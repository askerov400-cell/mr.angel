"""Classify, save and format private memory without blocking conversation."""

import asyncio
import json
import logging

from memory.validation import validate
from storage.supabase_store import recent_memory, save_automatic

logger = logging.getLogger("guardian")


async def process(user_id, text):
    from memory_classifier import classify_memory
    try:
        raw = await asyncio.wait_for(classify_memory(text), timeout=20)
        item = validate(raw)
        if item is None:
            logger.info("Память: сообщение пропущено")
            return "ignored"
        saved = await asyncio.to_thread(save_automatic, user_id, item)
        status = "saved" if saved else "unchanged"
        logger.info("Память: %s, тип %s", status, item["type"])
        return status
    except Exception as error:
        logger.warning("Память: операция не выполнена (%s)", type(error).__name__)
        return "failed"


def format_memory(groups):
    # JSON quoting separates records from instructions. No record is trusted code.
    lines = []
    seen = set()
    for row in groups.get("facts", []):
        text = row["fact_text"]
        marker = ("FACT", text.strip().lower())
        if marker not in seen:
            lines.append("FACT: " + json.dumps(text, ensure_ascii=False))
            seen.add(marker)
    for row in groups.get("memory_entries", []):
        kind, text = row["memory_type"], row["memory_text"]
        marker = (kind, text.strip().lower())
        if marker not in seen:
            label = "OBSERVATION (предположение, не факт)" if kind == "OBSERVATION" else kind
            lines.append(label + ": " + json.dumps(text, ensure_ascii=False))
            seen.add(marker)
    for row in groups.get("user_states", []):
        lines.append("STATE: " + json.dumps({
            "key": row["state_key"], "value": row["state_value"], "unit": row["unit"],
            "updated_at": row["updated_at"],
        }, ensure_ascii=False))
    return "\n".join(lines)[:16000] or "Сохранённых данных пока нет."


async def context(user_id):
    try:
        groups = await asyncio.to_thread(recent_memory, user_id)
        return format_memory(groups)
    except Exception as error:
        logger.warning("Память: чтение не выполнено (%s)", type(error).__name__)
        return "Долговременная память сейчас недоступна; используй только текущий диалог."
