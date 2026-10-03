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

Supabase и Railway выбраны для дальнейшей настройки, но пока не подключены.

Правила работы — `AGENTS.md`. Спецификации — `specs/`.
