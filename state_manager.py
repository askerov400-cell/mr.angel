import json
import os
from datetime import datetime


STATE_FILE = "state.json"


# --------------------------------------------------
# ЗАГРУЗКА СОСТОЯНИЙ
# --------------------------------------------------

def load_state():
    """Загружает актуальные состояния пользователя."""

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

            if isinstance(data, dict):
                return data

            return {}

    except (json.JSONDecodeError, OSError) as error:
        print("STATE LOAD ERROR:", repr(error))
        return {}


# --------------------------------------------------
# СОХРАНЕНИЕ СОСТОЯНИЙ
# --------------------------------------------------

def save_state(state):
    """Сохраняет состояния пользователя."""

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )


# --------------------------------------------------
# ОБНОВЛЕНИЕ СОСТОЯНИЯ
# --------------------------------------------------

def update_state(
    key,
    value,
    category=None,
    unit=None,
    source=None,
    confidence=None
):
    """
    Создаёт или обновляет текущее состояние пользователя.

    Старое значение не уничтожается.
    Оно переносится в историю.
    """

    state = load_state()

    now = datetime.now().isoformat(
        timespec="seconds"
    )

    # ----------------------------------------------
    # СОСТОЯНИЯ ЕЩЁ НЕТ
    # ----------------------------------------------

    if key not in state:

        state[key] = {
            "current": value,
            "category": category,
            "unit": unit,
            "confidence": confidence,
            "source": source,
            "created_at": now,
            "updated_at": now,
            "history": []
        }

        save_state(state)

        return {
            "action": "created",
            "key": key,
            "current": value
        }

    item = state[key]

    old_value = item.get("current")

    # ----------------------------------------------
    # ЗНАЧЕНИЕ НЕ ИЗМЕНИЛОСЬ
    # ----------------------------------------------

    if old_value == value:

        item["updated_at"] = now

        if confidence is not None:
            item["confidence"] = confidence

        if source is not None:
            item["source"] = source

        if category is not None:
            item["category"] = category

        if unit is not None:
            item["unit"] = unit

        save_state(state)

        return {
            "action": "unchanged",
            "key": key,
            "current": value
        }

    # ----------------------------------------------
    # ЗНАЧЕНИЕ ИЗМЕНИЛОСЬ
    # ----------------------------------------------

    history = item.setdefault(
        "history",
        []
    )

    history.append({
        "value": old_value,
        "from": item.get("updated_at"),
        "to": now,
        "confidence": item.get("confidence"),
        "source": item.get("source")
    })

    item["current"] = value
    item["updated_at"] = now

    if category is not None:
        item["category"] = category

    if unit is not None:
        item["unit"] = unit

    if confidence is not None:
        item["confidence"] = confidence

    if source is not None:
        item["source"] = source

    save_state(state)

    return {
        "action": "updated",
        "key": key,
        "previous": old_value,
        "current": value
    }


# --------------------------------------------------
# ПОЛУЧЕНИЕ ОДНОГО СОСТОЯНИЯ
# --------------------------------------------------

def get_state(key):
    """Возвращает одно актуальное состояние."""

    state = load_state()

    return state.get(key)


# --------------------------------------------------
# ПОЛУЧЕНИЕ ВСЕХ СОСТОЯНИЙ
# --------------------------------------------------

def get_all_states():
    """Возвращает все актуальные состояния."""

    return load_state()


# --------------------------------------------------
# ПОЛУЧЕНИЕ ИСТОРИИ
# --------------------------------------------------

def get_history(key):
    """Возвращает историю изменения состояния."""

    item = get_state(key)

    if not item:
        return []

    return item.get(
        "history",
        []
    )