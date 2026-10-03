from database import init_database, add_fact, get_facts


TEST_USER_ID = 123456789


init_database()

facts_before = get_facts(TEST_USER_ID)

if not facts_before:
    print("Фактов пока нет.")
    print("Записываю первый тестовый факт...")

    add_fact(
        telegram_user_id=TEST_USER_ID,
        category="test",
        fact_text="Тестовый автомобиль пользователя — Volvo.",
        source="user",
        confidence=1.0
    )
else:
    print("В базе уже есть сохранённые факты.")


facts_after = get_facts(TEST_USER_ID)

print()
print("Содержимое постоянной памяти:")

for fact in facts_after:
    print(
        f"ID: {fact['id']} | "
        f"Категория: {fact['category']} | "
        f"Факт: {fact['fact_text']} | "
        f"Источник: {fact['source']} | "
        f"Уверенность: {fact['confidence']}"
    )