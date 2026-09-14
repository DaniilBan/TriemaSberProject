"""
Запуск run_pipeline в отдельном потоке с перехватом stdout и input().

GUI читает логи из очереди через .after() и не подвисает.
"""

import builtins
import threading
from typing import Callable, Dict, List, Optional


class PipelineWorker:

    def __init__(
        self,
        log_callback: Callable[[str], None],
        done_callback: Callable[[Optional[Dict], Optional[Exception]], None],
        ask_callback: Optional[Callable[[str], str]] = None,
    ):
        """
        Args:
            log_callback: вызывается при каждом print() из пайплайна.
            done_callback: вызывается после завершения (успех или ошибка).
            ask_callback: то, что будет вызвано вместо input().
        """
        self.log_callback = log_callback
        self.done_callback = done_callback
        self.ask_callback = ask_callback
        self.thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(
        self,
        file_path: str,
        target_types: List[str],
        output_path: Optional[str] = None,
    ) -> None:
        if self.is_running():
            return
        self._stop_flag.clear()
        self.thread = threading.Thread(
            target=self._run,
            args=(file_path, target_types, output_path),
            daemon=True,
        )
        self.thread.start()

    def _run(self, file_path, target_types, output_path):
        # Импорт внутри — чтобы не подтягивать тяжёлые модули до нажатия кнопки
        from main import run_pipeline

        original_print = builtins.print
        original_input = builtins.input

        def gui_print(*args, **kwargs):
            text = " ".join(str(a) for a in args)
            self.log_callback(text)

        def gui_input(prompt: str = "") -> str:
            if self.ask_callback is not None:
                return self.ask_callback(prompt)
            return ""

        builtins.print = gui_print
        builtins.input = gui_input

        result = None
        error = None
        try:
            result = run_pipeline(
                file_path=file_path,
                output_path=output_path,
                target_types=target_types,
                ask_callback=self.ask_callback,
            )
        except Exception as exc:
            error = exc
        finally:
            builtins.print = original_print
            builtins.input = original_input
            self.done_callback(result, error)