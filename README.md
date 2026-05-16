# VetSchedule 🐾

Веб-сайт расписания занятий + Telegram-бот для групп **ВМ.О-ВЕТ.С-22-1…7**.

---

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy, SQLite / PostgreSQL |
| Frontend | Vanilla JS SPA, PWA (offline), темная/светлая тема |
| Bot | python-telegram-bot v21 (async), ConversationHandler |
| Данные | JSON-файлы расписания + SQLite для ДЗ |

---

## Структура проекта

```
vetschedule/
├── main.py              # FastAPI-приложение, все /api/* роуты
├── bot.py               # Telegram-бот
├── database.py          # SQLAlchemy-модели (User, Homework, HomeworkFile)
├── schedule_utils.py    # Общие утилиты (загрузка JSON, форматирование)
├── config.py            # Конфигурация через env-переменные
├── run.py               # Одновременный запуск сервера + бота
├── schedule_parser.py   # Парсер PDF → DOCX → JSON (отдельный скрипт)
├── generate_icons.py    # Генератор иконок PWA
├── requirements.txt
├── .env.example
├── Procfile             # Для Heroku/Railway
├── schedule_json/       # JSON-файлы расписания (по группе)
│   ├── ВМ_О_ВЕТ_С_22_1.json
│   └── ...
├── uploads/             # Загруженные файлы ДЗ
└── static/              # Frontend (SPA)
    ├── index.html
    ├── manifest.json
    └── sw.js
```

---

## Быстрый старт (локально)

### 1. Клонируй и настрой окружение

```bash
git clone <repo>
cd vetschedule

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Создай `.env`

```bash
cp .env.example .env
# Открой .env и вставь TELEGRAM_TOKEN
```

### 3. Положи JSON-расписания

Скопируй файлы `ВМ_О_ВЕТ_С_22_*.json` в папку `schedule_json/`
(или запусти парсер: `python schedule_parser.py --local-docx schedule.docx`).

### 4. Сгенерируй иконки PWA

```bash
python generate_icons.py
```

### 5. Запусти

```bash
# Только сервер (без бота):
uvicorn main:app --reload

# Сервер + бот одновременно:
python run.py
```

Открой: **http://localhost:8000**

---

## Telegram-бот

### Команды

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + выбор группы |
| `/today` | Расписание на сегодня |
| `/tomorrow` | Расписание на завтра |
| `/week` или `/schedule` | Расписание на текущую неделю (с навигацией ← →) |
| `/hw` | Список домашних заданий группы |
| `/addhw` | Добавить ДЗ интерактивно |
| `/cancel` | Отменить текущий диалог |

### Получить токен бота

1. Открой **@BotFather** в Telegram
2. `/newbot` → введи имя и username
3. Скопируй токен в `.env` → `TELEGRAM_TOKEN=...`

---

## API Endpoints

### Расписание

```
GET  /api/groups                       → список групп
GET  /api/schedule/{group}             → полное расписание
GET  /api/schedule/{group}/week/{num}  → конкретная неделя (ISO номер)
GET  /api/schedule/{group}/today       → занятия сегодня
GET  /api/schedule/{group}/tomorrow    → занятия завтра
```

### Домашние задания

```
GET    /api/homework?group=...&status=...   → список ДЗ
POST   /api/homework                        → создать ДЗ
GET    /api/homework/{id}                   → одно ДЗ
PUT    /api/homework/{id}                   → обновить ДЗ
DELETE /api/homework/{id}                   → удалить ДЗ
POST   /api/homework/{id}/files             → загрузить файл
GET    /api/files/{id}                      → скачать файл
```

### Пользователи (для бота)

```
POST /api/users            → создать/обновить пользователя
GET  /api/users/{tg_id}    → получить пользователя по Telegram ID
```

Документация Swagger: **http://localhost:8000/docs**

---

## Обновление расписания

```bash
# Скачать новый PDF и обновить JSON одной командой:
python schedule_parser.py --url https://site.ru/schedule.pdf

# Автообновление каждые 60 минут:
python schedule_parser.py --url https://site.ru/schedule.pdf --interval 60
```

Сервер читает JSON при каждом запросе — перезапуск не нужен.

---

## Деплой на Railway / Render

### Railway

```bash
railway init
railway add --database postgresql   # опционально
railway up
```

Установи переменные окружения в панели Railway:
- `TELEGRAM_TOKEN`
- `SITE_URL` = `https://<your-app>.railway.app`
- `DATABASE_URL` (автоматически если добавил PostgreSQL)

### Render

1. New Web Service → выбери репозиторий
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Добавь переменные окружения
5. Бот — отдельный Background Worker с командой `python bot.py`

### Vercel (только фронтенд)

Vercel не поддерживает Python-процессы напрямую. Для фронтенда деплой статику в `static/`,
бэкенд — на Railway/Render.

---

## Структура JSON-расписания

```json
{
  "group": "ВМ.О-ВЕТ.С-22-1",
  "generated": "2026-05-11T10:00:00",
  "weeks": [
    {
      "week": 15,
      "date_range": "7–10 апреля 2026",
      "days": [
        {
          "day_name": "Вторник",
          "date": "7/04",
          "lessons": [
            {
              "time": "09.00-10.30",
              "subject": "л. Ветеринарно-санитарная экспертиза",
              "teacher": "Савина И.П.",
              "room": "УЛК-А/Лек.1",
              "type": "lecture"
            }
          ]
        }
      ]
    }
  ]
}
```

**Типы занятий** (`type`):
- `lecture` — лекция (синий)
- `lab` — лабораторная (жёлтый)
- `practical` — практика (зелёный)
- `other` — прочее (фиолетовый)

---

## Зависимости

```
fastapi          — REST API
uvicorn          — ASGI-сервер
sqlalchemy       — ORM для базы данных
python-telegram-bot — Telegram Bot API
aiofiles         — асинхронная работа с файлами
python-multipart — загрузка файлов (multipart/form-data)
apscheduler      — планировщик напоминаний
pydantic         — валидация данных
httpx            — HTTP-клиент (бот → API)
pdf2docx         — конвертация PDF (парсер)
python-docx      — чтение DOCX (парсер)
requests         — скачивание PDF (парсер)
```
