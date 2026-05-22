# VetSchedule

Расписание и домашние задания для групп **ВМ.О-ВЕТ.С-22-1…7**: сайт, API и Telegram-бот.

## Продакшен

| Часть | Где |
|-------|-----|
| Сайт + API + бот (webhook) | **Vercel** |
| Обновление `schedule_json/` | **GitHub Actions** |

**Инструкция:** [DEPLOY.md](DEPLOY.md)

## Локально

```bash
pip install -r requirements.txt
cp .env.example .env
python run.py
```

http://localhost:8000 — сайт, API и бот (polling).

## Структура

```
main.py, bot.py, database.py, lesson_overrides.py
schedule_json/     # JSON расписания (в git)
static/index.html  # фронтенд
vercel.json        # деплой Vercel
.github/workflows/ # парсер PDF
```

## Команды бота

`/start`, `/today`, `/tomorrow`, `/week`, `/hw`, `/addhw`, `/cancellesson`
