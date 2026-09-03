import os
from collections import defaultdict
from docx import Document
from docx2python import docx2python
from docx.text.paragraph import Paragraph
from docx.table import Table
from docx.oxml.ns import qn
from docx.text.run import Run
from docx.oxml.text.hyperlink import CT_Hyperlink
from lxml import etree
etree.register_namespace('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')


'''current_dir = os.path.dirname(os.path.abspath(__file__))
full_path = os.path.join(current_dir, 'demo.docx')
print("Файлы в папке скрипта:", os.listdir(current_dir))
print("Ищем файл по пути:", full_path)'''
document = Document("demo.docx")
content = docx2python("demo.docx")
document_timeline = []
'''test_footnotes_data = [
    [
        [ ['Внимание! Применяются особые тарифы обеспечения контракта.'] ],
        [ ['Размер НМЦК', 'Процент обеспечения'] ],
        [ ['До 20 млн руб.', '<a href="https://etp.ru">1% от НМЦК</a>'] ],
        [ ['Ссылка на правила: <a href="https://site.ru">Инструкция</a>'] ]
    ]
]'''


footnotes_map = defaultdict(str)
i = 1
for footnote in content.footnotes:
    is_table_open = False
    for blocs in footnote:
        for paragraph in blocs:
            if len(paragraph) > 1 and is_table_open == False:
                footnotes_map[i] += "\n[НАЧАЛО ТАБЛИЦЫ]\n"
                is_table_open = True
                footnotes_map[i] += " | ".join(paragraph)
            elif is_table_open == True and len(paragraph) == 1:
                footnotes_map[i] += "\n[КОНЕЦ ТАБЛИЦЫ]\n"
                footnotes_map[i] += "".join(paragraph) + " "
                is_table_open = False
            elif is_table_open == True and len(paragraph) > 1:
                footnotes_map[i] += "\n" +  " | ".join(paragraph)
            else:
                footnotes_map[i] += "".join(paragraph) + " "

    footnotes_map[i] = footnotes_map[i].strip()
    if is_table_open:
        footnotes_map[i] += "\n[КОНЕЦ ТАБЛИЦЫ]\n"
        is_table_open = False
    i += 1

endnotes_map = defaultdict(str)
i = 1
for endnote in content.endnotes:
    is_table_open = False
    for blocs in endnote:
        for paragraph in blocs:
            if len(paragraph) > 1 and is_table_open == False:
                endnotes_map[i] += "\n[НАЧАЛО ТАБЛИЦЫ]\n"
                is_table_open = True
                endnotes_map[i] += " | ".join(paragraph)
            elif is_table_open == True and len(paragraph) == 1:
                endnotes_map[i] += "\n[КОНЕЦ ТАБЛИЦЫ]\n"
                endnotes_map[i] += "".join(paragraph) + " "
                is_table_open = False
            elif is_table_open == True and len(paragraph) > 1:
                endnotes_map[i] += "\n" +  " | ".join(paragraph)
            else:
                endnotes_map[i] += "".join(paragraph) + " "

    endnotes_map[i] = endnotes_map[i].strip()
    if is_table_open:
        endnotes_map[i] += "\n[КОНЕЦ ТАБЛИЦЫ]\n"
        is_table_open = False
    i += 1


print("--- СЫРЫЕ ПОДСТРОЧНЫЕ СНОСКИ (footnotes) ---")
print(content.footnotes)
print("=== СОДЕРЖИМОЕ СЛОВАРЯ ПОДСТРОЧНЫХ СНОСОК (footnotes_map) ===")
for key, value in footnotes_map.items():
    print(f"ID {key}: {value}")

print("\n=== СОДЕРЖИМОЕ СЛОВАРЯ КОНЦЕВЫХ СНОСОК (endnotes_map) ===")
for key, value in endnotes_map.items():
    print(f"ID {key}: {value}")

print("\n--- СЫРЫЕ КОНЦЕВЫЕ СНОСКИ (endnotes) ---")
print(content.endnotes)



from docx.oxml.ns import qn

from docx.text.run import Run
from docx.text.hyperlink import Hyperlink
from docx.oxml.ns import qn

def extract_text_from_paragraph(paragraph, doc):
    text = ""

    # 1. Обрабатываем всё содержимое через iter_inner_content()
    for child in paragraph.iter_inner_content():
        if isinstance(child, Run):
            text += child.text
        elif isinstance(child, Hyperlink):
            visible_text = child.text
            r_id = child._element.get(qn('r:id'))
            url = doc.part.rels[r_id].target_ref if r_id in doc.part.rels else ""
            text += f'<a href="{url}">{visible_text}</a>'

    # 2. Ищем сноски через XML (iter_inner_content() их не выдаёт)
    w = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

    # Подстрочные сноски
    for ref in paragraph._element.findall('.//' + w + 'footnoteReference'):
        footnote_id = ref.get(qn('w:id'))
        if footnote_id and footnote_id.isdigit():
            footnote_text = footnotes_map.get(int(footnote_id), "Сноска не найдена")
            text += f" [СНОСКА: {footnote_text}] "

    # Концевые сноски
    for ref in paragraph._element.findall('.//' + w + 'endnoteReference'):
        endnote_id = ref.get(qn('w:id'))
        if endnote_id and endnote_id.isdigit():
            endnote_text = endnotes_map.get(int(endnote_id), "Сноска не найдена")
            text += f" [СНОСКА: {endnote_text}] "

    return text.replace('\n', ' ').strip()

for element in document.element.body:
    if element.tag.endswith('tbl'):
        table = Table(element, document)
        document_timeline.append("\n[НАЧАЛО ТАБЛИЦЫ]\n")
        for row in table.rows:
            row_string = ""
            for cell in row.cells:
                cell_text = ""
                for paragraph in cell.paragraphs:
                    cell_text += extract_text_from_paragraph(paragraph, document) + " "
                row_string += cell_text + " | "
            document_timeline.append(row_string.rstrip(" |"))
        document_timeline.append("\n[КОНЕЦ ТАБЛИЦЫ]\n")
    elif element.tag.endswith('paragraph') or element.tag.endswith('}p'):
        paragraph_text = Paragraph(element, document)
        cleaned_text = extract_text_from_paragraph(paragraph_text, document)
        document_timeline.append(cleaned_text)






# Печатаем заголовок для наглядности
print("=== РЕЗУЛЬТАТ ПАРСИНГА ДОКУМЕНТА ===\n")

# Перебираем хронологический массив строки за строкой
for index, line in enumerate(document_timeline, 1):
    if not line.strip():
        # Печатаем её маркер, чтобы вы видели: тут пустой абзац автора для красоты!
        print(f"[{index}] <ПУСТАЯ СТРОКА ДОКУМЕНТА>")
    # Выводим номер строки и её содержимое
    print(f"[{index}] {line}")


'''print("РЕЗУЛЬТАТ ТЕСТИРОВАНИЯ СНОСКИ №1:\n")
print(footnotes_map[1])'''
