import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from interfaces import LLMInterface, MaskedEntity, ParsedDocument

logger = logging.getLogger(__name__)

try:
    from gigachat import GigaChat
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False


class ExtractionResult(BaseModel):
    entities: List[Dict[str, Any]] = Field(
        description="Список найденных конфиденциальных сущностей"
    )


# ---------------------------------------------------------------------------
# Утилиты для очистки значений от префиксов-меток
# ---------------------------------------------------------------------------

# Только ОДНОЗНАЧНЫЕ префиксы-метки. Не включаем "Директора", "Руководителя",
# "Поставщик", "Покупатель" и т.п. — они могут быть частью значения.
_PREFIX_MARKERS = (
    "ИНН", "КПП", "ОГРН", "ОГРНИП", "БИК",
    "Адрес", "Юр. адрес", "Юр.адрес", "Юридический адрес",
    "Факт. адрес", "Факт.адрес", "Фактический адрес", "Почтовый адрес",
    "Тел.", "Телефон", "Факс",
    "E-mail", "Email", "Эл. почта", "Электронная почта",
)

_PREFIX_RE = re.compile(
    r'^(?:' + '|'.join(re.escape(p) for p in _PREFIX_MARKERS) + r')\s*[:\-—]?\s+',
    re.IGNORECASE,
)


def _strip_value_prefix(orig_text: str) -> str:
    """Отрезает ведущий маркер-префикс (один раз).

    'ИНН: 3666123456'         -> '3666123456'
    'E-mail: sales@mail.ru'   -> 'sales@mail.ru'
    'Адрес: г. Москва, ...'   -> 'г. Москва, ...'
    """
    value = (orig_text or "").strip()
    new_value = _PREFIX_RE.sub('', value).strip()
    return new_value if new_value else value


# ---------------------------------------------------------------------------
# Поиск вхождений (union exact + fuzzy)
# ---------------------------------------------------------------------------

def find_occurrences(needle: str, haystack: str) -> List[re.Match]:
    """Ищет ВСЕ вхождения needle, объединяя exact и fuzzy варианты."""
    if not needle or not haystack:
        return []

    seen_spans: set = set()
    result: List[re.Match] = []

    def _add(matches) -> None:
        for m in matches:
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            result.append(m)

    # 1. Точный поиск
    _add(re.finditer(re.escape(needle), haystack))

    # 2. Гибкий поиск по пробелам / переносам
    tokens = [re.escape(t) for t in needle.split() if t]
    if len(tokens) > 1:
        flexible = re.compile(r'\s+'.join(tokens), re.IGNORECASE)
        _add(flexible.finditer(haystack))

    result.sort(key=lambda m: m.start())
    return result


# ---------------------------------------------------------------------------
# Устойчивый парсер JSON от LLM (4 уровня)
# ---------------------------------------------------------------------------

def _extract_json_object(raw: str) -> Optional[str]:
    """Достаёт внешний {...} из ответа, игнорируя Markdown-обёртки.

    Берёт первый '{' и последний '}' — это надёжнее жадного `\\{.*\\}`,
    который может захватить лишний текст и сломаться на вложенных скобках.
    """
    if not raw:
        return None

    text = raw.strip()

    # Снять ```json ... ```
    text = re.sub(r'^```(?:json|JSON)?\s*', '', text)
    text = re.sub(r'```\s*$', '', text)

    first = text.find('{')
    last = text.rfind('}')
    if first == -1 or last == -1 or last <= first:
        return None

    return text[first:last + 1]


def _repair_json(text: str) -> str:
    """Чинит типичные дефекты JSON от LLM."""
    # 1. Trailing commas перед ] и }
    text = re.sub(r',\s*([\]}])', r'\1', text)

    # 2. Управляющие символы (кроме \n, \t, \r, которые допустимы в JSON)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    return text


