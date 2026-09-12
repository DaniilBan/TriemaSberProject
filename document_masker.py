import fitz  # PyMuPDF
import docx
from docx.enum.text import WD_COLOR_INDEX
import openpyxl
from openpyxl.styles import PatternFill
from typing import Dict
import re


def _get_sorted_replacements(replacements: Dict[str, str]) -> Dict[str, str]:
    return dict(
        sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True
        )
    )


def _build_flexible_regex(target_text: str) -> re.Pattern:

    escaped = re.escape(target_text.strip())

    pattern_str = re.sub(r'\\?\s+', r'\\s+', escaped)
    return re.compile(pattern_str, re.IGNORECASE)


def mask_docx(input_path: str, output_path: str, replacements: Dict[str, str]):
    doc = docx.Document(input_path)
    sorted_replacements = _get_sorted_replacements(replacements)

    def process_paragraph(p):
        if not p.text or not p.text.strip():
            return

        for target, mask in sorted_replacements.items():
            if not target or not target.strip():
                continue

            pattern = _build_flexible_regex(target)


            if pattern.search(p.text):

                replaced_in_runs = False
                for run in p.runs:
                    if pattern.search(run.text):
                        run.text = pattern.sub(mask, run.text)
                        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                        replaced_in_runs = True

                if not replaced_in_runs and pattern.search(p.text):
                    new_text = pattern.sub(mask, p.text)
                    p.text = new_text
                    for run in p.runs:
                        run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    for p in doc.paragraphs:
        process_paragraph(p)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    process_paragraph(p)

    for section in doc.sections:
        for p in section.header.paragraphs:
            process_paragraph(p)
        for p in section.footer.paragraphs:
            process_paragraph(p)

    doc.save(output_path)


def mask_xlsx(input_path: str, output_path: str, replacements: Dict[str, str]):
    wb = openpyxl.load_workbook(input_path)
    yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    sorted_replacements = _get_sorted_replacements(replacements)

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    cell_text = str(cell.value)
                    is_modified = False

                    for target, mask in sorted_replacements.items():
                        if not target or not target.strip():
                            continue

                        pattern = _build_flexible_regex(target)
                        if pattern.search(cell_text):
                            cell_text = pattern.sub(mask, cell_text)
                            is_modified = True

                    if is_modified:
                        cell.value = cell_text
                        cell.fill = yellow_fill

    wb.save(output_path)


def mask_pdf(input_path: str, output_path: str, replacements: Dict[str, str]):
    doc = fitz.open(input_path)
    sorted_replacements = _get_sorted_replacements(replacements)

    for page in doc:
        for target, mask in sorted_replacements.items():
            if not target or not target.strip():
                continue

            search_variants = [
                target.strip(),
                re.sub(r'\s+', ' ', target.strip()),
                re.sub(r'\s+', '\xa0', target.strip())
            ]

            for var in search_variants:
                text_instances = page.search_for(var)
                for inst in text_instances:
                    page.add_redact_annot(
                        inst,
                        text=mask,
                        fill=(1, 1, 0),
                        text_color=(0, 0, 0),
                        fontsize=8
                    )
        page.apply_redactions()

    doc.save(output_path)