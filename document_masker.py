import fitz  # PyMuPDF
import docx
from docx.shared import RGBColor
from docx.enum.text import WD_COLOR_INDEX
import openpyxl
from openpyxl.styles import PatternFill
from typing import Dict, List


def mask_docx(input_path: str, output_path: str, replacements: Dict[str, str]):
    """
    Заменяет конфиденциальные данные в .docx файле и выделяет их желтым цветом.
    replacements: словарь вида {"Иванов И.И.": "[МАСКА: ФИО]", "79991112233": "[МАСКА: ТЕЛЕФОН]"}
    """
    doc = docx.Document(input_path)

    def process_paragraphs(paragraphs):
        for p in paragraphs:
            for text_to_find, mask_text in replacements.items():
                if text_to_find in p.text:
                    # Посегментная замена внутри runs для сохранения оригинального стиля
                    for run in p.runs:
                        if text_to_find in run.text:
                            run.text = run.text.replace(text_to_find, mask_text)
                            # Визуальная подсветка (желтый маркер)
                            run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    # Обработка основного текста
    process_paragraphs(doc.paragraphs)

    # Обработка текста внутри таблиц
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                process_paragraphs(cell.paragraphs)

    doc.save(output_path)


def mask_xlsx(input_path: str, output_path: str, replacements: Dict[str, str]):
    """
    Заменяет значения в ячейках .xlsx и подсвечивает ячейку желтой заливкой.
    """
    wb = openpyxl.load_workbook(input_path)
    yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    cell_text = str(cell.value)
                    is_modified = False
                    for text_to_find, mask_text in replacements.items():
                        if text_to_find in cell_text:
                            cell_text = cell_text.replace(text_to_find, mask_text)
                            is_modified = True

                    if is_modified:
                        cell.value = cell_text
                        cell.fill = yellow_fill

    wb.save(output_path)


def mask_pdf(input_path: str, output_path: str, replacements: Dict[str, str]):
    """
    Находит текст в PDF, накладывает аннотацию редакции (redaction/mask)
    с заливкой цветом и новым текстом маркера.
    """
    doc = fitz.open(input_path)

    for page in doc:
        for text_to_find, mask_text in replacements.items():
            # Поиск координат (bounding box) всех совпадений текста
            text_instances = page.search_for(text_to_find)

            for inst in text_instances:
                # Добавление области под замену (Redaction annotation)
                page.add_redact_annot(
                    inst,
                    text=mask_text,
                    fill=(1, 1, 0),  # RGB: Желтый фон заднего плана (1, 1, 0)
                    text_color=(0, 0, 0),  # RGB: Черный цвет текста
                    fontsize=9
                )
        # Применение всех маскировок на странице (физическое удаление старого текста)
        page.apply_redactions()

    doc.save(output_path)