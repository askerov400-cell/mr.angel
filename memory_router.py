from memory_manager import add_memory
from state_manager import update_state


def route_memory(classification):
    """
    Маршрутизатор памяти Хранителя.

    Получает результат classify_memory()
    и направляет его в нужное хранилище.
    """

    if not classification:
        return {
            "action": "ignored",
            "reason": "Пустой результат классификации"
        }

    memory_type = str(
        classification.get("type", "IGNORE")
    ).upper()

    # ----------------------------------------------
    # IGNORE — НЕ СОХРАНЯЕМ
    # ----------------------------------------------

    if memory_type == "IGNORE":
        return {
            "action": "ignored",
            "reason": classification.get(
                "reason",
                "Информация не требует сохранения"
            )
        }

    # ----------------------------------------------
    # STATE — ИЗМЕНЯЕМОЕ СОСТОЯНИЕ
    # ----------------------------------------------

    if memory_type == "STATE":

        key = classification.get("state_key")

        if not key:
            return {
                "action": "error",
                "reason": "STATE не содержит state_key"
            }

        if "state_value" not in classification:
            return {
                "action": "error",
                "reason": "STATE не содержит state_value"
            }

        value = classification.get("state_value")

        result = update_state(
            key=key,
            value=value,
            category=classification.get("category"),
            unit=classification.get("state_unit"),
            source="memory_classifier",
            confidence=classification.get("confidence")
        )

        return {
            "action": "state",
            "result": result
        }

    # ----------------------------------------------
    # ДОЛГОВРЕМЕННАЯ ПАМЯТЬ
    # ----------------------------------------------

    result = add_memory(classification)

    return {
        "action": "memory",
        "result": result
    }


async def process_memory(text):
    """
    Полный цикл обработки сообщения:

    текст пользователя
    -> классификация
    -> маршрутизация
    -> сохранение в нужное хранилище
    """

    from memory_classifier import classify_memory

    classification = await classify_memory(text)

    storage_result = route_memory(classification)

    return {
        "classification": classification,
        "storage": storage_result
    }