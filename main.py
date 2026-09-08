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
        llm: LLMInterface = GigaChatLLM("eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.h2xaypRg9zb-z3mcvNS0c6VamBSkWcNxk0dWzGRlJE8kjT9c70Z7PMryS-mmGAr34y1rviNKKD25d7tyfAlY49m4ic4LIXIwNsZxWy1zICXs8B45mlzr_9iA1jFJV73_isIoijinWaKfFxOs0jjNLf-DxarHmOwJjDS7FyEBfAX9leWZ-FkktO1iRuIahgSffcwa3QGus-FBcLl-gN2L3RZ5sBSaPH2cFTasEb7EIfLRp1Jihc13ykJSoWlFotZ-o9XRVRFI-DM6Pqf2RqxMoOkVtSHfFPOuR2m_235pbk5AJUNYMe-fvkzuS-N-qiz_m4L5qtzFF0vNNW6soYMo5A.cw6cqLFVsFjiD4VRjgA0ew.HVFe5nHLd4I1WgIR3g0fvqYxtfirrQBvCEXBIEvTxAHhpu9S0-2zcRjVAsjyExk_h4QEubpdBt9rkAH5VC2PHhiyCwR0fmdlrXDje3g4yveveiF7t45x4gZqOU2qKVLczIMj7z04YvzzEsyxxKfsHm_hV0k4rouUMbF911RgPuS5stHXA74C21_ljhWQ_U3WAT2Gw39LjYYh7SJKSzIEZCexrSZqnoxiSthCXBojWmiZF4HMDMFe-NJrGZqJWAVghJQ-EzVmu5vMld-XnyrEy37KvaXsM1-FOGvL4T2fsCkFOFsbiag4YOfs4STDB3KZB7IXkmHNhagSjZCGovfnA8MWlASulpQ2OL0F2fw3BztUylhVMrfO6u_Od4BYGDEGfKefITfV1OFo6m5wDpShelSJdGZUoS7hTPYo_dpYMJ2CYBi7o3vj8rY-dnGrtVYTpwrnAE8y53YRn0IpwdeHwZdcEdusCh3gUcZuWv_AE-0ucGZR6FzYgjTsHCNk8G2YyfM6cIkCKcZcikefJN79LFvUv0V4_jS06XxxFVnUUP61ylpZBhpE9qgSXrTrFLzZQ2nrL8cDtqvWZrbrggBTq-oSjSJWQSNMNToVHf6UF6lBhIbMcyxefM5619l4YU64xQnB2V4ksHPVG_qsFgUFjSInpSWXVajrjFd36hNYm54Vq1cPtAvT0upA55LSMMbpDnNEQnTcF5LF21S7TvoEDBlpbAa8i_bPSyvLuApXj58.Fg8p-4zmznTI62vrV4xpydsGkxQ8x2k6cT3GVKJ4hX4")
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