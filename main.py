import os
import sys
from typing import Dict, List, Type, Any

from dotenv import load_dotenv

# 1. Импорт интерфейсов и структур данных
from interfaces import ParserInterface, ParsedDocument, MaskedEntity, LLMInterface

# 2. Импорт специализированных парсеров
from docx_parcer import DocxParser
from xlsx_parcer import XlsxParser
from pdf_parcer import PdfParser

# 3. Импорт ИИ-слоя
from llm_layer import GigaChatLLM, LocalOllamaLLM

# 4. Импорт логики валидации, маскирования и отчётов
from interactive_validator import InteractiveValidator
from document_masker import mask_docx, mask_xlsx, mask_pdf
from report_generator import ReportGenerator

load_dotenv()


def debug_missing_entities_session(llm, document_text: str, extracted_entities: dict):
    print("\n" + "=" * 60)
    print("🛠️  РЕЖИМ ОТЛАДКИ ПРОМПТА И ПОИСКА ПРОПУСКОВ (GIGACHAT)")
    print("Введите 'next' или 'exit' для перехода к Валидатору.")
    print("=" * 60 + "\n")

    found_raw_entities = list(extracted_entities.keys())

    history = [
        {
            "role": "system",
            "content": (
                "Ты — AI-ассистент. Ранее ты анализировал СЫРОЙ текст документа и извлекал из него сущности. "
                "Отвечай на вопросы пользователя о том, почему некоторые конкретные сущности не попали в список."
            )
        },
        {
            "role": "user",
            "content": f"Вот ИСХОДНЫЙ текст документа:\n---\n{document_text[:15000]}\n---\n\nВот список извлеченных сущностей:\n{found_raw_entities}"
        },
        {
            "role": "assistant",
            "content": "Я ознакомился с текстом и списком извлеченных сущностей. Готов ответить на вопросы."
        }
    ]

    while True:
        user_query = input("❓ [Debug Prompt] Ваш вопрос к GigaChat: ").strip()

        if user_query.lower() in ["next", "exit", "quit", "выход"]:
            print("👋 Завершение сессии отладки...\n")
            break

        if not user_query:
            continue

        history.append({"role": "user", "content": user_query})

        try:
            bot_response = llm.chat_with_history(history)
            history.append({"role": "assistant", "content": bot_response})
            print(f"\n🤖 [GigaChat]: {bot_response}\n" + "-" * 60)
        except Exception as e:
            print(f"⚠️ Ошибка при запросе к GigaChat: {e}\n")


def get_parser(file_extension: str) -> ParserInterface:
    parsers: Dict[str, Type[ParserInterface]] = {
        ".docx": DocxParser,
        ".xlsx": XlsxParser,
        ".pdf": PdfParser
    }
    parser_class = parsers.get(file_extension.lower())
    if not parser_class:
        raise ValueError(f"Неподдерживаемое расширение файла: {file_extension}")
    return parser_class()


def run_pipeline(file_path: str, output_path: str = None, debug_mode: bool = False):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Указанный файл не найден: '{file_path}'")

    file_ext = os.path.splitext(file_path)[1].lower()

    if not output_path:
        base, ext = os.path.splitext(file_path)
        output_path = f"{base}_masked{ext}"

    print("=" * 60)
    print(f"[1/5] Выполняется парсинг документа: {file_path}")
    parser = get_parser(file_ext)
    parsed_doc: ParsedDocument = parser.parse(file_path)
    print(f"-> Успешно прочитан файл: {parsed_doc.filename}")

    print("\n[2/5] Запуск LLM для поиска конфиденциальных сущностей...")
    try:
        gigachat_credentials = os.getenv("GIGACHAT_CREDENTIALS")
        llm: LLMInterface = GigaChatLLM(credentials=gigachat_credentials)
    except Exception as e:
        print(f"⚠️ Ошибка инициализации GigaChatLLM ({e}). Использование фоллбэка.")
        llm: LLMInterface = LocalOllamaLLM()

    target_types = ['INN', 'PHONE', 'PARTY', 'EMAIL', 'PASSPORT', 'ADDRESS', 'FIO']
    extracted_entities_list: List[MaskedEntity] = llm.extract_entities(parsed_doc, target_types)

    initial_replacements_dict: Dict[str, str] = {}
    initial_report_items: List[Dict[str, Any]] = []

    for entity in extracted_entities_list:
        initial_replacements_dict[entity.original_text] = entity.masked_text
        initial_report_items.append({
            "text": entity.original_text,
            "type": entity.entity_type,
            "mask": entity.masked_text,
            "confidence": entity.confidence
        })

    if debug_mode:
        debug_missing_entities_session(
            llm=llm,
            document_text=parsed_doc.full_text,
            extracted_entities=initial_replacements_dict
        )

    print("\n[3/5] Запуск модуля проверки полноты и валидации...")
    validator = InteractiveValidator(llm_client=llm)

    final_replacements_dict: Dict[str, str] = validator.validate_and_clarify(
        document_text=parsed_doc.full_text,
        extracted_entities=initial_replacements_dict
    )

    final_report_items: List[Dict[str, Any]] = []
    for orig_text, mask_text in final_replacements_dict.items():
        entity_type = "USER_ADDED"
        for item in initial_report_items:
            if item["text"] == orig_text:
                entity_type = item["type"]
                break

        final_report_items.append({
            "text": orig_text,
            "type": entity_type,
            "mask": mask_text
        })

    print("\n[4/5] Применение маскирования к документу...")
    if file_ext == ".docx":
        mask_docx(file_path, output_path, final_replacements_dict)
    elif file_ext == ".xlsx":
        mask_xlsx(file_path, output_path, final_replacements_dict)
    elif file_ext == ".pdf":
        mask_pdf(file_path, output_path, final_replacements_dict)

    print("\n[5/5] Формирование отчётов о заменённых фрагментах...")

    json_report_path = ReportGenerator.save_json_report(
        input_filename=parsed_doc.filename,
        output_filename=os.path.basename(output_path),
        initial_replacements=initial_report_items,
        final_replacements=final_report_items
    )

    txt_report_path = ReportGenerator.save_txt_report(
        input_filename=parsed_doc.filename,
        output_filename=os.path.basename(output_path),
        initial_replacements=initial_report_items,
        final_replacements=final_report_items
    )

    print("=" * 60)
    print(" ОБРАБОТКА И ГЕНЕРАЦИЯ ОТЧЁТОВ УСПЕШНО ЗАВЕРШЕНЫ!")
    print(f"📄 Обезличенный документ: {os.path.abspath(output_path)}")
    print(f"📊 Отчёт JSON:           {os.path.abspath(json_report_path)}")
    print(f"📝 Отчёт TXT:            {os.path.abspath(txt_report_path)}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_file_path = sys.argv[1]
    else:
        input_file_path = input("Введите путь к документу (.docx, .xlsx, .pdf): ").strip().strip('"')

    run_pipeline(input_file_path)