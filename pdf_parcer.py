import logging
import os
import re
from typing import Any, Dict, List

import pdfplumber
from pydantic import BaseModel

try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from interfaces import ParserInterface, ParsedDocument

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Нормализация PDF-текста
# ---------------------------------------------------------------------------

_ZERO_WIDTH_CHARS = '\u200b\u200c\u200d\ufeff\u00ad'
_ZERO_WIDTH_MAP = dict.fromkeys(map(ord, _ZERO_WIDTH_CHARS), None)

_TYPO_REPLACEMENTS = {
    '«': '"', '»': '"', '“': '"', '”': '"', '„': '"', '‟': '"',
    '–': '-', '—': '-', '−': '-',
    '…': '...',
    '№': 'N',
    '\u00a0': ' ', '\u2007': ' ', '\u2009': ' ', '\u202f': ' ',
    '\u2002': ' ', '\u2003': ' ', '\u2004': ' ', '\u2005': ' ',
    '\u2006': ' ', '\u2008': ' ', '\u200a': ' ',
}

_LETTER_SPACING_MIN_PARTS = 5
_LETTER_SPACING_SINGLE_RATIO = 0.6


def _fix_letter_spacing(line: str) -> str:
    """'И Н Н 3 6 6 6 1 2 3 4 5 6' -> 'ИНН3666123456'."""
    parts = line.split(' ')
    if len(parts) < _LETTER_SPACING_MIN_PARTS:
        return line
    single_count = sum(1 for p in parts if len(p) == 1)
    if single_count / len(parts) < _LETTER_SPACING_SINGLE_RATIO:
        return line
    return ''.join(parts)


def normalize_pdf_text(text: str) -> str:
    """Приводит PDF-текст к виду, пригодному для LLM и regex.

    Устраняет типичные артефакты pdfplumber:
    - невидимые и специальные пробелы -> обычный пробел
    - типографские кавычки/тире -> ASCII
    - перенос слова через дефис в конце строки
    - разрыв фразы по строкам (склеивает строки без завершающего знака)
    - letter-spacing (побуквенный разнос)
    - множественные пробелы, пробелы перед пунктуацией
    """
    if not text:
        return text

    text = text.translate(_ZERO_WIDTH_MAP)

    for src, dst in _TYPO_REPLACEMENTS.items():
        text = text.replace(src, dst)

    # Перенос слова через дефис на границе строки: "теле-\nфон" -> "телефон"
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)

    # Склеиваем строки без завершающего знака: собирает "ИНН\n3666123456"
    lines = text.split('\n')
    merged: List[str] = []
    for ln in lines:
        ln = ln.rstrip()
        if not ln:
            merged.append('')
            continue
        if merged and merged[-1] and not re.search(r'[.!?:;]\s*$', merged[-1]):
            merged[-1] = merged[-1] + ' ' + ln
        else:
            merged.append(ln)
    text = '\n'.join(merged)

    # Letter-spacing
    text = '\n'.join(_fix_letter_spacing(ln) for ln in text.split('\n'))

    # Множественные пробелы и пробелы перед пунктуацией
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)

    return text


# ---------------------------------------------------------------------------
# Парсер
# ---------------------------------------------------------------------------

class PdfParser(ParserInterface):

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл {file_path} не найден!")

        full_text_list: List[str] = []
        pages_dict: Dict[str, str] = {}
        extracted_tables: List[Dict[str, Any]] = []
        used_ocr = False

        try:
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)

                for i, page in enumerate(pdf.pages):
                    page_num = i + 1
                    try:
                        page_text = page.extract_text() or ""
                    except Exception as exc:
                        logger.warning("pdfplumber не смог извлечь текст со стр. %d: %s", page_num, exc)
                        page_text = ""

                    if not page_text.strip():
                        ocr_text = self._apply_ocr_to_page(file_path, page_num)
                        if ocr_text:
                            page_text = ocr_text
                            used_ocr = True

                    page_text = normalize_pdf_text(page_text)

                    pages_dict[f"Page_{page_num}"] = page_text
                    full_text_list.append(f"--- Страница {page_num} ---\n{page_text}")

                    try:
                        tables = page.extract_tables() or []
                    except Exception as exc:
                        logger.warning("Не удалось извлечь таблицы со стр. %d: %s", page_num, exc)
                        tables = []

                    for table in tables:
                        if table:
                            cleaned_table = [
                                [cell.strip() if cell else "" for cell in row]
                                for row in table
                            ]
                            extracted_tables.append({
                                "page": page_num,
                                "data": cleaned_table
                            })
        except Exception as exc:
            logger.error("Не удалось открыть PDF '%s': %s", file_path, exc)
            raise

        full_text = "\n\n".join(full_text_list)

        return ParsedDocument(
            filename=os.path.basename(file_path),
            file_type="pdf",
            full_text=full_text,
            pages_or_sheets=pages_dict,
            tables=extracted_tables if extracted_tables else None,
            metadata={
                "page_count": total_pages,
                "used_ocr": used_ocr,
                "tables_count": len(extracted_tables),
            }
        )

    def _apply_ocr_to_page(self, file_path: str, page_num: int) -> str:
        if not OCR_AVAILABLE:
            logger.warning("OCR-библиотеки не установлены. Пропуск скана стр. %d.", page_num)
            return ""

        try:
            images = convert_from_path(file_path, first_page=page_num, last_page=page_num)
            if images:
                text = pytesseract.image_to_string(images[0], lang='rus+eng')
                return text.strip()
        except Exception as exc:
            logger.warning("Ошибка OCR на стр. %d: %s", page_num, exc)

        return ""