def _balanced_json_objects(text: str) -> List[str]:
    """Находит все сбалансированные {...} с учётом строк.

    Используется как промежуточный уровень: если весь JSON битый, но
    отдельные объекты внутри entities[] целые — их можно распарсить
    по одному.
    """
    objects: List[str] = []
    depth = 0
    in_string = False
    escape = False
    start = -1

    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                objects.append(text[start:i + 1])
                start = -1

    return objects


def _extract_entities_loose(text: str) -> List[Dict[str, Any]]:
    """Fallback: вытаскиваем сущности из битого JSON регуляркой.

    Работает даже если структура верхнего уровня сломана, а внутри строк
    есть незаэкранированные кавычки. Ключевой момент — нежадный захват
    `original_text` до `","entity_type"`.
    """
    entity_re = re.compile(
        r'"original_text"\s*:\s*"'
        r'(?P<orig>(?:[^"\\]|\\.)*?)'
        r'"\s*,\s*'
        r'"entity_type"\s*:\s*"'
        r'(?P<etype>[^"]*)'
        r'"'
        r'(?:\s*,\s*"confidence"\s*:\s*(?P<conf>[0-9.]+))?',
        re.DOTALL,
    )

    results: List[Dict[str, Any]] = []
    for m in entity_re.finditer(text):
        orig = m.group("orig").replace('\\"', '"').strip()
        etype = m.group("etype").strip()
        if not orig:
            continue
        item: Dict[str, Any] = {
            "original_text": orig,
            "entity_type": etype,
        }
        if m.group("conf"):
            try:
                item["confidence"] = float(m.group("conf"))
            except ValueError:
                pass
        results.append(item)
    return results


