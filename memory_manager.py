import json
import os
from datetime import datetime

from openai import OpenAI
from dotenv import load_dotenv


# --------------------------------------------------
# НАСТРОЙКИ
# --------------------------------------------------

load_dotenv()

MEMORY_FILE = "memory.json"

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


# --------------------------------------------------
# ЗАГРУЗКА ПАМЯТИ
# --------------------------------------------------

def load_memory():
    """Загружает долговременную память Хранителя."""

    if not os.path.exists(MEMORY_FILE):
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            if isinstance(data, list):
                return data

            return []

    except (json.JSONDecodeError, OSError) as error:
        print("MEMORY LOAD ERROR:", repr(error))
        return []


# --------------------------------------------------
# СОХРАНЕНИЕ ПАМЯТИ
# --------------------------------------------------

def save_memory(memory):
    """Сохраняет долговременную память Хранителя."""

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(
            memory,
            file,
            ensure_ascii=False,
            indent=2
        )


# --------------------------------------------------
# ТОЧНЫЙ ДУБЛЬ
# --------------------------------------------------

def exact_duplicate(memory, memory_text):
    """Проверяет полное текстовое совпадение."""

    new_text = memory_text.strip().lower()

    for item in memory:

        old_text = item.get(
            "memory_text",
            ""
        ).strip().lower()

        if old_text == new_text:
            return item

    return None


# --------------------------------------------------
# СМЫСЛОВОЙ ДУБЛЬ
# --------------------------------------------------

def semantic_duplicate(new_text, memory):
    """
    Проверяет через DeepSeek, описывает ли новая запись
    уже существующий конкретный факт или событие.
    """

    if not memory:
        return {
            "duplicate": False,
            "existing_id": None,
            "confidence": 1.0,
            "reason": "Память пуста"
        }

    existing = []

    for item in memory:

        existing.append({
            "id": item.get("id"),
            "type": item.get("type"),
            "category": item.get("category"),
            "memory_text": item.get("memory_text")
        })

    prompt = f"""
Ты являешься модулем дедупликации долговременной памяти
персонального ИИ-агента Хранитель.

Твоя задача:

Определить, описывает ли НОВАЯ ЗАПИСЬ тот же самый
конкретный факт или то же самое конкретное событие,
которое уже присутствует в памяти.

НОВАЯ ЗАПИСЬ:

{new_text}


СУЩЕСТВУЮЩАЯ ПАМЯТЬ:

{json.dumps(existing, ensure_ascii=False, indent=2)}


СРАВНИВАЙ СМЫСЛ, А НЕ СЛОВА.


ПРИМЕР 1:

"Пользователь подписал договор с новым поставщиком."

и

"Пользователь заключил контракт с новым поставщиком."

Это ДУБЛЬ, если нет информации,
указывающей, что речь идет о разных договорах.


ПРИМЕР 2:

"Пользователь подписал договор с поставщиком A."

и

"Пользователь подписал договор с поставщиком B."

Это НЕ ДУБЛЬ.


ПРИМЕР 3:

"Пользователь весит 77 кг."

и

"Вес пользователя составляет 77 килограммов."

Это ДУБЛЬ.


ПРИМЕР 4:

"Пользователь весит 77 кг."

и

"Пользователь весит 75 кг."

Это НЕ ДУБЛЬ.

Это изменение состояния пользователя.


ПРИМЕР 5:

"Пользователь решил отказаться от добавленного сахара."

и

"Пользователь сегодня не употреблял добавленный сахар."

Это НЕ ДУБЛЬ.

Первая запись — решение или правило.
Вторая запись — событие или выполнение правила.


ВАЖНЫЕ ПРАВИЛА:

1. Синонимы и перефразирование могут описывать один факт.

2. Не создавай новую память только потому,
   что пользователь сформулировал старый факт другими словами.

3. Не объединяй разные:
   - даты;
   - суммы;
   - людей;
   - компании;
   - поставщиков;
   - договоры;
   - объекты;
   - решения;
   - состояния;
   - результаты;
   - события.

4. Если новая информация описывает изменение старого состояния,
   это НЕ дубль.

5. Если существуют явные признаки,
   что события разные,
   это НЕ дубль.

6. Если информации недостаточно,
   чтобы уверенно считать записи одним событием,
   ставь duplicate = false.

7. existing_id должен содержать ID существующей записи,
   с которой обнаружен дубль.

8. confidence — уверенность именно в решении
   о наличии или отсутствии дубля.

Верни ТОЛЬКО валидный JSON.

Формат:

{{
    "duplicate": true,
    "existing_id": 1,
    "confidence": 0.98,
    "reason": "Обе записи описывают одно событие разными словами"
}}
"""

    try:

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты точный модуль дедупликации "
                        "долговременной памяти. "
                        "Сравнивай фактический смысл записей. "
                        "Отвечай только валидным JSON."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            response_format={
                "type": "json_object"
            }
        )

        result_text = (
            response
            .choices[0]
            .message
            .content
            .strip()
        )

        result = json.loads(result_text)

        print(
            "SEMANTIC CHECK:",
            result
        )

        return result

    except Exception as error:

        print(
            "SEMANTIC CHECK ERROR:",
            repr(error)
        )

        return {
            "duplicate": False,
            "existing_id": None,
            "confidence": 0.0,
            "reason": (
                "Ошибка смысловой проверки: "
                + str(error)
            )
        }


