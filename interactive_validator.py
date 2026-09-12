import json
import re
from typing import Dict, List, Tuple, Any


class InteractiveValidator:

    def __init__(self, llm_client):
        self.llm = llm_client

    def _build_validation_prompt(self, document_text: str, extracted_entities: Dict[str, str]) -> str:
        return f"""Ты — модуль валидации и контроля качества извлечения конфиденциальных данных из документов.
Твоя задача — проверить полноту извлечения сущностей на основе предоставленного текста и результатов первичного распознавания.

Текст документа:
\"\"\"
{document_text}
\"\"\"

Найденные на данный момент сущности и их маски:
{json.dumps(extracted_entities, ensure_ascii=False, indent=2)}

Инструкция по проверке:
1. Изучи типы данных среди УЖЕ найденных сущностей (entity_type). Ищи пропуски ИСКЛЮЧИТЕЛЬНО для этих типов.
2. Проверь полноту: нет ли в тексте явно пропущенных сущностей аналогичных типов (например, ИНН Заказчика замаскирован, а ИНН Поставщика в реквизитах пропущен).
3. Проверь связность: если среди найденных типов есть Стороны договора ('BUYER' / 'SUPPLIER'), определены ли обе стороны и нет ли неопределенности в их реквизитах.
4. Критерии статуса:
   - Если явных пропусков найденных типов нет -> "status": "COMPLETE"
   - Если есть критические пропуски или неопределенности -> "status": "NEEDS_CLARIFICATION"

Верни ответ СТРОГО в формате JSON без каких-либо вводных слов, пояснений и Markdown-тегов.

Формат ответа:
{{
  "status": "COMPLETE",
  "questions": [],
  "missing_entities_candidates": []
}}

Пример при наличии пропусков:
{{
  "status": "NEEDS_CLARIFICATION",
  "questions": [
    "В реквизитах найден ИНН Поставщика, но само наименование организации пропущено. Обезличить 'ООО Вектор'?"
  ],
  "missing_entities_candidates": [
    {{
      "original_text": "ООО Вектор",
      "entity_type": "SUPPLIER",
      "reason": "Пропущено наименование организации в блоке реквизитов"
    }}
  ]
}}"""

    def _parse_json_from_response(self, response_text: str) -> dict:
        try:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            print(f"⚠️ Не удалось распарсить JSON из ответа LLM: {e}")
        return {}

    def validate_and_clarify(
            self,
            document_text: str,
            extracted_entities: Dict[str, str]
    ) -> Dict[str, str]:
        current_replacements = extracted_entities.copy()

        prompt = self._build_validation_prompt(document_text, current_replacements)
        response_raw = self.llm.generate(prompt)

        validation_result = self._parse_json_from_response(response_raw)

        if not validation_result:
            print("[INFO] Не удалось распарсить ответ валидатора. Используются первичные сущности.")
            return current_replacements

        if validation_result.get("status") == "COMPLETE":
            print("[INFO] Проверка полноты завершена успешно. Неопределенностей не обнаружено.")
            return current_replacements

        questions = validation_result.get("questions", [])
        if questions:
            print("\n" + "=" * 50)
            print(" ВНИМАНИЕ: Требуется уточнение данных перед маскированием!")
            print("=" * 50)

            for idx, question in enumerate(questions, 1):
                print(f"\nВопрос {idx}: {question}")
                user_answer = input("Ваш ответ (или нажмите Enter, чтобы пропустить): ").strip()

                if user_answer:
                    clarify_prompt = f"""
На основе ответа пользователя добавь или обнови пару в словаре replacements (что заменять -> на какую маску).
Вопрос был: {question}
Ответ пользователя: {user_answer}

Верни СТРОГО JSON объект с новыми парами для добавления в словарь замены, например:
{{"Иванов Иван Иванович": "[ПОКУПАТЕЛЬ_REDACTED]"}}
"""
                    new_pairs_raw = self.llm.generate(clarify_prompt)
                    new_pairs = self._parse_json_from_response(new_pairs_raw)
                    if new_pairs:
                        current_replacements.update(new_pairs)
                        print(f"-> Добавлено в маскирование: {new_pairs}")

        return current_replacements