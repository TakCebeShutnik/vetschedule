# Развёртывание на Vercel

Всё на одном домене Vercel: **сайт**, **API**, **бот** (через webhook).  
Парсер PDF → JSON по-прежнему в **GitHub Actions** (тяжёлый, долгий — на Vercel не запускаем).

---

## Схема

```
GitHub Actions  →  коммит schedule_json/  →  push  →  Vercel пересобирается
                                                          │
                    https://ваш-проект.vercel.app  ←──────┘
                    ├── /          сайт (static/)
                    ├── /api/*     FastAPI
                    └── /api/telegram/webhook   Telegram
```

---

## 0. Репозиторий GitHub

`git init` только в **корне** `vetschedule/` (где `main.py`), не в `schedule_json/`.

```powershell
cd "F:\Рабочий стол\vetschedule"
git add .
git commit -m "VetSchedule"
git push origin main
```

---

## 1. GitHub Actions — парсер (без изменений)

**Settings** → **Secrets** → `SCHEDULE_PDF_URL` = ссылка на PDF.

Workflow `.github/workflows/update-schedule.yml` обновляет `schedule_json/` в репозитории.  
После push Vercel сам задеплоит новую версию.

---

## 2. Vercel — импорт проекта

### 2.1 New Project

1. [vercel.com](https://vercel.com) → **Add New** → **Project** → репозиторий `TakCebeShutnik/vetschedule`.
2. **Framework Preset:** **FastAPI** (или Other — подхватит `main.py` и `vercel.json`).

### 2.2 Настройки сборки (важно)

| Поле | Значение |
|------|----------|
| **Root Directory** | `./` |
| **Build Command** | `python scripts/inject_api_config.py` |
| **Output Directory** | **оставить пустым** (не `static`!) |
| **Install Command** | `pip install -r requirements.txt` |

Если указать **Output Directory = static**, API не заработает — будет только статика.

`vercel.json` в репозитории уже задаёт install/build.

### 2.3 Переменные окружения (Production + Preview)

| Переменная | Пример | Обязательно |
|------------|--------|-------------|
| `TELEGRAM_TOKEN` | от @BotFather | да, для бота |
| `SITE_URL` | `https://vetschedule.vercel.app` | да, ваш URL Vercel |
| `CRON_SECRET` | длинная случайная строка | да, для setup-webhook |
| `EDITOR_CODE` | `0801` | да (= код на сайте) |
| `TELEGRAM_MODE` | `webhook` | на Vercel ставится само |
| `CORS_ORIGINS` | можно не задавать (`*`) | нет |

**Не нужны** на Vercel: `API_PUBLIC_URL`, `API_INTERNAL_URL` (подставятся из `SITE_URL`).

Опционально позже: `DATABASE_URL` = Postgres (Neon / Vercel Postgres), если нужна постоянная БД.

### 2.4 Deploy

Нажмите **Deploy**. Дождитесь зелёного статуса.

### 2.5 Проверка API

Откройте в браузере:

`https://ВАШ-ПРОЕКТ.vercel.app/api/groups`

Должен быть JSON со списком групп.

### 2.6 Подключить Telegram-бота (webhook)

В браузере **один раз** (подставьте свой домен и секрет):

```
https://ВАШ-ПРОЕКТ.vercel.app/api/telegram/setup-webhook?secret=ВАШ_CRON_SECRET
```

Ответ: `{"ok":true,"webhook_url":"..."}`.

Напишите боту `/start` в Telegram.

### 2.7 Сайт

`https://ВАШ-ПРОЕКТ.vercel.app/` — расписание и ДЗ. API на том же домене, отдельный `API_PUBLIC_URL` не нужен.

---

## 3. Локальная разработка

```powershell
pip install -r requirements.txt
cp .env.example .env
# TELEGRAM_TOKEN, SITE_URL=http://localhost:8000
python run.py
```

- Сайт + API: http://localhost:8000  
- Бот: **polling** (`TELEGRAM_MODE` по умолчанию не webhook без `VERCEL=1`)

---

## 4. Ограничения Vercel (бесплатный план)

| Что | Как на Vercel |
|-----|----------------|
| SQLite | Файл в `/tmp` — данные ДЗ/отмены могут **сбрасываться** при холодном старте |
| Файлы ДЗ | `/tmp/uploads` — то же |
| Напоминания ДЗ (cron в боте) | Отключены в webhook-режиме |
| Парсер PDF | Только GitHub Actions |

Для стабильной БД: подключите **Postgres** (`DATABASE_URL`) и при необходимости внешнее хранилище файлов.

---

## 5. Частые ошибки

| Симптом | Решение |
|---------|---------|
| Сайт есть, API 404 | Убрать **Output Directory = static**, пресет FastAPI |
| Failed to fetch | Деплой не прошёл / нет `/api/groups` |
| Бот молчит | Вызвать `setup-webhook`, проверить `TELEGRAM_TOKEN` и `SITE_URL` |
| 403 setup-webhook | Неверный `CRON_SECRET` в URL |

---

## 6. Самопроверка после деплоя

1. `/api/groups` → JSON  
2. `/` → выбор группы, расписание  
3. `setup-webhook` → ok  
4. Бот `/today` → расписание  
