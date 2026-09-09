import json
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# Импортируем интерфейс проекта
from interfaces import LLMInterface, MaskedEntity, ParsedDocument

# Попытка импорта официального SDK GigaChat
try:
    from gigachat import GigaChat

    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False


# --- 1. Модель структурированного ответа от LLM ---
class ExtractionResult(BaseModel):
    entities: List[Dict[str, Any]] = Field(
        description="Список найденных конфиденциальных сущностей"
    )


# --- 2. Реализация слоя GigaChat ---
class GigaChatLLM(LLMInterface):
    """
    Изолированный провайдер для работы с GigaChat.
    Отвечает за извлечение сущностей (ИНН, Телефоны, Поставщики и др.) из ParsedDocument.
    """

    def _clean_text_for_llm(self, text: str) -> str:
        """Нормализация текста для сглаживания разницы между PDF и DOCX"""
        if not text:
            return ""
        # Заменяем все разрывы и множественные пробелы на одиночные
        cleaned = re.sub(r'\s+', ' ', text)
        return cleaned.strip()

    def __init__(self, access_token: Optional[str] = None, model_name: str = "GigaChat"):
        """
        :param credentials: Токен авторизации GigaChat (или из переменной окружения GIGACHAT_CREDENTIALS)
        :param model_name: Название модели (GigaChat, GigaChat-Pro и т.д.)
        """
        if not GIGACHAT_AVAILABLE:
            raise ImportError("Пакет 'gigachat' не установлен. Установите через: pip install gigachat")

        self.access_token = access_token
        self.model_name = model_name
        # Отключаем верификацию SSL для работы с сертификатами Минцифры
        self.client = GigaChat(access_token=self.access_token, base_url="https://gigachat.devices.sberbank.ru/api/v1", verify_ssl_certs=False, model=self.model_name)

    def generate(self, prompt: str, **kwargs) -> str:
        """Базовый метод генерации текста"""
        response = self.client.chat(prompt)
        return response.choices[0].message.content

    def chat_with_history(self, messages: list) -> str:
        """
        Метод для ведения контекстного диалога с передачей истории сообщений.
        """
        payload = {
            "model": self.model_name,
            "messages": messages
        }
        response = self.client.chat(payload)
        return response.choices[0].message.content

    def get_embedding(self, text: str) -> List[float]:
        """Получение эмбеддингов текста"""
        response = self.client.embeddings(texts=[text])
        return response.data[0].embedding

    def extract_entities(self, parsed_doc: ParsedDocument, target_types: List[str]) -> List[MaskedEntity]:
        if not parsed_doc or not parsed_doc.full_text or not parsed_doc.full_text.strip():
            return []

        clean_text = self._clean_text_for_llm(parsed_doc.full_text)
        text_to_analyze = clean_text[:12000]

        prompt = f"""
Ты — AI-ассистент по деидентификации и анонимизации документов.
Проанализируй текст документа и найди в нем все упоминания следующих типов данных: {target_types}.

Особые правила для типа 'PARTY' (Стороны договора):
- Определи, кто является Поставщиком/Исполнителем/Продавцом (присвой entity_type = 'SUPPLIER').
- Определи, кто является Покупателем/Заказчиком/Клиентом (присвой entity_type = 'BUYER').

ОБЯЗАТЕЛЬНОЕ УСЛОВИЕ:
В поле 'target_types_received' перечисли ВСЕ типы сущностей, которые тебя попросили найти в этом запросе.

Ответ должен быть СТРОГО валидным JSON-объектом без вводных слов.
Структура JSON:
{{
  "target_types_received": ["ТИП_1", "ТИП_2"],
  "entities": [
    {{
      "original_text": "ТОЧНЫЙ_ТЕКСТ_ИЗ_ДОКУМЕНТА",
      "entity_type": "ТИП_СУЩНОСТИ",
      "confidence": 0.95
    }}
  ]
}}

Текст документа для анализа:
---
{text_to_analyze} 
---
"""
        raw_response = self.generate(prompt)
        return self._parse_llm_json_response(raw_response, parsed_doc.full_text)

    def _parse_llm_json_response(self, raw_response: str, full_text: str) -> List[MaskedEntity]:
        masked_entities = []
        try:
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                return []

            data = json.loads(json_match.group(0))

            # ВЫВОД В КОНСОЛЬ: что модель поняла из вашего промпта
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


# --- 3. Альтернативный провайдер для локальной модели (например, Ollama) ---
class LocalOllamaLLM(LLMInterface):
    """
    Заглушка/Альтернатива для локальных моделей (Ollama / Llama / Saiga).
    Позволяет соблюсти Пункт 6 ТЗ (быстрая замена модели без переписывания логики).
    """

    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def generate(self, prompt: str, **kwargs) -> str:
        # Здесь будет вызов локального API Ollama (http://localhost:11434/api/generate)
        return '{"entities": []}'

    def chat_with_history(self, messages: list) -> str:
        """Заглушка для локальной модели"""
        return "Локальная модель не поддерживает контекст диалога."

    def get_embedding(self, text: str) -> List[float]:
        return []