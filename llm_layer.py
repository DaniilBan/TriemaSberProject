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
{parsed_doc.full_text[:4000]} 
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


# --- 4. Проверка работы модуля ---
if __name__ == "__main__":
    # Тестовые данные
    mock_doc = ParsedDocument(
        filename="test_contract.docx",
        file_type="docx",
        full_text="Договор поставки. Поставщик: ООО 'Вектор', ИНН 7712345678. Заказчик: АО 'Триема'. Тел: +7 (999) 111-22-33",
        pages_or_sheets={"main": "..."},
        tables=None,
        metadata={}
    )

    print("=== ТЕСТИРОВАНИЕ ИИ-СЛОЯ ===")

    # Можно легко переключать модели в 1 строчку:
    # llm_service = LocalOllamaLLM()
    try:
        # Для запуска требуется установленный токен GigaChat
        llm_service = GigaChatLLM(access_token="eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.uyZ6rMAWX1Ho8wE2nV0G-MNzZpeDLEhTIwSdNpKN4y0C1zuD85dlDHSNDHSOzVP8pYu9weJsA4HXDoQt26ntssPP_oNeRJUJA8EYKBLBjXNFjpOReifZIfmKZ1xZoNUNb9DeAeE6hdGtt-FZ9wSuQmiu9GXvcvXLY9CSEv2tLKbQmklbegGLenUT-ZKLWRPNWXLRn_ReDBWwmvKYcutGLhWgjig_jl7feXukYFTUnQHMKov9WvRx90Edh3uN_kFUuHBEzcSURQUPO1Zyi31-bxOM0gFbeYk8YF2x3oJl0iDoSybYF8XlNNW8fR8kUQp5pt4ozO-eybCER5YhD3Zecg.9YQ8qLKTdhTNsadyk-liIQ.FyANVWfHRMga-HmSv90pExxlshW6Ley0MKROEZ9o1Gl-ATeaOBAZP0B0jujX6JM92G3jmKLLzUstZOYrJ_yD1xFB7fNZh_XgQjy0-o3ZSO6csLMVIwKBZVW4aSyAQBQS9qBdDeVEpx5JTr2ZJdboHPesZQzljyq5ntsu2J0vYx2bO_lCeKWvee0hNBQEEORKmsgINX4vMMoaDt05ggn67iy2ypUv2iL-X2HeFnUWfvoJtL35wUtB9Xp02VCS0INjZ64Yp_JxBSoDaZA3IitIi0-dGAgdktsYifGi80xeQWLDDqjHi0SpYnnsQBzTLuUhrdpsqoLLbLqeWqexinUv-r4WNcZp7oyIKpHH1Khu-BLjIUH3XsBVfty4Nla7aX0bu9iFoHwamCQ47P9HXqBlxxaaracIML1Dxn_523OG143KUnstbqeQpv8zKbYuSthN67-UinI6y8zyR1r1tXjZMkI83Q1yhKNG_kk1H1wZMl2YHDXYeHvDu2f1ey2qIju1xhIs475RxATq2FQtbsDN0QE3EsAarIxzLh_kMACMLG_Cw5xpOh2RjjfSG_qSji1znCUscej8IDEOBgyBqdgENhUOtNHnA5ulIZ99zfl5_nW77DvfBizkXQTk6ZCjcpTlhgs-RxpBjRbKDPY1XpsNIVIuN4SoNsJQxmUy-ucVu-hU5twzS9jLj5XPJ8eiLgCONqrELBfHtu6s1U4xImTRwpMDsoOzOWE7o2vmUpikt48.7kLPjY5FjqQOSOQJvkKXr4P7n3ak8fA-I6FbomGvc7w")
        results = llm_service.extract_entities(mock_doc, target_types=['INN', 'PHONE', 'PARTY'])

        for entity in results:
            print(
                f"Найдено: {entity.original_text} | Тип: {entity.entity_type} | Позиция: {entity.start_pos}:{entity.end_pos}")
    except Exception as e:
        print(f"Тестовый запуск без токена: {e}")