def _parse_json_from_raw(raw: str) -> Optional[dict]:
    """Многоуровневый парсер ответа LLM.

    Уровень 1: чистый JSON как есть.
    Уровень 2: с починкой trailing comma / управляющих символов.
    Уровень 3: через баланс скобок — ищем целый верхний объект.
    Уровень 4: regex-fallback по полям original_text / entity_type.
    """
    if not raw:
        return None

    candidate = _extract_json_object(raw)
    if not candidate:
        logger.warning("В ответе LLM не найден JSON-объект")
        return None

    # --- Уровень 1: чистый JSON
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed (level 1): %s", exc)

    # --- Уровень 2: с починкой trailing comma / управляющих символов
    repaired = _repair_json(candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed (level 2 after repair): %s", exc)

    # --- Уровень 3: баланс скобок — ищем целые {...} внутри
    for obj_str in _balanced_json_objects(repaired):
        try:
            data = json.loads(obj_str)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "entities" in data:
            logger.info("JSON восстановлен через balance-скан.")
            return data

    # --- Уровень 4: regex-fallback — вытаскиваем сущности регуляркой
    entities = _extract_entities_loose(candidate)
    if entities:
        logger.warning(
            "JSON не удалось восстановить полностью, "
            "использован regex-fallback (%d сущностей).",
            len(entities),
        )
        return {"entities": entities}

    logger.error(
        "JSON не поддался восстановлению. Ответ (первые 500 символов):\n%s",
        raw[:500],
    )
    return None


# ---------------------------------------------------------------------------
# GigaChatLLM
# ---------------------------------------------------------------------------

class GigaChatLLM(LLMInterface):

    def __init__(self, credentials: Optional[str] = None, model_name: str = "GigaChat"):
        if not GIGACHAT_AVAILABLE:
            raise ImportError("Пакет 'gigachat' не установлен. Установите через: pip install gigachat")

        self.credentials = credentials or os.getenv("GIGACHAT_CREDENTIALS")
        if not self.credentials:
            raise ValueError(
                "Не указаны credentials для GigaChat. Передайте параметр credentials "
                "или установите переменную окружения GIGACHAT_CREDENTIALS."
            )

        self.model_name = model_name
        self.client = GigaChat(
            credentials=self.credentials,
            base_url="https://gigachat.devices.sberbank.ru/api/v1",
            verify_ssl_certs=False,
            model=self.model_name,
        )

    # ------------------------------------------------------------------ LLM API

    def generate(self, prompt: str, **kwargs) -> str:
        payload = {"messages": [{"role": "user", "content": prompt}]}
        response = self.client.chat(payload)
        return response.choices[0].message.content

    def chat_with_history(self, messages: list) -> str:
        payload = {"model": self.model_name, "messages": messages}
        response = self.client.chat(payload)
        return response.choices[0].message.content

    def get_embedding(self, text: str) -> List[float]:
        response = self.client.embeddings(texts=[text])
        return response.data[0].embedding

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _clean_text_for_llm(text: str) -> str:
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _split_into_chunks(text: str, size: int = 6000, overlap: int = 400) -> List[str]:
        if not text:
            return []
        if len(text) <= size:
            return [text]
        chunks: List[str] = []
        step = max(1, size - overlap)
        for i in range(0, len(text), step):
            chunks.append(text[i:i + size])
        return chunks

    def _build_chunks(self, parsed_doc: ParsedDocument) -> List[str]:
        """Разбивает документ на чанки. Приоритет — по страницам/листам."""
        pages = parsed_doc.pages_or_sheets or {}
        if len(pages) > 1:
            return [
                f"[{name}]\n{text}"
                for name, text in pages.items()
                if text and text.strip()
            ]
        return self._split_into_chunks(parsed_doc.full_text)

    # ------------------------------------------------------------------ prompt

    def _build_extraction_prompt(self, text_to_analyze: str, target_types: List[str]) -> str:
        return f"""РОЛЬ: NER-модуль для извлечения конфиденциальных сущностей.

ЗАДАЧА: найди все сущности типов {target_types} в тексте.

КРИТИЧНО ПРО ЭКРАНИРОВАНИЕ В JSON:
Внутри строк original_text любые двойные кавычки (") ОБЯЗАНЫ быть
экранированы как \\" — это требование JSON. Без этого ответ невалиден.

Правильно:   {{"original_text": "ООО \\"Вектор\\"", "entity_type": "PARTY"}}
Неправильно: {{"original_text": "ООО "Вектор"", "entity_type": "PARTY"}}

Если сомневаешься — используй КАВЫЧКИ-ЁЛОЧКИ « » внутри значения,
их экранировать не надо: {{"original_text": "ООО «Вектор»", ...}}

ПРАВИЛА ПОЛЯ original_text:
1. Возвращай ТОЛЬКО само значение, без слов-меток вроде "ИНН:", "КПП:", "E-mail:", "Тел.", "в лице", "Адрес:".
   Примеры: "3666123456", "sales@company.ru", "Соколов Д.А.", "ООО «Вектор»".
2. Сохраняй регистр, кавычки, падеж и пунктуацию БЕЗ изменений.
3. Извлекай ровно то, что есть в тексте, не расширяй контекстом.

ПРАВИЛА ПО ТИПАМ:
- INN: 10 или 12 цифр
- KPP: 9 цифр
- OGRN: 13 цифр, OGRNIP: 15 цифр
- FIO: полные ФИО и инициалы
- PHONE: любой формат
- EMAIL: только адрес
- ADDRESS: индекс + регион + город + улица + дом + помещение, целиком
- PARTY: Поставщик→"SUPPLIER", Покупатель→"BUYER", неясно→"PARTY"

ФОРМАТ ОТВЕТА: валидный JSON, начинается сразу с '{{', без Markdown:

{{
  "target_types_received": {target_types},
  "entities": [
    {{
      "original_text": "ЗНАЧЕНИЕ_БЕЗ_ПРЕФИКСА",
      "entity_type": "ТИП",
      "confidence": 0.95
    }}
  ]
}}

Текст документа:
---
{text_to_analyze}
---"""

    # ------------------------------------------------------------------ parsing

    def _parse_llm_json_response(
        self, raw_response: str, full_text: str
    ) -> List[MaskedEntity]:
        data = _parse_json_from_raw(raw_response)
        if not data:
            return []

        received_types = data.get("target_types_received", [])
        if received_types:
            logger.info("GigaChat сообщил типы для поиска: %s", received_types)

        entities_list = data.get("entities", []) or []
        result: List[MaskedEntity] = []
        seen_spans: set = set()

        for item in entities_list:
            if not isinstance(item, dict):
                continue

            orig_text_raw = (item.get("original_text") or "").strip()
            if not orig_text_raw:
                continue

            entity_type = item.get("entity_type", "UNKNOWN")
            try:
                confidence = float(item.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0

            # Собираем ВСЕ формы для поиска:
            # 1. original_text как есть
            # 2. original_text без префикса
            # 3. Все варианты из поля variants (и с префиксом, и без)
            candidates: List[str] = [orig_text_raw]

            cleaned_orig = _strip_value_prefix(orig_text_raw)
            if cleaned_orig and cleaned_orig != orig_text_raw:
                candidates.append(cleaned_orig)

            raw_variants = item.get("variants") or []
            if isinstance(raw_variants, list):
                for v in raw_variants:
                    v_str = (v or "").strip()
                    if not v_str:
                        continue
                    candidates.append(v_str)
                    v_clean = _strip_value_prefix(v_str)
                    if v_clean and v_clean != v_str:
                        candidates.append(v_clean)

            # Дедуплицируем кандидатов, сохраняя порядок
            unique_candidates = list(dict.fromkeys(candidates))

            for candidate in unique_candidates:
                if not candidate or len(candidate) < 2:
                    continue
                for match in find_occurrences(candidate, full_text):
                    span = (match.start(), match.end())
                    if span in seen_spans:
                        continue
                    seen_spans.add(span)
                    result.append(MaskedEntity(
                        original_text=full_text[match.start():match.end()],
                        masked_text=f"[{entity_type}_REDACTED]",
                        start_pos=match.start(),
                        end_pos=match.end(),
                        entity_type=entity_type,
                        confidence=confidence,
                    ))

        result.sort(key=lambda e: (e.start_pos, e.end_pos))
        return result

    # ------------------------------------------------------------------ public

    def extract_entities(
        self, parsed_doc: ParsedDocument, target_types: List[str]
    ) -> List[MaskedEntity]:
        if not parsed_doc or not parsed_doc.full_text or not parsed_doc.full_text.strip():
            return []

        chunks = self._build_chunks(parsed_doc)
        if not chunks:
            return []

        all_entities: List[MaskedEntity] = []
        seen: set = set()

        for idx, chunk in enumerate(chunks, 1):
            clean = self._clean_text_for_llm(chunk)
            if len(clean) < 20:
                continue

            logger.info("LLM-запрос %d/%d (%d символов)", idx, len(chunks), len(clean))
            prompt = self._build_extraction_prompt(clean, target_types)

            try:
                raw = self.generate(prompt)
            except Exception as exc:
                logger.warning("Ошибка LLM на чанке %d: %s", idx, exc)
                continue

            chunk_entities = self._parse_llm_json_response(raw, parsed_doc.full_text)

            for ent in chunk_entities:
                key = (ent.start_pos, ent.end_pos)
                if key in seen:
                    continue
                seen.add(key)
                all_entities.append(ent)

        logger.info("Итого уникальных сущностей: %d", len(all_entities))
        return all_entities


# ---------------------------------------------------------------------------
# LocalOllamaLLM (заглушка)
# ---------------------------------------------------------------------------

class LocalOllamaLLM(LLMInterface):
    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def generate(self, prompt: str, **kwargs) -> str:
        return '{"entities": []}'

    def chat_with_history(self, messages: list) -> str:
        return "Локальная модель не поддерживает контекст диалога."

    def get_embedding(self, text: str) -> List[float]:
        return []

    def extract_entities(
        self, parsed_doc: ParsedDocument, target_types: List[str]
    ) -> List[MaskedEntity]:
        logger.warning("Используется фоллбэк LocalOllamaLLM: сущности не извлечены.")
        return []