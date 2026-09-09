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


def debug_missing_entities_session(llm, document_text: str, extracted_entities: dict):
    """
    Интерактивная сессия для тестирования и анализа пропущенных сущностей.
    Не заменяет валидатор, используется только для ручной отладки промпта.
    """
    print("\n" + "=" * 60)
    print("🛠️  РЕЖИМ ОТЛАДКИ ПРОМПТА И ПОИСКА ПРОПУСКОВ (GIGACHAT)")
    print("Задайте вопросы модельке (например: 'Почему ты не нашел КПП 366601010?')")
    print("Введите 'next' или 'exit' для перехода к Шагу 3 (Валидатор).")
    print("=" * 60 + "\n")

    # Инициализируем историю диалога системным контекстом
    history = [
        {
            "role": "system",
            "content": "Ты — AI-ассистент. Ранее ты анализировал документ и извлекал из него сущности."
        },
        {
            "role": "user",
            "content": f"Вот текст документа, который ты анализировал:\n---\n{document_text[:8000]}\n---\n\nВот сущности, которые ты извлек:\n{extracted_entities}"
        },
        {
            "role": "assistant",
            "content": "Я ознакомился с документом и списком извлеченных сущностей. Готов ответить на твои вопросы по качеству извлечения."
        }
    ]

    while True:
        user_query = input("❓ [Debug Prompt] Ваш вопрос к GigaChat: ").strip()

        if user_query.lower() in ["next", "exit", "quit", "выход"]:
            print("👋 Завершение сессии отладки. Переход к Шагу 3...\n")
            break

        if not user_query:
            continue

        # Добавляем вопрос пользователя в историю
        history.append({"role": "user", "content": user_query})

        try:
            # Получаем ответ от LLM с учетом всего контекста
            bot_response = llm.chat_with_history(history)

            # Сохраняем ответ модели в историю для следующего уточняющего вопроса
            history.append({"role": "assistant", "content": bot_response})

            print(f"\n🤖 [GigaChat]: {bot_response}\n")
            print("-" * 60)
        except Exception as e:
            print(f"⚠️ Ошибка при запросе к GigaChat: {e}\n")

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
        llm: LLMInterface = GigaChatLLM("eyJjdHkiOiJqd3QiLCJlbmMiOiJBMjU2Q0JDLUhTNTEyIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.azzKwJsitXy-cvQ9OnrWsnJyeplXq1It76tJIKuV75kY23uNF9FvMT8OzEutv-v1g2z0yTohz9D2wIKoya7HH094KwT7aONYoF0xFgL3V8DDEsxVSUD-Lx8Y4T_57uiAf2r82MPNFxsuQgaMRHwNuS6UW10GzI56Si5U6uOw6ypzRJs83555PUHvkVuDG9g3IgDGb9JH-yMPfsigwTlYFOEyglLshbdfEZbBzltHyDAVrsjG0jqzPDEPmDdImBGwN0Xgr7Qrp0LJFFomIu9tz8J2aFZfBvnSdpAx94YpzUw1bvwDzkeDJGiAExksZpTUXohtdUF9bGmoGRKtfxXr2w.tF2CmDSw_fqlygI0MgfCQQ.1AlaxaPCgt55PePFhd-cw6SDpecZrDCd9AyfG_rfQkqhV3mm_kmPFZoyWl2FXNoFg6H8Ey062V7tdn3qNHV0izAXQA9ePronlUBpDy2bFC1nOJHJp36xt8R-yQ_g4V36hg9qyAT5_YScwgZ_nPDzdhE0cY7vsj4Nw5RyXvChRl2bzJEul2GJ5LyUqGeC09P-Pyehxkt3Xm95LcDUDgf29fPAZfuiRjX0unLPHE3KW97g6ldeiA_kOu_VQkwu9FoJ7HSe-PT002-CWye3WkwByvFvodPHRcS-Rbsp9Gd0gi_9nssliXEv4edA45WA6i2rjoReXYdKIJ1FweBF6lw0qqD1cl4x5b-zmMLnLoNpa_l62bk8hEOT9CFVKwmzjwVQWmYUcGWbH-KKYt5nPtkI4o8U31SSr6CzZ5ioK2cI79CreuChxtwgh6Cf75Qsl9hmQ_nQPgRVr6ubaMmaE5RsDy6MfdoPiDGYFQUnHsFRK9PDVMFHQVciZ0GwDpw1_OfciCOi8coreOEw0MO9E1OAD4P5gonrIfi6T70zN_mvwhxT5Q1DqKFjhwsXzBiNC_jRjOnlP3sS12h655bH0HWME3MfPfbCeiOFlb69iZgdAbCnQU73P-koK6UvPVRIGX8-jlNKEIESz23EKaP23oE1bI2khnYrcyfbDPsNBhn6I_w-blrfp4orCnmUoVJqS59blsASdFICwpfuCASuqxK2_8Jrz91j1YCdMUmzCz-Jzzw.zHvxrL6KqwQ1VqyFMFv_5HQuRInkmwKvVFVLWIw7C1Y")
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

    debug_missing_entities_session(
        llm=llm,
        document_text=parsed_doc.full_text,
        extracted_entities=initial_replacements
    )

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