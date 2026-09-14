"""Модальные окна для GUI."""

import os
import sys
import threading

import customtkinter as ctk


def open_path(path: str) -> None:
    """Открывает файл или папку в системном приложении."""
    if not os.path.exists(path):
        return
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


class AskDialog(ctk.CTkToplevel):
    """Модальное окно вопроса валидатора.

    Открывается из главного потока, а возвращает ответ в worker-поток
    через threading.Event.
    """

    def __init__(
        self,
        master,
        prompt_text: str,
        answer_holder: dict,
        done_event: threading.Event,
    ):
        super().__init__(master)
        self.title("Уточнение от валидатора")
        self.geometry("640x360")
        self.resizable(True, True)
        self.answer_holder = answer_holder
        self.done_event = done_event

        self.transient(master)
        self.grab_set()

        # Текст вопроса
        ctk.CTkLabel(
            self,
            text="Валидатор требует уточнения",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(16, 6), padx=16, anchor="w")

        textbox = ctk.CTkTextbox(self, wrap="word", height=180)
        textbox.pack(fill="both", expand=True, padx=16, pady=6)
        textbox.insert("1.0", prompt_text)
        textbox.configure(state="disabled")

        # Поле ввода
        ctk.CTkLabel(self, text="Ваш ответ:").pack(anchor="w", padx=16, pady=(6, 2))
        self.entry = ctk.CTkEntry(self, height=36)
        self.entry.pack(fill="x", padx=16)
        self.entry.bind("<Return>", lambda e: self._submit())

        # Кнопки
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=14)

        ctk.CTkButton(
            btn_frame,
            text="Пропустить",
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=self._skip,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_frame, text="Ответить", command=self._submit
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.after(100, self.entry.focus_set)

    def _submit(self) -> None:
        self.answer_holder["answer"] = self.entry.get().strip()
        self.done_event.set()
        self.destroy()

    def _skip(self) -> None:
        self.answer_holder["answer"] = ""
        self.done_event.set()
        self.destroy()


class ResultDialog(ctk.CTkToplevel):
    """Окно с результатами — кнопки открытия файлов."""

    def __init__(self, master, result: dict):
        super().__init__(master)
        self.title("Обработка завершена")
        self.geometry("520x280")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="✅ Документ обезличен успешно",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#22c55e",
        ).pack(pady=(20, 12))

        for label, key in [
            ("Открыть документ", "masked"),
            ("Открыть отчёт JSON", "report_json"),
            ("Открыть отчёт TXT", "report_txt"),
        ]:
            path = result.get(key)
            if not path:
                continue
            ctk.CTkButton(
                self,
                text=label,
                width=380,
                command=lambda p=path: open_path(p),
            ).pack(pady=4)

        ctk.CTkButton(
            self,
            text="Закрыть",
            fg_color="#6b7280",
            hover_color="#4b5563",
            width=380,
            command=self.destroy,
        ).pack(pady=(12, 16))


class ConfirmDialog(ctk.CTkToplevel):
    """Модальное окно подтверждения.

    Два способа использования:

    1) Из главного потока (например, из обработчика кнопки):
        result = ConfirmDialog.ask_sync(master, title, message)
        if result: ...

       Блокирует только текущий обработчик, но mainloop продолжает
       крутиться и диалог корректно отрисовывается.

    2) Из worker-потока (если понадобится):
        result = ConfirmDialog.ask(master, title, message)

       Использует master.after() + threading.Event.
    """

    def __init__(
        self,
        master,
        title: str,
        message: str,
        holder: dict,
        done_event: threading.Event | None = None,
    ):
        super().__init__(master)
        self.title(title)
        self.geometry("500x220")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.holder = holder
        self.done_event = done_event

        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(pady=(20, 8), padx=20, anchor="w")

        msg_box = ctk.CTkTextbox(self, wrap="word", height=90)
        msg_box.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        msg_box.insert("1.0", message)
        msg_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkButton(
            btn_frame,
            text="Отмена",
            fg_color="#6b7280",
            hover_color="#4b5563",
            width=140,
            command=self._cancel,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_frame,
            text="Пересоздать",
            width=160,
            command=self._confirm,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _confirm(self):
        self.holder["result"] = True
        if self.done_event is not None:
            self.done_event.set()
        self.destroy()

    def _cancel(self):
        self.holder["result"] = False
        if self.done_event is not None:
            self.done_event.set()
        self.destroy()

    # ------------------------------------------------------------------ API

    @classmethod
    def ask_sync(cls, master, title: str, message: str) -> bool:
        """Синхронный вызов ИЗ ГЛАВНОГО ПОТОКА.

        Использует wait_window() — tkinter временно пускает event-loop,
        диалог отрисовывается, а управление возвращается в вызывающий
        обработчик после закрытия окна.
        """
        holder = {"result": False}
        dialog = cls(master, title, message, holder, done_event=None)
        dialog.wait_window()
        return holder.get("result", False)

    @classmethod
    def ask(cls, master, title: str, message: str) -> bool:
        """Синхронный вызов ИЗ WORKER-ПОТОКА.

        Открывает диалог в главном потоке через after(), ждёт ответа
        через threading.Event. Работает только если главный поток
        свободен и продолжает крутить mainloop.
        """
        holder = {"result": False}
        done = threading.Event()

        def show():
            cls(master, title, message, holder, done_event=done)

        master.after(0, show)
        done.wait()
        return holder.get("result", False)