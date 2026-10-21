"""Compatibility API for the selected memory backend."""
import os
from dotenv import load_dotenv

load_dotenv()


def select_backend(read=os.getenv):
    """Явный выбор имеет приоритет; без него Supabase включается по наличию ключей."""
    chosen = (read("MEMORY_BACKEND") or "").strip().lower()
    if chosen:
        return chosen
    if (read("SUPABASE_URL") or "").strip() and (read("SUPABASE_SECRET_KEY") or "").strip():
        return "supabase"
    return "sqlite"


BACKEND = select_backend()
if BACKEND == "supabase":
    from storage.supabase_store import (
        init_database, add_fact, get_facts, add_observation, get_observations,
        add_goal, get_goals, add_event, get_events,
    )
elif BACKEND == "sqlite":
    from storage.sqlite_store import (
        DB_PATH, get_connection, init_database, add_fact, get_facts,
        add_observation, get_observations, add_goal, get_goals, add_event, get_events,
    )
else:
    raise RuntimeError("MEMORY_BACKEND must be sqlite or supabase")
