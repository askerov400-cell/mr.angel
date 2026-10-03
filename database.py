import sqlite3
from pathlib import Path
from datetime import datetime


DB_PATH = Path(__file__).resolve().parent / "mrangel.db"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with get_connection() as conn:

        # Подтверждённые факты
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                fact_text TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            )
        """)

        # Наблюдения и гипотезы агента
        conn.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                observation_text TEXT NOT NULL,
                evidence TEXT,
                confidence REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            )
        """)

        # Цели пользователя
        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                goal_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                priority INTEGER NOT NULL DEFAULT 5,
                source TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
        """)

        # Значимые события и решения
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                event_text TEXT NOT NULL,
                event_date TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()


def add_fact(
    telegram_user_id,
    category,
    fact_text,
    source="user",
    confidence=1.0
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO facts (
                telegram_user_id,
                category,
                fact_text,
                source,
                confidence,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                category,
                fact_text,
                source,
                confidence,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
        return cursor.lastrowid


def get_facts(telegram_user_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM facts
            WHERE telegram_user_id = ?
            ORDER BY id ASC
            """,
            (telegram_user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


def add_observation(
    telegram_user_id,
    category,
    observation_text,
    evidence="",
    confidence=0.5
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO observations (
                telegram_user_id,
                category,
                observation_text,
                evidence,
                confidence,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                telegram_user_id,
                category,
                observation_text,
                evidence,
                confidence,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
        return cursor.lastrowid


def get_observations(telegram_user_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM observations
            WHERE telegram_user_id = ?
            AND status = 'active'
            ORDER BY id ASC
            """,
            (telegram_user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


def add_goal(
    telegram_user_id,
    category,
    goal_text,
    priority=5,
    source="user"
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO goals (
                telegram_user_id,
                category,
                goal_text,
                status,
                priority,
                source,
                created_at
            )
            VALUES (?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                telegram_user_id,
                category,
                goal_text,
                priority,
                source,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
        return cursor.lastrowid


def get_goals(telegram_user_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM goals
            WHERE telegram_user_id = ?
            AND status = 'active'
            ORDER BY priority DESC, id ASC
            """,
            (telegram_user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


def add_event(
    telegram_user_id,
    category,
    event_text,
    event_date=None,
    source="user"
):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO events (
                telegram_user_id,
                category,
                event_text,
                event_date,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                category,
                event_text,
                event_date,
                source,
                datetime.now().isoformat(timespec="seconds")
            )
        )
        conn.commit()
        return cursor.lastrowid


def get_events(telegram_user_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM events
            WHERE telegram_user_id = ?
            ORDER BY id ASC
            """,
            (telegram_user_id,)
        ).fetchall()

        return [dict(row) for row in rows]


if __name__ == "__main__":
    init_database()

    print("База данных MrAngel готова.")
    print(f"Файл базы: {DB_PATH}")
    print("")
    print("Структура памяти:")
    print("1. facts        — подтверждённые факты")
    print("2. observations — наблюдения и гипотезы агента")
    print("3. goals        — цели пользователя")
    print("4. events       — события и решения")