"""
GUI для системы деидентификации документов.

Запуск:
    python gui/app.py
"""

import os
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Делаем корень проекта доступным для импортов
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gui.worker import PipelineWorker
from gui.dialogs import AskDialog, ResultDialog, ConfirmDialog
from gui.storage import HistoryStorage


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

TARGET_TYPES = [
    ("ИНН",         "INN",      True),
    ("КПП",         "KPP",      True),
    ("ОГРН/ОГРНИП", "OGRN",     True),
    ("Телефоны",    "PHONE",    True),
    ("E-mail",      "EMAIL",    True),
    ("ФИО",         "FIO",      True),
    ("Адреса",      "ADDRESS",  True),
    ("Стороны",     "PARTY",    True),
    ("Паспорт",     "PASSPORT", False),
]

SUPPORTED_EXTS = {".docx", ".xlsx", ".pdf"}


# ---------------------------------------------------------------------------
# Главное приложение
# ---------------------------------------------------------------------------

class App(ctk.CTk):

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Деидентификация документов")
        self.geometry("1200x850")
        self.minsize(1000, 720)

        self.file_path = ctk.StringVar(value="")
        self.custom_types_input = ctk.StringVar(value="")

        self.type_vars = {
            code: ctk.BooleanVar(value=checked)
            for _, code, checked in TARGET_TYPES
        }

        # Применённые кастомные типы (список строк). Чипсы показываются под полем.
        self.applied_custom_types: list[str] = []

        # История обработок
        self.history = HistoryStorage()

        self.worker = PipelineWorker(
            log_callback=self._enqueue_log,
            done_callback=self._on_done,
            ask_callback=self._ask_from_worker,
        )

        self._log_buffer = []
        self._log_lock = threading.Lock()

        self._build_ui()
        self._drain_logs()
        self._refresh_history_view()

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        # ============ Заголовок ============
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            header,
            text="Деидентификация документов",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="Локальный мультиагентный помощник для обезличивания PDF / DOCX / XLSX",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
        ).pack(anchor="w", pady=(2, 0))

        # ============ Основная область: слева настройки, справа история ============
        main_row = ctk.CTkFrame(self, fg_color="transparent")
        main_row.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        # --- Левая колонка ---
        left_col = ctk.CTkFrame(main_row, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True)

        # --- Правая колонка: история ---
        right_col = ctk.CTkFrame(main_row, width=320, fg_color="transparent")
        right_col.pack(side="right", fill="y", padx=(14, 0))
        right_col.pack_propagate(False)

        # ============ Карточка выбора файла ============
        file_card = ctk.CTkFrame(left_col)
        file_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            file_card,
            text="Документ",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 4))

        ctk.CTkEntry(
            file_card,
            textvariable=self.file_path,
            placeholder_text="Путь к файлу (.docx / .xlsx / .pdf)",
            height=36,
        ).grid(row=1, column=0, sticky="ew", padx=(14, 8), pady=(0, 14))

        ctk.CTkButton(
            file_card,
            text="Обзор...",
            width=110,
            height=36,
            command=self._pick_file,
        ).grid(row=1, column=1, sticky="e", padx=(0, 14), pady=(0, 14))

        file_card.grid_columnconfigure(0, weight=1)

        # ============ Карточка типов ============
        types_card = ctk.CTkFrame(left_col)
        types_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            types_card,
            text="Что маскировать",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 6))

        # Чекбоксы
        for i, (label, code, _) in enumerate(TARGET_TYPES):
            r = 1 + i // 3
            c = i % 3
            ctk.CTkCheckBox(
                types_card,
                text=label,
                variable=self.type_vars[code],
                font=ctk.CTkFont(size=12),
            ).grid(row=r, column=c, sticky="w", padx=14, pady=6)

        checkbox_rows = 1 + (len(TARGET_TYPES) - 1) // 3  # последняя строка чекбоксов
        base_row = checkbox_rows + 1

        # Разделитель
        ctk.CTkFrame(types_card, height=1, fg_color="#3a3a3a").grid(
            row=base_row, column=0, columnspan=3,
            sticky="ew", padx=14, pady=(10, 4),
        )

        # Заголовок кастомных типов
        ctk.CTkLabel(
            types_card,
            text="Свои типы данных",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=base_row + 1, column=0, columnspan=3,
               sticky="w", padx=14, pady=(8, 2))

        # Поле ввода + кнопка «Применить»
        custom_row = ctk.CTkFrame(types_card, fg_color="transparent")
        custom_row.grid(row=base_row + 2, column=0, columnspan=3,
                        sticky="ew", padx=14, pady=(0, 6))
        custom_row.grid_columnconfigure(0, weight=1)

        self.custom_entry = ctk.CTkEntry(
            custom_row,
            textvariable=self.custom_types_input,
            placeholder_text="Введите тип и нажмите «Применить»",
            height=36,
        )
        self.custom_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.custom_entry.bind("<Return>", lambda e: self._apply_custom_type())

        ctk.CTkButton(
            custom_row,
            text="Применить",
            width=120,
            height=36,
            command=self._apply_custom_type,
        ).grid(row=0, column=1, sticky="e")

        # Контейнер для чипсов применённых типов
        self.chips_frame = ctk.CTkFrame(types_card, fg_color="transparent")
        self.chips_frame.grid(row=base_row + 3, column=0, columnspan=3,
                              sticky="ew", padx=14, pady=(0, 14))

        # ============ Кнопка запуска + прогресс ============
        action_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        action_frame.pack(fill="x", pady=(0, 6))

        self.run_btn = ctk.CTkButton(
            action_frame,
            text="▶  Обработать документ",
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._run_pipeline,
        )
        self.run_btn.pack(side="left")

        self.progress = ctk.CTkProgressBar(action_frame, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self.progress.set(0)

        # ============ Лог ============
        log_card = ctk.CTkFrame(left_col)
        log_card.pack(fill="both", expand=True, pady=(6, 0))

        ctk.CTkLabel(
            log_card,
            text="Журнал выполнения",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(12, 4))

        self.log_box = ctk.CTkTextbox(
            log_card,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log_box.configure(state="disabled")

        # ============ История (правая колонка) ============
        history_card = ctk.CTkFrame(right_col)
        history_card.pack(fill="both", expand=True)

        header_h = ctk.CTkFrame(history_card, fg_color="transparent")
        header_h.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header_h,
            text="История",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header_h,
            text="Очистить",
            width=90,
            height=28,
            fg_color="#6b7280",
            hover_color="#4b5563",
            command=self._clear_history,
        ).pack(side="right")

        self.history_scroll = ctk.CTkScrollableFrame(history_card, width=280)
        self.history_scroll.pack(fill="both", expand=True, padx=10, pady=(4, 12))

    # ---------------------------------------------------------------- Custom types

    def _apply_custom_type(self):
        """Добавляет введённые типы в список применённых и очищает поле."""
        raw = self.custom_types_input.get().strip()
        if not raw:
            return

        added = False
        for chunk in raw.replace(";", ",").replace("\n", ",").split(","):
            name = chunk.strip()
            if not name:
                continue
            # не дублируем
            if name.lower() in {t.lower() for t in self.applied_custom_types}:
                continue
            self.applied_custom_types.append(name)
            added = True

        self.custom_types_input.set("")
        if added:
            self._render_chips()

    def _render_chips(self):
        for w in self.chips_frame.winfo_children():
            w.destroy()

        if not self.applied_custom_types:
            ctk.CTkLabel(
                self.chips_frame,
                text="Свои типы не добавлены",
                font=ctk.CTkFont(size=11),
                text_color="#6b7280",
            ).pack(anchor="w")
            return

        for i, name in enumerate(self.applied_custom_types):
            chip = ctk.CTkFrame(self.chips_frame, corner_radius=12,
                                fg_color="#1f6aa5")
            chip.pack(side="left", padx=(0, 6), pady=2)

            ctk.CTkLabel(
                chip,
                text=name,
                font=ctk.CTkFont(size=11),
                text_color="#ffffff",
            ).pack(side="left", padx=(10, 4), pady=3)

            ctk.CTkButton(
                chip,
                text="✕",
                width=20,
                height=20,
                corner_radius=10,
                fg_color="transparent",
                hover_color="#2a86c9",
                command=lambda n=name: self._remove_custom_type(n),
            ).pack(side="left", padx=(0, 4), pady=3)

    def _remove_custom_type(self, name: str):
        self.applied_custom_types = [
            t for t in self.applied_custom_types if t != name
        ]
        self._render_chips()

    def _collect_target_types(self):
        """Финальный список типов: чекбоксы + применённые кастомные."""
        types = [code for _, code, _ in TARGET_TYPES if self.type_vars[code].get()]
        for name in self.applied_custom_types:
            if name.upper() in {t.upper() for t in types}:
                continue
            types.append(name)
        return types

    # ---------------------------------------------------------------- History

    def _refresh_history_view(self):
        for w in self.history_scroll.winfo_children():
            w.destroy()

        items = self.history.all()
        if not items:
            ctk.CTkLabel(
                self.history_scroll,
                text="Пока пусто.\nОбработайте документ — запись появится здесь.",
                font=ctk.CTkFont(size=11),
                text_color="#6b7280",
                justify="left",
            ).pack(anchor="w", padx=4, pady=10)
            return

        for entry in items:
            self._add_history_item(entry)

    def _add_history_item(self, entry: dict):
        card = ctk.CTkFrame(self.history_scroll, corner_radius=8)
        card.pack(fill="x", pady=4, padx=2)

        src = entry.get("source_file", "")
        src_name = os.path.basename(src) if src else "?"
        ts = entry.get("timestamp", "").replace("T", " ")

        title_lbl = ctk.CTkLabel(
            card,
            text=src_name,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=230,
        )
        title_lbl.pack(anchor="w", padx=10, pady=(8, 0))

        ctk.CTkLabel(
            card,
            text=ts,
            font=ctk.CTkFont(size=10),
            text_color="#9ca3af",
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(0, 6))

        # Клик по всей карточке открывает ResultDialog
        def _open(_e, e=entry):
            ResultDialog(self, {
                "masked": e.get("masked", ""),
                "report_json": e.get("report_json", ""),
                "report_txt": e.get("report_txt", ""),
            })

        for widget in (card, title_lbl):
            widget.bind("<Button-1>", _open)
            try:
                widget.configure(cursor="hand2")
            except Exception:
                pass

    def _clear_history(self):
        from tkinter import messagebox as mb

        items = self.history.all()
        if not items:
            mb.showinfo("История", "История уже пуста.")
            return

        # Считаем, сколько файлов реально существует
        existing = 0
        for it in items:
            for key in ("masked", "report_json", "report_txt"):
                p = it.get(key, "")
                if p and os.path.exists(p):
                    existing += 1

        msg = (
            f"Удалить все записи истории ({len(items)}) и связанные файлы?\n\n"
            f"На диске найдено {existing} файл(ов), они будут удалены безвозвратно.\n\n"
            f"Продолжить?"
        )
        if not mb.askyesno("Очистить историю", msg):
            return

        result = self.history.clear_with_files()

        deleted = result.get("deleted", [])
        failed = result.get("failed", [])

        self._refresh_history_view()

        if failed:
            mb.showwarning(
                "Очистка завершена с ошибками",
                f"Удалено файлов: {len(deleted)}\n\n"
                f"Не удалось удалить ({len(failed)}):\n" + "\n".join(failed[:5]),
            )
        else:
            mb.showinfo(
                "Готово",
                f"История очищена.\nУдалено файлов: {len(deleted)}",
            )

    # ---------------------------------------------------------------- Events

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title="Выберите документ",
            filetypes=[
                ("Документы", "*.docx *.xlsx *.pdf"),
                ("Word", "*.docx"),
                ("Excel", "*.xlsx"),
                ("PDF", "*.pdf"),
                ("Все файлы", "*.*"),
            ],
        )
        if path:
            self.file_path.set(path)

    def _run_pipeline(self):
        path = self.file_path.get().strip().strip('"')
        if not path:
            messagebox.showwarning("Внимание", "Выберите файл для обработки.")
            return
        if not os.path.exists(path):
            messagebox.showerror("Ошибка", f"Файл не найден:\n{path}")
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTS:
            messagebox.showerror(
                "Ошибка",
                f"Неподдерживаемый формат: {ext}\nПоддерживаются: .docx, .xlsx, .pdf",
            )
            return

        types = self._collect_target_types()
        if not types:
            messagebox.showwarning(
                "Внимание",
                "Выберите хотя бы один тип сущностей "
                "или добавьте свои через «Применить».",
            )
            return

        # Проверка на повторную обработку.
        # ВАЖНО: используем ask_sync, потому что _run_pipeline вызывается
        # из главного потока (нажатие кнопки). ConfirmDialog.ask() здесь
        # приведёт к дедлоку.
        if self.history.has_source(path):
            confirm = ConfirmDialog.ask_sync(
                self,
                "Файл уже обрабатывался",
                f"Файл:\n{path}\n\nуже есть в истории.\n\n"
                f"Пересоздать результат? Будет создан новый файл "
                f"с суффиксом _v2, _v3 и т.д. Старые результаты останутся.",
            )
            if not confirm:
                return
            # Удаляем старые записи по этому источнику
            self.history.remove_by_source(path)

        self._clear_log()
        self.run_btn.configure(state="disabled", text="⏳ Обработка...")
        self.progress.start()

        self._current_source = path
        self.worker.start(path, types)

    def _on_done(self, result, error):
        self.after(0, lambda: self._finalize(result, error))

    def _finalize(self, result, error):
        self.progress.stop()
        self.progress.set(0)
        self.run_btn.configure(state="normal", text="▶  Обработать документ")

        if error is not None:
            self._append_log(f"\n⚠️ Ошибка: {error}")
            messagebox.showerror("Ошибка обработки", str(error))
            return

        if result:
            self._append_log("\n✨ Готово.")

            # Сохраняем в историю
            src = getattr(self, "_current_source", "")
            if src:
                self.history.add(src, result)
                self._refresh_history_view()

            ResultDialog(self, result)

    # ---------------------------------------------------------------- Input from worker

    def _ask_from_worker(self, prompt: str) -> str:
        answer_holder = {"answer": ""}
        done_event = threading.Event()

        def show_dialog():
            AskDialog(self, prompt, answer_holder, done_event)

        self.after(0, show_dialog)
        done_event.wait()
        return answer_holder["answer"]

    # ---------------------------------------------------------------- Logs

    def _enqueue_log(self, text: str):
        with self._log_lock:
            self._log_buffer.append(text)

    def _drain_logs(self):
        with self._log_lock:
            lines = self._log_buffer[:]
            self._log_buffer.clear()

        for line in lines:
            self._append_log(line)

        self.after(120, self._drain_logs)

    def _append_log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()
    app.mainloop()