# --------------------------------------------------
# ДОБАВЛЕНИЕ НОВОЙ ПАМЯТИ
# --------------------------------------------------

def add_memory(classification):
    """
    Получает результат memory_classifier
    и принимает решение о сохранении информации.
    """

    if not classification:

        return {
            "saved": False,
            "reason": "Пустой результат классификации"
        }

    memory_type = classification.get(
        "type",
        "IGNORE"
    )

    # IGNORE не сохраняем
    if memory_type == "IGNORE":

        return {
            "saved": False,
            "reason": classification.get(
                "reason",
                "Информация не требует сохранения"
            )
        }

    memory_text = classification.get(
        "memory_text",
        ""
    ).strip()

    if not memory_text:

        return {
            "saved": False,
            "reason": "Нет текста для сохранения"
        }

    memory = load_memory()

    # --------------------------------------------------
    # ШАГ 1. ТОЧНЫЙ ДУБЛЬ
    # --------------------------------------------------

    duplicate = exact_duplicate(
        memory,
        memory_text
    )

    if duplicate:

        return {
            "saved": False,
            "reason": "Такая информация уже есть в памяти",
            "duplicate": True,
            "semantic_duplicate": False,
            "existing_id": duplicate.get("id")
        }

    # --------------------------------------------------
    # ШАГ 2. СМЫСЛОВОЙ ДУБЛЬ
    # --------------------------------------------------

    semantic = semantic_duplicate(
        memory_text,
        memory
    )

    semantic_is_duplicate = (
        semantic.get("duplicate") is True
        and
        semantic.get("confidence", 0) >= 0.85
    )

    if semantic_is_duplicate:

        return {
            "saved": False,
            "reason": semantic.get(
                "reason",
                "Обнаружен смысловой дубль"
            ),
            "duplicate": True,
            "semantic_duplicate": True,
            "existing_id": semantic.get(
                "existing_id"
            ),
            "confidence": semantic.get(
                "confidence"
            )
        }

    # --------------------------------------------------
    # ШАГ 3. НОВАЯ ИНФОРМАЦИЯ
    # --------------------------------------------------

    existing_ids = []

    for item in memory:

        item_id = item.get(
            "id",
            0
        )

        if isinstance(item_id, int):
            existing_ids.append(item_id)

    next_id = max(
        existing_ids,
        default=0
    ) + 1

    record = {
        "id": next_id,
        "type": memory_type,
        "category": classification.get(
            "category"
        ),
        "memory_text": memory_text,
        "confidence": classification.get(
            "confidence"
        ),
        "reason": classification.get(
            "reason"
        ),
        "created_at": datetime.now().isoformat(
            timespec="seconds"
        )
    }

    memory.append(record)

    save_memory(memory)

    return {
        "saved": True,
        "record": record,
        "semantic_check": semantic
    }


# --------------------------------------------------
# ПОЛУЧЕНИЕ ВСЕЙ ПАМЯТИ
# --------------------------------------------------

def get_all_memory():
    """Возвращает всю долговременную память."""

    return load_memory()