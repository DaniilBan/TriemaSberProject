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

    def get_embedding(self, text: str) -> List[float]:
        """Получение эмбеддингов текста"""
        response = self.client.embeddings(texts=[text])
        return response.data[0].embedding

    def extract_entities(self, parsed_doc: ParsedDocument, target_types: List[str]) -> List[MaskedEntity]:
        """
        Специализированный метод для анализа ParsedDocument и поиска сущностей.

        :param parsed_doc: Объект распарсенного документа
        :param target_types: Список типы данных для удаления (напр. ['INN', 'PHONE', 'PARTY', 'EMAIL'])
        :return: Список найденных объектов MaskedEntity
        """
        clean_text = self._clean_text_for_llm(parsed_doc.full_text)
        text_to_analyze = clean_text[:12000]

        prompt = f"""
Ты — AI-ассистент по деидентификации и анонимизации документов.
Проанализируй текст документа и найди в нем все упоминания следующих типов данных: {target_types}.

Особые правила для типа 'PARTY' (Стороны договора):
- Определи, кто является Поставщиком/Исполнителем/Продавцом (присвой entity_type = 'SUPPLIER').
- Определи, кто является Покупателем/Заказчиком/Клиентом (присвой entity_type = 'BUYER').

Верни ответ СТРОГО в формате JSON без каких-либо вводных слов и пояснений. 
Структура JSON:
{{
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
        """Очистка и парсинг JSON-ответа от LLM в объекты MaskedEntity"""
        masked_entities = []
        try:
            # Вырезаем JSON из возможной Markdown-разметки (```json ... ```)
            json_match = re.search(r'\{.*\}', raw_response, re.DOTALL)
            if not json_match:
                return []

            data = json.loads(json_match.group(0))
            entities_list = data.get("entities", [])

            for item in entities_list:
                orig_text = item.get("original_text", "").strip()
                entity_type = item.get("entity_type", "UNKNOWN")
                confidence = float(item.get("confidence", 1.0))

                if not orig_text:
                    continue

                # Ищем точные позиционные индексы вхождений в исходном тексте
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

    def get_embedding(self, text: str) -> List[float]:
        return []