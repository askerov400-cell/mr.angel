# Карта Хранителя

Рабочий каталог: C:/MrAngel. Бот: **@MrAngel_1_1_bot**.
Обновлено 10.10.2026. Начни с таблицы, затем читай нужную спецификацию.

## Где искать

| Задача | Код | Спецификация / тесты |
|---|---|---|
| Кнопки и главное меню | [interface/menu.py](interface/menu.py) | specs/telegram-interface.md, tests/test_interface.py |
| Запуск, команды, маршрутизация | [bot.py](bot.py) | README.md, requirements.txt |
| Манера общения | [prompts/guardian.txt](prompts/guardian.txt), bot.py → handle_text | specs/concise-replies.md, specs/contextual-replies.md |
| Автоматическая память | [memory/service.py](memory/service.py) | specs/automatic-memory.md, tests/test_automatic_memory.py |
| Классификация сведений | [memory_classifier.py](memory_classifier.py), memory/validation.py | specs/unambiguous-memory.md |
| История и восстановление диалога | [memory/journal.py](memory/journal.py) | specs/chat-history.md, specs/dialogue-recovery.md |
| Смысл коротких ответов | [memory/dialogue_context.py](memory/dialogue_context.py) | tests/test_dialogue_context.py |
| Форматированные команды | [memory/commands.py](memory/commands.py) | specs/formatted-commands.md |
| Выбор хранилища | [database.py](database.py) | specs/supabase-memory.md |
| Supabase: память и запросы | [storage/supabase_store.py](storage/supabase_store.py) | db/*.sql, tests/test_supabase_store.py |
| SQLite: локальный режим | [storage/sqlite_store.py](storage/sqlite_store.py) | database.py |
| Знакомство и ответы на вопросы | [acquaintance/handlers.py](acquaintance/handlers.py), store.py | specs/owner-acquaintance.md, tests/test_acquaintance.py |
| Расписание вопросов | [acquaintance/schedule.py](acquaintance/schedule.py), worker.py, questions.py | db/owner_questions.sql |
| Голосовые сообщения | [speech/handler.py](speech/handler.py) | specs/audio-messages.md, tests/test_audio.py |
| Фотографии | [vision/handler.py](vision/handler.py) | specs/photo-messages.md, tests/test_photo.py |
| Видео, кадры и звук | [video/handler.py](video/handler.py), extract.py, analysis.py | specs/video-messages.md, tests/test_video.py |
| Kaspi: кнопки и действия | [kaspi/handlers.py](kaspi/handlers.py) | specs/kaspi-orders.md, tests/test_kaspi.py |
| Kaspi: подключение и ошибки API | [kaspi/client.py](kaspi/client.py) | specs/kaspi-orders.md |
| Kaspi: статистика | [kaspi/statistics.py](kaspi/statistics.py) | specs/kaspi-products.md |
| X2POS: товары, остатки и движения | [x2pos/handlers.py](x2pos/handlers.py) | specs/x2pos-integration.md, tests/test_x2pos.py |
| X2POS: запросы API и права доступа | [x2pos/client.py](x2pos/client.py) | specs/x2pos-integration.md |
| Получение ключа X2POS | [x2pos/setup.py](x2pos/setup.py) | Скрытый ввод; пароль не сохраняется |
| Названия настроек | [.env.example](.env.example) | Значения только в .env / Railway |
| Правила и требования | [AGENTS.md](AGENTS.md), [specs/README.md](specs/README.md) | Спецификация → код → проверка |

memory_manager.py, memory_router.py, state_manager.py — прежние модули JSON-памяти/состояния.
Текущие bot.py и memory/ их не импортируют. Для исправления Supabase-памяти начинать с memory/ и storage/.
Корневые test_memory.py и test_classifier.py — ранние проверки; основной набор находится в tests/.

## Путь сообщения

    Telegram → bot.py
      ├─ меню → interface/menu.py
      ├─ вопросы → acquaintance/handlers.py → store.py → Supabase
      ├─ Kaspi → kaspi/handlers.py → client.py → API Kaspi
      ├─ X2POS → x2pos/handlers.py → client.py → API X2POS
      ├─ голос → speech/handler.py → обработка текста
      ├─ фото → vision/handler.py
      ├─ видео → video/handler.py → extract.py / analysis.py
      └─ текст → handle_text → история + память + ответ DeepSeek

История: memory/journal.py. Полезные сведения: memory/service.py → memory_classifier.py.
Рабочее хранилище — Supabase; SQLite остаётся альтернативой по настройке.
DeepSeek: общение и классификация. Groq: распознавание и анализ медиа.
Данные Kaspi/X2POS показываются отдельно, не передаются в разговорную память и LLM.

## Размещение и состояние

Git: https://github.com/askerov400-cell/mr.angel.git, ветка main.
Railway: проект pacific-enjoyment, сервис mr.angel.
[Переменные Хранителя](https://railway.com/project/f3762568-e53f-4261-80a6-c0b00e60907c/service/e1296760-5d16-4dec-aaa1-c251564abb0b/variables?environmentId=8672a2ae-668f-4cf6-b76b-42331bee818d).
Supabase: guardian; схема и миграции — db/.
Mr Ai Studio — другой проект; его сервис не использовать для Хранителя.
Не запускать вторую локальную копию bot.py, пока Railway получает сообщения того же бота.

| Раздел | Подтверждённое состояние |
|---|---|
| Общение, память | Рабочий бот на Railway, хранение в Supabase |
| Голос, фото, видео | Реализованы; ограничения в соответствующих specs |
| Вопросы владельцу | Расписание и хранение ответов; до 10 вопросов с 10:00 до 23:00 |
| Kaspi | Кнопка и код есть. Реальный API не подтверждён из-за сетевых ошибок; приём/отмена не проверены |
| X2POS | Локально проверены ключ, права, 50 товаров и остатки. Код развёрнут. Настройки ещё нужно перенести на Railway |
| X2POS: движения | Код подготовлен; реальные документы пока не проверены |
| Автоматические цены, предзаказ, общая товарная аналитика | Пока не реализованы |

## Быстрые проверки

Из C:/MrAngel в PowerShell:

    ./.venv/Scripts/python.exe -m unittest discover -s tests
    ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_x2pos.py
    ./.venv/Scripts/python.exe -m unittest discover -s tests -p test_kaspi.py
    git status --short
    git diff --check

Последний полный прогон: 120 тестов прошли. Подменённый API в тестах не доказывает реальное подключение.

## Порядок работы без повторного чтения всего проекта

1. Найти функцию в таблице; открыть её спецификацию.
2. Искать внутри нужного модуля, например: rg -n 'timeout|HTTPError' x2pos.
3. Прочитать зависимости и вызывающий обработчик.
4. До изменения поведения обновить спецификацию.
5. Проверить затронутый раздел; полный набор запускать при изменении общих компонентов.
6. Отдельно сообщать состояние кода, тестов и реального API.
7. При добавлении модулей, переносе файлов и изменении статуса подключения обновлять карту.

Секреты, личные ID, данные памяти и выгрузки учёта в карту и Git не включать.
