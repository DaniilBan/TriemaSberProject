import json
import os
from datetime import datetime
from typing import Dict, Any, List


class ReportGenerator:
    """Генератор отчетов о замене конфиденциальных данных."""

    @staticmethod
    def save_json_report(
            input_filename: str,
            output_filename: str,
            initial_replacements: List[Dict[str, Any]],
            final_replacements: List[Dict[str, Any]],
            report_path: str = None
    ) -> str:
        """
        Сохраняет отчет о заменах в формате JSON.
        """
        if not report_path:
            base_name = os.path.splitext(output_filename)[0]
            report_path = f"{base_name}_report.json"

        report_data = {
            "timestamp": datetime.now().isoformat(),
            "source_file": input_filename,
            "masked_file": output_filename,
            "stats": {
                "initial_detected_count": len(initial_replacements),
                "final_masked_count": len(final_replacements)
            },
            "initial_replacements": initial_replacements,
            "final_replacements": final_replacements
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=4)

        return report_path

    @staticmethod
    def save_txt_report(
            input_filename: str,
            output_filename: str,
            initial_replacements: List[Dict[str, Any]],
            final_replacements: List[Dict[str, Any]],
            report_path: str = None
    ) -> str:
        """
        Сохраняет человекочитаемый отчет в формате TXT.
        """
        if not report_path:
            base_name = os.path.splitext(output_filename)[0]
            report_path = f"{base_name}_report.txt"

        lines = [
            "=" * 60,
            "ОТЧЕТ О МАСКИРОВАНИИ КОНФИДЕНЦИАЛЬНЫХ ДАННЫХ",
            "=" * 60,
            f"Дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Исходный файл: {input_filename}",
            f"Итоговый файл: {output_filename}",
            "-" * 60,
            f"Найдено сущностей (первично): {len(initial_replacements)}",
            f"Применено замен (итого)     : {len(final_replacements)}",
            "=" * 60,
            "\n[ИТОГОВЫЙ СПИСОК ЗАМЕН]",
        ]

        for idx, item in enumerate(final_replacements, start=1):
            text = item.get("text") or item.get("value") or "N/A"
            entity_type = item.get("type") or item.get("entity_type") or "UNKNOWN"
            mask = item.get("mask") or item.get("replacement") or "[MASKED]"

            lines.append(f"{idx}. [{entity_type}] '{text}' -> '{mask}'")

        lines.append("\n" + "=" * 60)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path