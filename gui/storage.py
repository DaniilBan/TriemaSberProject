"""Хранение истории обработок в JSON-файле."""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


class HistoryStorage:

    def __init__(self, path: Optional[str] = None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "history.json")
        self.path = path
        self._items: List[Dict[str, Any]] = self._load()

    # ---------------------------------------------------------------- internal

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------------------------------------------------------- public

    def all(self) -> List[Dict[str, Any]]:
        """Возвращает историю, свежие записи первыми."""
        return list(reversed(self._items))

    def has_source(self, source_path: str) -> bool:
        """True, если файл с таким путём уже обрабатывался."""
        norm = os.path.abspath(source_path).lower()
        return any(
            os.path.abspath(it.get("source_file", "")).lower() == norm
            for it in self._items
        )

    def add(self, source_file: str, result: Dict[str, str]) -> Dict[str, Any]:
        """Добавляет запись (или заменяет существующую по этому источнику)."""
        norm = os.path.abspath(source_file).lower()

        # Убираем старые записи по этому же source_file — для случая
        # «пересоздать»: остаётся только одна актуальная запись.
        self._items = [
            it for it in self._items
            if os.path.abspath(it.get("source_file", "")).lower() != norm
        ]

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "source_file": os.path.abspath(source_file),
            "masked": result.get("masked", ""),
            "report_json": result.get("report_json", ""),
            "report_txt": result.get("report_txt", ""),
        }
        self._items.append(entry)
        self._save()
        return entry

    def remove_by_source(self, source_path: str) -> None:
        """Удаляет старые записи по этому source_file (без удаления файлов)."""
        norm = os.path.abspath(source_path).lower()
        self._items = [
            it for it in self._items
            if os.path.abspath(it.get("source_file", "")).lower() != norm
        ]
        self._save()

    # ---------------------------------------------------------------- удаление файлов

    def remove_files_for_entry(self, entry: Dict[str, Any]) -> Dict[str, List[str]]:
        """Удаляет с диска все файлы, привязанные к записи истории.

        Возвращает {"deleted": [...], "failed": [...]}.
        """
        deleted: List[str] = []
        failed: List[str] = []

        paths = [
            entry.get("masked", ""),
            entry.get("report_json", ""),
            entry.get("report_txt", ""),
        ]

        for p in paths:
            if not p:
                continue
            if not os.path.exists(p):
                continue
            try:
                os.remove(p)
                deleted.append(p)
            except Exception as exc:
                failed.append(f"{p}: {exc}")

        return {"deleted": deleted, "failed": failed}

    def clear_with_files(self) -> Dict[str, List[str]]:
        """Удаляет все записи истории И все связанные файлы на диске.

        Возвращает {"deleted": [...], "failed": [...]}.
        """
        deleted: List[str] = []
        failed: List[str] = []

        for entry in list(self._items):
            result = self.remove_files_for_entry(entry)
            deleted.extend(result["deleted"])
            failed.extend(result["failed"])

        self._items = []
        self._save()

        return {"deleted": deleted, "failed": failed}

    def clear(self) -> None:
        """Очищает только записи, файлы остаются на диске."""
        self._items = []
        self._save()