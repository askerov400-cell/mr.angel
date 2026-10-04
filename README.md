# Хранитель

Telegram-бот для общения и записи данных пользователя.

## Локальный запуск в PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Заполнить `TELEGRAM_BOT_TOKEN` и `DEEPSEEK_API_KEY` в локальном `.env`. Не публиковать этот файл.

```powershell
.\.venv\Scripts\python.exe -u bot.py
```

Остановка: `Ctrl+C`.

Сейчас бот использует локальную SQLite-базу. В проекте также есть модули JSON-памяти и состояния. Локальные данные исключены из Git.

Бесплатный проект Supabase создан; для подключения приложения нужны
`SUPABASE_URL`, серверный `SUPABASE_SECRET_KEY` и `MEMORY_BACKEND=supabase`.
Хранить их в локальном `.env` или переменных Railway. Серверный ключ не публиковать.
По умолчанию остаётся SQLite; существующие данные ещё не перенесены.

Автоматическая классификация памяти пока не подключена к переписке.

Правила работы — `AGENTS.md`. Спецификации — `specs/`.
