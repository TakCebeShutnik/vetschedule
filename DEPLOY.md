# Развёртывание VetSchedule

Три части:

| Часть | Платформа | Что делает |
|-------|-----------|------------|
| Парсер PDF → JSON | **GitHub Actions** | Раз в неделю (или вручную) обновляет `schedule_json/` в репозитории |
| Сайт (PWA) | **Vercel** | Статика из `static/`, запросы к API на PythonAnywhere |
| API + бот | **PythonAnywhere** | FastAPI, SQLite, загрузки ДЗ, Telegram-бот |

---

## 0. Подготовка репозитория GitHub

1. Создайте **пустой** репозиторий на GitHub (без README, если будете пушить свой код).

2. **Важно:** `git init` только в **корне проекта** `vetschedule/`, **не** в `schedule_json/` и не в `static/`.

```powershell
cd "F:\Рабочий стол\vetschedule"    # корень, где лежат main.py и bot.py
git init                              # только если ещё нет папки .git в корне
git branch -M main                    # ветка main (не master)
git add .
git commit -m "Initial vetschedule"
git remote add origin https://github.com/ВАШ_ЛОГИН/vetschedule.git
git push -u origin main
```

Если `remote origin already exists` — не добавляйте снова, только `git push -u origin main`.

Если ошибка `src refspec main does not match any` — вы на ветке `master`: выполните `git branch -M main` и снова `git push`.

3. В репозитории должна быть папка `schedule_json/` **внутри** проекта (не отдельный репозиторий).

---

## 1. GitHub Actions — парсер расписания

Файл: `.github/workflows/update-schedule.yml`

### 1.1 Секрет

GitHub → репозиторий → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Имя | Значение |
|-----|----------|
| `SCHEDULE_PDF_URL` | Прямая ссылка на PDF расписания (как в `.env`) |

### 1.2 Права на push

Workflow уже настроен с `permissions: contents: write` — коммитит обновлённые JSON в `main`.

### 1.3 Запуск

- **Автоматически:** по cron (понедельник 05:00 UTC) — при необходимости измените cron в yaml.
- **Вручную:** **Actions** → **Update schedule JSON** → **Run workflow**.

### 1.4 После Actions

На PythonAnywhere нужно подтянуть новые JSON (см. п. 3.5).

---

## 2. Vercel — сайт

### 2.1 Импорт проекта

