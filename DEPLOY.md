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
| `DATABASE_URL` или `POSTGRES_URL` | см. § 2.4 | **да** — без этого БД сбрасывается |
| `TELEGRAM_MODE` | `webhook` | на Vercel ставится само |
| `CORS_ORIGINS` | можно не задавать (`*`) | нет |

**Не нужны** на Vercel: `API_PUBLIC_URL`, `API_INTERNAL_URL` (подставятся из `SITE_URL`).

### 2.4 Постоянная база данных (обязательно на Vercel)

На Vercel **нельзя** хранить SQLite в `/tmp` — после перезапуска пропадут ДЗ, отмены пар и файлы.

**Вариант A — Neon (бесплатно, проще всего)**

1. [neon.tech](https://neon.tech) → проект → скопируйте **Connection string** (PostgreSQL).
2. Vercel → **Settings** → **Environment Variables** — после Connect появятся переменные Neon, например:
   - `STORAGE_POSTGRES_URL_DATABASE_URL` (код подхватит сам)
   - или вручную: `DATABASE_URL` = connection string из Neon
3. **Redeploy** (обязательно после появления переменных).

**Вариант B — Vercel Postgres**

1. Vercel → проект → **Storage** → **Create Database** → Postgres.
2. Подключите к проекту — появятся `POSTGRES_URL` (подхватится автоматически).
3. Redeploy.

Вложения к ДЗ при Postgres сохраняются **внутри БД**, не на диск.

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
| БД | Только **Postgres** (Neon / Vercel Postgres), не SQLite |
| Файлы ДЗ | В Postgres (`file_data`), если задан `DATABASE_URL` |
| Напоминания ДЗ (cron в боте) | Отключены в webhook-режиме |
| Парсер PDF | Только GitHub Actions |

Для стабильной БД: подключите **Postgres** (`DATABASE_URL`) и при необходимости внешнее хранилище файлов.

---

## 5. Частые ошибки

| Симптом | Решение |
|---------|---------|
| **500**, `could not import main.py`, «нужна постоянная БД» | Storage → Neon подключён к проекту → **Redeploy**. Либо вручную: `DATABASE_URL` = строка из `STORAGE_POSTGRES_URL_DATABASE_URL` |
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
