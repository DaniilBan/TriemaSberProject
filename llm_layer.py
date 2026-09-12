import json
import os
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# Импортируем интерфейс проекта
from interfaces import LLMInterface, MaskedEntity, ParsedDocument

try:
    from gigachat import GigaChat

    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False


class ExtractionResult(BaseModel):
    entities: List[Dict[str, Any]] = Field(
        description="Список найденных конфиденциальных сущностей"
    )


class GigaChatLLM(LLMInterface):


    def _clean_text_for_llm(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r'\s+', ' ', text)
        return cleaned.strip()

    def __init__(self, credentials: Optional[str] = None, model_name: str = "GigaChat"):

        if not GIGACHAT_AVAILABLE:
            raise ImportError("Пакет 'gigachat' не установлен. Установите через: pip install gigachat")

        self.credentials = credentials or os.getenv("GIGACHAT_CREDENTIALS")

        if not self.credentials:
            raise ValueError(
                "Не указаны credentials для GigaChat. Передайте параметр credentials в конструктор "
                "или установите переменную окружения GIGACHAT_CREDENTIALS в .env файле."
            )

        self.model_name = model_name

        self.client = GigaChat(
            credentials=self.credentials,
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            verify_ssl_certs=False,
            model=self.model_name
        )

    def generate(self, prompt: str, **kwargs) -> str:

        response = self.client.chat(prompt)
        return response.choices[0].message.content

    def chat_with_history(self, messages: list) -> str:

        payload = {
            "model": self.model_name,
            "messages": messages
        }
        response = self.client.chat(payload)
        return response.choices[0].message.content

    def get_embedding(self, text: str) -> List[float]:

        response = self.client.embeddings(texts=[text])
        return response.data[0].embedding

    def extract_entities(self, parsed_doc: ParsedDocument, target_types: List[str]) -> List[MaskedEntity]:
        if not parsed_doc or not parsed_doc.full_text or not parsed_doc.full_text.strip():
            return []

        clean_text = self._clean_text_for_llm(parsed_doc.full_text)
        text_to_analyze = clean_text[:15000]

        prompt = f"""ТВОЯ РОЛЬ:
Ты — легковесный NER-движок (модуль извлечения данных), работающий в составе мультиагентной системы деидентификации.
Твоя единственная задача — высокоточное распознавание конфиденциальных сущностей в готовом плоском тексте.
Ты НЕ работаешь с файлами напрямую, не меняешь структуру документа, не занимаешься его версткой и не сохраняешь файлы.
Твой приоритет — максимальная полнота (recall) при строгом соблюдении заданного JSON-формата.

Проанализируй текст документа и найди в нем все упоминания следующих типов данных: {target_types}.

ОГРАНИЧЕНИЯ СРЕДЫ И РЕСУРСЫ:
1. Выдавай ответ мгновенно. Никакой вежливой беседы, приветствий, вводных фраз или пояснений. Ответ должен начинаться сразу с открывающей фигурной скобки '{{'.
2. Инвариантность текста: сохраняй каждый символ исходного текста (UTF-8, \\n, \\t, пробелы). Не проводи лингвистическую нормализацию, не исправляй опечатки и не меняй регистр букв в поле 'original_text'.
3. Если сущность найдена внутри слова или разрезана переносом строки — не пытайся её склеить или расширить, извлекай ровно то, что присутствует в тексте.

СПЕЦИАЛЬНЫЕ ПРАВИЛА ИЗВЛЕЧЕНИЯ:
1. **FIO (ФИО):** Извлекай как полные имена (Иванов Иван Иванович), так и сокращения с инициалами (Соколов Д.А., Д.А. Соколов).
2. **KPP (КПП):** Обязательно извлекай 9-значные коды КПП (например, 366601010, КПП 366201001).
3. **PHONE (Телефоны):** Извлекай ВСЕ номера телефонов независимо от формата (+7 (473) 255-43-21, 84732554321, 255-43-21 и т.д.).
4. **ADDRESS (Адреса):** Извлекай любые адреса целиком, включая юр. адреса, факические адреса, номера офисов, зданий и строений (например, '394006, г. Воронеж, ул. Свободы, д. 73, офис 402').
5. **PARTY (Стороны договора):**
   - Для Поставщика/Исполнителя/Продавца указывай entity_type = 'SUPPLIER'.
   - Для Покупателя/Заказчика/Клиента указывай entity_type = 'BUYER'.
   - Если роль неясна, указывай entity_type = 'PARTY'.

ПРАВИЛА ДЛЯ ТИПА 'PARTY' (Стороны договора):
Если в {target_types} присутствует 'PARTY':
- Для стороны, выступающей Поставщиком / Исполнителем / Продавцом / Подрядчиком, указывай entity_type = 'SUPPLIER'.
- Для стороны, выступающей Покупателем / Заказчиком / Клиентом, указывай entity_type = 'BUYER'.
- Если конкретную роль определить невозможно, указывай entity_type = 'PARTY'.

ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ:
В поле 'target_types_received' перечисли ВСЕ типы сущностей, которые тебя попросили найти в этом запросе: {target_types}.

Ответ должен быть СТРОГО валидным JSON-объектом без Markdown-разметки (не используй ```json ... ```).

Структура JSON:
{{
  "target_types_received": {target_types},
  "entities": [
    {{
      "original_text": "ТОЧНЫЙ_ТЕКСТ_ИЗ_ДОКУМЕНТА",
      "entity_type": "ТИП_СУЩНОСТИ",
      "confidence": 0.95,
      "redacted_placeholder": "[МАРКЕР_ЗАМЕНЫ]"
    }}
  ]
}}

Текст документа для анализа:
---
{text_to_analyze}
---"""

        raw_response = self.generate(prompt)
        return self._parse_llm_json_response(raw_response, parsed_doc.full_text)

    def _parse_llm_json_response(self, raw_response: str, full_text: str) -> List[MaskedEntity]:
        masked_entities = []
        try:
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                return []

            data = json.loads(json_match.group(0))

            received_types = data.get("target_types_received", [])
            print(f"\n🤖 [GigaChat ответил]: Я ищу следующие типы сущностей: {received_types}\n")

            entities_list = data.get("entities", [])
            for item in entities_list:
                orig_text = item.get("original_text", "").strip()
                entity_type = item.get("entity_type", "UNKNOWN")
                confidence = float(item.get("confidence", 1.0))

                if not orig_text:
                    continue

                for match in re.finditer(re.escape(orig_text), full_text):
                    masked_entities.append(
                        MaskedEntity(
                            original_text=orig_text,
                            masked_text=f"[{entity_type}_REDACTED]",
                            start_pos=match.start(),
                            end_pos=match.end(),
                            entity_type=entity_type,
                            confidence=confidence
                        )
                    )

        except Exception as e:
            print(f"❌ Ошибка парсинга ответа LLM: {e}")

        return masked_entities


class LocalOllamaLLM(LLMInterface):


    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def generate(self, prompt: str, **kwargs) -> str:
        return '{"entities": []}'

    def chat_with_history(self, messages: list) -> str:
        return "Локальная модель не поддерживает контекст диалога."

    def get_embedding(self, text: str) -> List[float]:
        return []

    def extract_entities(self, parsed_doc: ParsedDocument, target_types: List[str]) -> List[MaskedEntity]:
        print("⚠️ Используется фоллбэк LocalOllamaLLM: сущности не извлечены.")
        return []