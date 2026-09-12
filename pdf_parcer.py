import os
from typing import List, Dict, Any, Optional
import pdfplumber
import pymupdf
from pydantic import BaseModel

try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from interfaces import ParserInterface, ParsedDocument


class PdfParser(ParserInterface):

    def parse(self, file_path: str) -> ParsedDocument:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл {file_path} не найден!")

        full_text_list: List[str] = []
        pages_dict: Dict[str, str] = {}
        extracted_tables: List[Dict[str, Any]] = []
        used_ocr = False

        with pdfplumber.open(file_path) as pdf:
            total_pages = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                page_text = page.extract_text() or ""

                if not page_text.strip():
                    ocr_text = self._apply_ocr_to_page(file_path, page_num)
                    if ocr_text:
                        page_text = ocr_text
                        used_ocr = True

                pages_dict[f"Page_{page_num}"] = page_text
                full_text_list.append(f"--- Страница {page_num} ---\n{page_text}")

                tables = page.extract_tables()
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
                "tables_count": len(extracted_tables)
            }
        )

    def _apply_ocr_to_page(self, file_path: str, page_num: int) -> str:
        if not OCR_AVAILABLE:
            print("⚠️ OCR библиотеки не установлены (pdf2image, pytesseract). Пропуск скана.")
            return ""

        try:
            images = convert_from_path(
                file_path,
                first_page=page_num,
                last_page=page_num
            )
            if images:
                text = pytesseract.image_to_string(images[0], lang='rus+eng')
                return text.strip()
        except Exception as e:
            print(f"❌ Ошибка OCR на странице {page_num}: {e}")

        return ""


if __name__ == "__main__":
    test_pdf = "sample-table.pdf"
    if os.path.exists(test_pdf):
        parser = PdfParser()
        parsed_doc = parser.parse(test_pdf)

        print("=== РЕЗУЛЬТАТ ПАРСИНГА PDF ===")
        print(f"Имя файла: {parsed_doc.filename}")
        print(f"Страниц: {parsed_doc.metadata.get('page_count')}")
        print(f"Использовался OCR: {parsed_doc.metadata.get('used_ocr')}")
        print(f"Найдено таблиц: {parsed_doc.metadata.get('tables_count')}")
        print("\nФрагмент текста:\n")
        print(parsed_doc.full_text[:300])