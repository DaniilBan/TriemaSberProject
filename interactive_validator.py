import json
import re
from typing import Dict, List, Tuple, Any


class InteractiveValidator:
    """
    Валидатор полноты извлеченных данных на базе LLM с поддержкой
    интерактивного диалога для уточнения неопределенностей.
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    def _build_validation_prompt(self, document_text: str, extracted_entities: Dict[str, str]) -> str:
        return f"""
Ты — модуль валидации и контроля качества извлечения данных из документов.
Твоя задача — проверить, все ли обязательные сущности (ФИО, телефоны, реквизиты, суммы, роли Сторон) были найдены, и нет ли неопределенностей.

Текст документа (фрагмент/целиком):
\"\"\"
{document_text[:3000]}
\"\"\"

Найденные на данный момент сущности и их маски:
{json.dumps(extracted_entities, ensure_ascii=False, indent=2)}

Инструкция:
1. Проанализируй текст и текущий список сущностей.
2. Проверь:
   - Все ли важные конфиденциальные данные найдены?
   - Определены ли четко роли (кто Поставщик/Исполнитель, кто Покупатель/Заказчик)?
   - Нет ли двусмысленных данных (например, фамилия упоминается, но не ясно, относится ли она к Покупателю)?
3. Если данных достаточно и нет неопределенностей, верни: "status": "COMPLETE".
4. Если есть неопределенности или пропуски, верни "status": "NEEDS_CLARIFICATION" и составь список конкретных уточняющих вопросов для пользователя.

Верни ответ СТРОГО в формате JSON без каких-либо вводных слов и текста вне JSON.
Формат ответа:
{{
  "status": "COMPLETE",
  "questions": [],
  "missing_entities_candidates": []
}}
"""

    def _parse_json_from_response(self, response_text: str) -> dict:
        """Вспомогательный метод для безошибочного извлечения JSON из ответа LLM."""
        try:
            # Ищем фигурные скобки с содержимым (включая переводы строк)
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

        # Безопасное извлечение JSON
        validation_result = self._parse_json_from_response(response_raw)

        # Если распарсить результат не удалось, сохраняем то, что уже было найдено
        if not validation_result:
            print("[INFO] Не удалось распарсить ответ валидатора. Используются первичные сущности.")
            return current_replacements

        # Проверка статуса
        if validation_result.get("status") == "COMPLETE":
            print("[INFO] Проверка полноты завершена успешно. Неопределенностей не обнаружено.")
            return current_replacements

        # Если требуются уточнения
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