1. [vercel.com](https://vercel.com) → **Add New** → **Project** → импорт GitHub-репозитория.
2. Framework: **Other** (или оставить авто).
3. Корень репозитория — где лежит `vercel.json`.

### 2.2 Настройки сборки

Vercel подхватит `vercel.json`:

- **Build Command:** `python scripts/inject_api_config.py`
- **Output Directory:** `static`
- **Install Command:** `echo skip` (Python на билде есть для скрипта)

### 2.3 Переменные окружения (обязательно)

**Settings** → **Environment Variables**:

| Переменная | Пример | Зачем |
|------------|--------|--------|
| `API_PUBLIC_URL` | `https://вашлогин.pythonanywhere.com` | Без `/api` — подставляется в `static/config.js` |

Пересоберите деплой после добавления переменной.

### 2.4 Проверка

Откройте `https://ваш-проект.vercel.app` — должны загрузиться группы. Если «Нет связи с API» — неверный `API_PUBLIC_URL` или API на PA не запущен / CORS.

### 2.5 Код редактора на сайте

В `static/index.html` константа `HW_EDITOR_CODE` должна совпадать с `EDITOR_CODE` на PythonAnywhere (по умолчанию `0801`).

---

## 3. PythonAnywhere — API и бот

Нужен аккаунт; для бота 24/7 — платный **Hacker** (Always-on tasks) или периодический перезапуск на бесплатном.

### 3.1 Клонирование

**Consoles** → **Bash**:

```bash
cd ~
git clone https://github.com/ВАШ_ЛОГИН/vetschedule.git
cd vetschedule
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3.2 Переменные окружения

Создайте файл `~/vetschedule/.env` по образцу `.env.example` или задайте в **Web** → **Environment variables** (если используете):

| Переменная | Значение |
|------------|----------|
| `TELEGRAM_TOKEN` | от @BotFather |
| `SITE_URL` | URL Vercel |
| `API_INTERNAL_URL` | `https://ВАШ_ЛОГИН.pythonanywhere.com/api` |
| `CORS_ORIGINS` | URL Vercel |
| `DATABASE_URL` | `sqlite:////home/ВАШ_ЛОГИН/vetschedule/schedule.db` |
| `SCHEDULE_DIR` | `schedule_json` |
| `UPLOADS_DIR` | `uploads` |
| `EDITOR_CODE` | тот же, что на сайте |
| `RELOAD` | `0` |

`SCHEDULE_PDF_URL` на PA **не обязателен** — JSON приходит из GitHub.

### 3.3 Веб-приложение (FastAPI)

1. **Web** → **Add a new web app** → Manual configuration → **Python 3.10**.
2. **Code** → путь к проекту: `/home/ВАШ_ЛОГИН/vetschedule`.
3. **WSGI configuration file** — замените содержимое на:

```python
import sys
from pathlib import Path
path = '/home/ВАШ_ЛОГИН/vetschedule'
if path not in sys.path:
    sys.path.insert(0, path)
from wsgi import application
```

(или скопируйте логику из `wsgi.py` в файл PA).

4. **Virtualenv:** `/home/ВАШ_ЛОГИН/vetschedule/.venv`
5. **Static files** (опционально, если открываете API-домен напрямую):  
   URL `/static` → Directory `.../vetschedule/static`
6. **Reload** веб-приложения.

Проверка: `https://ВАШ_ЛОГИН.pythonanywhere.com/api/groups` → JSON со списком групп.

### 3.4 Telegram-бот

**Tasks** → **Always-on** (Hacker) или **Scheduled**:

```bash
cd /home/ВАШ_ЛОГИН/vetschedule && source .venv/bin/activate && python bot.py
```

Бот ходит в API по `API_INTERNAL_URL`.

### 3.5 Обновление расписания с GitHub

После коммита Actions на PA:

**Tasks** → **Scheduled** (например раз в час):

```bash
cd /home/ВАШ_ЛОГИН/vetschedule && git pull
```

Перезапуск API не нужен — JSON читаются при запросе.

### 3.6 Папки на диске

```bash
mkdir -p ~/vetschedule/uploads
```

Права на запись в `uploads/` и на файл БД SQLite.

---

## 4. Сводка URL и связей

```
[GitHub Actions] --commit--> schedule_json/ в репо
                                |
                                v git pull
[PythonAnywhere API] <-------- schedule_json/
        ^
        | HTTPS /api/*
        |
[Vercel static]  config.js → API_PUBLIC_URL = PA
[Telegram bot]   API_INTERNAL_URL = PA/api
```

---

## 5. Локальная разработка

```bash
cp .env.example .env
# TELEGRAM_TOKEN, при необходимости SCHEDULE_PDF_URL
pip install -r requirements.txt
python run.py
```

Сайт и API: **http://localhost:8000** (раздаётся `static/`).

Редактировать фронт: только **`static/index.html`**.

Опционально `static/config.local.js` (см. `static/config.local.js.example`) для Live Server.

---

## 6. Частые проблемы

| Симптом | Решение |
|---------|---------|
| Failed to fetch на Vercel | Задать `API_PUBLIC_URL`, пересобрать; проверить CORS на PA |
| 403 при отмене пары | `EDITOR_CODE` на PA = `HW_EDITOR_CODE` на сайте |
| Бот не отвечает | Always-on task, токен, `API_INTERNAL_URL` |
| Пустое расписание | `git pull` на PA, файлы в `schedule_json/` |
| CORS error | `CORS_ORIGINS` = точный URL Vercel (с `https://`) |
