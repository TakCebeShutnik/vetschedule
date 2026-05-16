# VetSchedule

Расписание и домашние задания для групп **ВМ.О-ВЕТ.С-22-1…7**: сайт (PWA), Telegram-бот, парсер PDF → JSON.

## Архитектура (продакшен)

| Компонент | Где |
|-----------|-----|
| Парсер → `schedule_json/` | GitHub Actions |
| Сайт | Vercel (`static/`) |
| API + бот + БД | PythonAnywhere |

**Пошаговый деплой:** [DEPLOY.md](DEPLOY.md)

## Структура

```
vetschedule/
├── main.py              # FastAPI (/api/*)
├── wsgi.py              # Точка входа для PythonAnywhere
├── bot.py               # Telegram-бот
├── database.py          # User, Homework, LessonOverride
├── lesson_overrides.py  # Отмена пар поверх JSON
├── schedule_utils.py    # Загрузка JSON, форматирование
├── schedule_parser.py   # PDF → JSON (CLI и Actions)
├── config.py            # Переменные окружения
├── run.py               # Локально: парсер + API + бот
├── requirements.txt     # API + бот (PA)
├── requirements-parser.txt  # Только парсер (Actions)
├── schedule_json/       # JSON по группам (в git)
├── static/              # Фронтенд (Vercel)
│   ├── index.html       # ← редактировать только здесь
│   ├── config.js        # Генерируется при сборке Vercel
│   └── manifest.json, sw.js, icons/
└── .github/workflows/update-schedule.yml
```

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env            # TELEGRAM_TOKEN и при необходимости SCHEDULE_PDF_URL
python run.py
```

Открыть **http://localhost:8000**

Иконки PWA (опционально): `pip install Pillow` → `python scripts/generate_pwa_icons.py`

## Бот — команды

| Команда | Описание |
|---------|----------|
| `/start` | Выбор группы |
| `/today`, `/tomorrow`, `/week` | Расписание |
| `/hw`, `/addhw` | Домашние задания |
| `/cancellesson` | Отмена / возврат пары (код редактора) |
| `/cancel` | Выйти из диалога |

## API (кратко)

- `GET /api/groups`, `/api/schedule/{group}`, `/today`, `/tomorrow`
- `POST /api/lesson-overrides/toggle` — отмена пары (нужен `editor_code`)
- CRUD `/api/homework`, файлы `/api/files/{id}`

Swagger: http://localhost:8000/docs

## Обновление расписания

- **Продакшен:** GitHub Actions → `git pull` на PythonAnywhere
- **Локально:** `python schedule_parser.py --url "https://…pdf" -o schedule_json` или `SCHEDULE_PDF_URL` в `.env` и `python run.py`
