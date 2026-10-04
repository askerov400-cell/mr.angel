"""Compatibility API for the selected memory backend."""
import os
from dotenv import load_dotenv

load_dotenv()
BACKEND = os.getenv("MEMORY_BACKEND", "sqlite").lower()
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
