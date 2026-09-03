import pypdf
from typing import List, Dict, Any, Optional
from interfaces import ParserInterface, ParsedDocument


class PdfParser(ParserInterface):
    def parse(self, file_path: str) -> ParsedDocument:
        reader = pypdf.PdfReader(file_path)
        full_text = ""
        pages_text = {}
        all_tables = []

        for i, page in enumerate(reader.pages):
            page_num = i + 1
            page_text = page.extract_text()
            pages_text[f"Page_{page_num}"] = page_text
            full_text += f"\n--- Страница {page_num} ---\n{page_text}\n"

            # Извлечение таблиц с текущей страницы
            tables_on_page = self._extract_tables_from_page(page, page_num)
            print(tables_on_page)
            if tables_on_page:
                all_tables.extend(tables_on_page)
        print(all_tables)

        return ParsedDocument(
            filename=file_path.split("/")[-1],
            file_type="pdf",
            full_text=full_text,
            pages_or_sheets=pages_text,
            tables=all_tables if all_tables else None,
            metadata={
                "page_count": len(reader.pages),
                "is_encrypted": reader.is_encrypted
            }
        )

    def _extract_tables_from_page(self, page, page_num: int) -> List[Dict[str, Any]]:
        tables = []

        try:
            # Попытка извлечь таблицы с помощью pypdf
            for table in page.find_tables():
                table_data = []
                headers = []

                rows = list(table.rows)

                if not rows:
                    continue

                # Определяем заголовки (первая строка)
                header_row = rows[0]
                headers = [cell.get_text().strip() for cell in header_row.cells]

                # Если заголовки пустые или все одинаковые, используем нумерацию
                if not headers or all(h == "" for h in headers):
                    headers = [f"Column_{j + 1}" for j in range(len(header_row.cells))]

                # Извлекаем данные со 2-й строки (если есть)
                for row in rows[1:]:
                    row_data = []
                    for j, cell in enumerate(row.cells):
                        cell_text = cell.get_text().strip()
                        # Попытка преобразовать в число, если возможно
                        try:
                            if cell_text.replace('.', '', 1).replace('-', '', 1).isdigit():
                                cell_text = float(cell_text)
                        except (ValueError, TypeError):
                            pass
                        row_data.append(cell_text)

                    # Дополняем строку, если она короче заголовков
                    while len(row_data) < len(headers):
                        row_data.append("")

                    table_data.append(row_data)

                # Если есть данные, создаем словарь
                if table_data:
                    table_dict = {
                        "page": page_num,
                        "headers": headers,
                        "data": table_data
                    }
                    tables.append(table_dict)

        except AttributeError:
            print("qwerty")
            pass
        except Exception as e:
            # Логирование ошибки при извлечении таблиц
            print(f"Error extracting tables from page {page_num}: {e}")

        return tables