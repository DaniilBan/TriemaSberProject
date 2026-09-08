import os
import sys
from typing import Dict, List, Type

# 1. Импорт интерфейсов и структур данных
from interfaces import ParserInterface, ParsedDocument, MaskedEntity, LLMInterface

# 2. Импорт специализированных парсеров
from docx_parcer import DocxParser
from xlsx_parcer import XlsxParser
from pdf_parcer import PdfParser

# 3. Импорт ИИ-слоя
from llm_layer import GigaChatLLM, LocalOllamaLLM

# 4. Импорт логики валидации и маскирования
from interactive_validator import InteractiveValidator
from document_masker import mask_docx, mask_xlsx, mask_pdf


def get_parser(file_extension: str) -> ParserInterface:
    """
    Фабрика парсеров для выбора соответствующего класса по расширению файла.
    """
    parsers: Dict[str, Type[ParserInterface]] = {
        ".docx": DocxParser,
        ".xlsx": XlsxParser,
        ".pdf": PdfParser
    }
    parser_class = parsers.get(file_extension.lower())
    if not parser_class:
        raise ValueError(f"Неподдерживаемое расширение файла: {file_extension}")
    return parser_class()


def run_pipeline(file_path: str, output_path: str = None):
    """
    Главный управляющий пайплайн обработки документа.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Указанный файл не найден: '{file_path}'")

    file_ext = os.path.splitext(file_path)[1].lower()

    if not output_path:
        base, ext = os.path.splitext(file_path)
        output_path = f"{base}_masked{ext}"

    # -------------------------------------------------------------
    # ШАГ 1. Парсинг документа
    # -------------------------------------------------------------
    print("=" * 60)
    print(f"[1/4] Выполняется парсинг документа: {file_path}")
    parser = get_parser(file_ext)
    parsed_doc: ParsedDocument = parser.parse(file_path)
    print(f"-> Успешно прочитан файл: {parsed_doc.filename}")
    print(f"-> Длина извлеченного текста: {len(parsed_doc.full_text)} символов.")

    # -------------------------------------------------------------
    # ШАГ 2. Анализ документа с помощью LLM (Извлечение сущностей)
    # -------------------------------------------------------------
    print("\n[2/4] Запуск LLM для поиска конфиденциальных сущностей...")

    # Можно легко сменить реализацию на LocalOllamaLLM() при необходимости
    try:
        # При необходимости передайте access_token авторизации
        llm: LLMInterface = GigaChatLLM("eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.BisKW4tXIE5etGpRvw5pCbJP644oovbSHkyKb9cDKCl9KOvcHBCvNcXGixg-ZbjTizdzBQue2lMh6TBFkbmiIa-xEgH4W9dZCAVnb-jxTa77c3Ryf8ZKyPCLNbHFm0zJBUk2ApniOEF7P6qL6gBInkU_G4xteNMRAgXrd8ZgKceckfxVUIoAARSllJksVqTgg8cmlM0IJgEx8reuSr564oAVNECZU53MUcnS2rde-xN8Hoe91UNXV2tdB6CGkzEkbdnWTTAiXANDdRnpDx2Ua3nJuTkt1azoMLrjgcGkpvrFqBlfDFnr6yYI-nXpeg7JyxRJVPBSAW-Xg8ROwCcrLw.lNOfV8mZtBrl0ww7HxOTHA.UVgSIBSbgQ9KB0o64tIkSU-gJ27cWExUcTRt8QwdODn_ykIEVhp2h7xMebZKf9GBcSw6rDwdctQqmS1TRnq3XHqALjNREP3_Zn0lS5qTTaYYe8Zc4iePRwCFq25nsMu74_dWzdfSkdtKD7hR51zw2x1A-tVOz5u3hNm6eTaDTm1HUukLmES8gtZqdjlJthmnd9sq95kAyQEwYZCLIvN828CfdY54ddX164mAb4JlvuIr_8y_A1wQIsTimUpQuAFokpVFFpW29m2n5T1Ckn9mkvITofwzuibc2kOutKRJYbHSH658o6xAed5GPCft7VuzP71WFg2Zx_jqSM5cjqdpGdep89ROCkdJxp_tqmZNt6erVn74lI-ykDVi698pqcgy257Txv7_P88yaM_CSS7bU9Tx_wRbc2BGn31AAaHPApmzV02cmbI1rMWgeRCVtXZe6BVZ7y3FeYPZPH6kZzPXYTcFdd9Mux7g27I3g7cRyuNkbSLCR2u5LAzOX5K16kufDBMhOOEnnIWAJJLT5j27HG76wZ6R-widax9_Os8f3m6KgOWvWhGW0MXxwR1UyKEggYKlsBhrqkgfyMqlGZSqGBQ1Wg6WcX2g9XSFSfJv4rNhWJF8tJMQ3YpxZWAsX4qvKA9tEJU63Hj5k-uh2KzymY4vfNnCSwtSEN4qHom2l87vO-uMnj5brOw5QgeuI74iZ3wjk6DWJHjVEEz-Il-hNdnaTPQVMTBXalawyy07hmA.yE7U9L7Y3F7-BqgQW_rDPBPCmgQhr-EqL20LoSxMfS0")
    except Exception as e:
        print(f"⚠️ Ошибка инициализации GigaChatLLM ({e}). Использование фоллбэка.")
        llm: LLMInterface = LocalOllamaLLM()

    # Целевые типы данных для извлечения (в соответствии с ТЗ)
    target_types = ['INN', 'PHONE', 'PARTY', 'EMAIL', 'PASSPORT', 'ADDRESS', 'FIO', 'CONFIDENTIAL DATA']

    # Получение структурных объектов MaskedEntity от слоя LLM
    extracted_entities_list: List[MaskedEntity] = llm.extract_entities(parsed_doc, target_types)

    # Преобразование результатов извлечения в словарь replacements {"исходный_текст": "маска"}
    # для дальнейшей передачи в валидатор и маскировщик
    initial_replacements: Dict[str, str] = {
        entity.original_text: entity.masked_text
        for entity in extracted_entities_list
    }

    print(f"-> Найдено уникальных сущностей: {len(initial_replacements)}")
    for orig, mask in initial_replacements.items():
        print(f"   • {orig}  --->  {mask}")

    # -------------------------------------------------------------
    # ШАГ 3. Проверка полноты и интерактивный диалог (Валидатор)
    # -------------------------------------------------------------
    print("\n[3/4] Запуск модуля проверки полноты и интерактивной валидации...")
    validator = InteractiveValidator(llm_client=llm)

    # Валидатор опрашивает пользователя при наличии неопределенностей и достраивает словарь
    final_replacements: Dict[str, str] = validator.validate_and_clarify(
        document_text=parsed_doc.full_text,
        extracted_entities=initial_replacements
    )

    # -------------------------------------------------------------
    # ШАГ 4. Маскирование файла с сохранением форматирования и подсветкой
    # -------------------------------------------------------------
    print("\n[4/4] Запуск процесса физического маскирования и выделения цветным фоном...")

    if file_ext == ".docx":
        mask_docx(file_path, output_path, final_replacements)
    elif file_ext == ".xlsx":
        mask_xlsx(file_path, output_path, final_replacements)
    elif file_ext == ".pdf":
        mask_pdf(file_path, output_path, final_replacements)

    print("=" * 60)
    print(" ОБРАБОТКА УСПЕШНО ЗАВЕРШЕНА!")
    print(f"Итоговый замаскированный документ сохранен по пути:\n -> {os.path.abspath(output_path)}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_file_path = sys.argv[1]
    else:
        input_file_path = input("Введите путь к документу (.docx, .xlsx, .pdf): ").strip().strip('"')

    run_pipeline(input_file_path)