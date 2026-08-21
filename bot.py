#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот расписания.
Запуск: python bot.py
"""
import logging
import httpx
from datetime import datetime, timedelta

from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from config import config
from schedule_utils import (
    load_group, list_groups, format_day_text, format_week_day_lines,
    today_key, tomorrow_key, current_iso_week, classify_lesson,
    weekday_abbr_ru, clean_subject,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

API_BASE = config.API_INTERNAL_URL or f"http://127.0.0.1:{config.PORT}/api"
SITE_BASE = config.SITE_URL.rstrip("/")
SUPPORT_TELEGRAM_URL = "https://t.me/cc0untN0tAF0und"

# ─── Список предметов ─────────────────────────────────────────────────────────

SUBJECTS = [
    "Организация ветеринарного дела",
    "Ветеринарная токсикология",
    "Акушерство и гинекология животных",
    "Паразитология и инвазионные болезни животных",
    "Эпизоотология и инфекционные болезни животных",
    "Ветеринарно-санитарная экспертиза",
    "Общая и частная хирургия",
    "Биология и патология жвачных",
    "Внутренние незаразные болезни животных",
]

# ─── Флаги (статусы ДЗ временно выключены — поставь True, чтобы вернуть) ─────
HW_STATUS_ENABLED = True
HW_EDITOR_CODE = config.EDITOR_CODE

# Состояния /addhw: сначала код, затем предмет → описание → дедлайн
HW_CODE, HW_SUBJECT, HW_DESCRIPTION, HW_DEADLINE = range(4)
# Состояния отмены пары: код → день → пара
LES_CODE, LES_DAY, LES_PICK = 10, 11, 12


# ─── API helpers ──────────────────────────────────────────────────────────────

async def api_get(path: str, **params) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API_BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()

async def api_post(path: str, json: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{API_BASE}{path}", json=json)
        r.raise_for_status()
        return r.json()

async def api_put(path: str, json: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(f"{API_BASE}{path}", json=json)
        r.raise_for_status()
        return r.json()


# ─── Утилиты ──────────────────────────────────────────────────────────────────

def get_group(ctx):
    return ctx.user_data.get("group")

def set_group(ctx, group: str):
    ctx.user_data["group"] = group

def hw_emoji(status: str) -> str:
    return {"pending": "🔴", "in_progress": "🟡", "done": "✅"}.get(status, "❓")

def hw_status_label(status: str) -> str:
    return {
        "pending": "Не сделано",
        "in_progress": "В работе",
        "done": "Сделано",
    }.get(status, status or "—")

def html_escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def sep_line(char: str = "─", width: int = 16) -> str:
    """Короткая полоса: в Telegram на телефоне длинные строки переносятся."""
    return char * width

def trunc_btn(s: str, max_len: int = 42) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"

def format_hw_line(hw: dict, idx: Optional[int], compact: bool = True) -> str:
    """Строка в общем списке (без полного текста — открывай карточку)."""
    em = hw_emoji(hw["status"]) if HW_STATUS_ENABLED else ""
    subj = html_escape(hw.get("subject") or "—")
    dl = ""
    if hw.get("deadline"):
        try:
            dt = datetime.fromisoformat(hw["deadline"].replace("Z", "+00:00"))
            dl = f" · ⏰ {dt.strftime('%d.%m %H:%M')}"
        except Exception:
            pass
    n_files = len(hw.get("files") or [])
    files_hint = f" · 📎{n_files}" if n_files else ""
    extra = ""
    if not compact:
        desc = (hw.get("description") or "").strip()
        if desc:
            short = html_escape(desc[:72] + ("…" if len(desc) > 72 else ""))
            extra = f"\n   <i>{short}</i>"
    prefix = f"{idx}. " if idx is not None else "• "
    em_part = f"{em} " if em else ""
    return f"{prefix}{em_part}<b>{subj}</b>{dl}{files_hint}{extra}"

def format_hw_card(hw: dict) -> str:
    """Полная карточка для просмотра: описание, файлы (+ статус, если HW_STATUS_ENABLED)."""
    subj = html_escape(hw.get("subject") or "—")
    if HW_STATUS_ENABLED:
        em = hw_emoji(hw["status"])
        st = hw_status_label(hw["status"])
        lines = [
            f"{em} <b>{subj}</b>",
            sep_line(),
            "",
            f"📌 Статус: <b>{html_escape(st)}</b>",
        ]
    else:
        lines = [f"📖 <b>{subj}</b>", sep_line(), ""]
    if hw.get("deadline"):
        try:
            dt = datetime.fromisoformat(hw["deadline"].replace("Z", "+00:00"))
            lines.append(f"⏰ Дедлайн: <b>{dt.strftime('%d.%m.%Y %H:%M')}</b>")
        except Exception:
            pass
    desc = (hw.get("description") or "").strip()
    if desc:
        lines.append("")
        lines.append("📝 <b>Задание</b>")
        lines.append(html_escape(desc))
    files = hw.get("files") or []
    lines.append("")
    if files:
        lines.append("📎 <b>Файлы</b> (нажми для скачивания)")
        base = SITE_BASE
        for f in files:
            fn = html_escape(f.get("filename") or "файл")
            rel = f.get("url") or ""
            url = f"{base}{rel}" if rel.startswith("/") else f"{base}/{rel}"
            lines.append(f"  • <a href=\"{url}\">{fn}</a>")
    else:
        lines.append("<i>Вложений нет</i>")
    lines.append("")
    lines.append(sep_line("·", 14))
    if HW_STATUS_ENABLED:
        lines.append("<i>Ниже можно сменить статус после просмотра.</i>")
    return "\n".join(lines)

def hw_detail_kb(hw_id: int) -> InlineKeyboardMarkup:
    """Кнопки под карточкой ДЗ (статусы — только если HW_STATUS_ENABLED)."""
    back = [InlineKeyboardButton("📋 К списку ДЗ", callback_data="hw_back")]
    if not HW_STATUS_ENABLED:
        return InlineKeyboardMarkup([back])
    rows = [
        [
            InlineKeyboardButton("🔴 Не сделано", callback_data=f"hws:{hw_id}:pending"),
            InlineKeyboardButton("🟡 В работе", callback_data=f"hws:{hw_id}:in_progress"),
        ],
        [
            InlineKeyboardButton("✅ Сделано", callback_data=f"hws:{hw_id}:done"),
        ],
        back,
    ]
    return InlineKeyboardMarkup(rows)

def groups_kb(groups):
    rows = []
    for i in range(0, len(groups), 2):
        rows.append([InlineKeyboardButton(g, callback_data=f"grp:{g}") for g in groups[i:i+2]])
    return InlineKeyboardMarkup(rows)

def subjects_kb():
    rows = []
    for i, s in enumerate(SUBJECTS):
        rows.append([InlineKeyboardButton(s, callback_data=f"hw_subj:{i}")])
    rows.append([InlineKeyboardButton("✏️ Ввести свой предмет", callback_data="hw_subj:custom")])
    return InlineKeyboardMarkup(rows)

def get_date_suggestions(subject: str, group: str) -> list:
    data = load_group(group)
    if not data:
        return []
    lo = subject.lower()
    now_date = datetime.now().date()
    results = []
    for week in data.get("weeks", []):
        for day in week.get("days", []):
            for ls in day.get("lessons", []):
                c = clean_subject(ls["subject"]).lower()
                if lo[:10] in c or c[:10] in lo:
                    d_s, m_s = day["date"].split("/")
                    try:
                        dt = datetime(2026, int(m_s), int(d_s))
                        if dt.date() >= now_date and len(results) < 5:
                            results.append({
                                "date": day["date"],
                                "day_name": day["day_name"],
                                "time": ls["time"],
                            })
                    except ValueError:
                        pass
    return results

def date_suggestions_kb(suggestions: list):
    rows = []
    for s in suggestions:
        hour = s["time"].split("-")[0].split(".")[0]
        label = f"📅 {weekday_abbr_ru(s['day_name'])} {s['date']} ({s['time'].split('-')[0]})"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"hw_date:{s['date']}:{hour}"
        )])
    rows.append([InlineKeyboardButton("✏️ Ввести дату вручную", callback_data="hw_date:manual")])
    rows.append([InlineKeyboardButton("⏭ Пропустить дедлайн",  callback_data="hw_date:skip")])
    return InlineKeyboardMarkup(rows)


# ─── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx):
    user = update.effective_user
    try:
        await api_post("/users", {
            "telegram_id": user.id,
            "name": user.full_name,
            "group_name": get_group(ctx),
        })
    except Exception:
        pass
    hw_line = (
        "Я покажу <b>расписание</b> и список <b>домашних заданий</b> с файлами"
        + (" и статусами" if HW_STATUS_ENABLED else "")
        + "."
    )
    code_hint = "" if HW_STATUS_ENABLED else (
        "\n\n<i>Добавлять задания: /addhw — сначала запросит код доступа.</i>"
    )
    support = (
        f"\n\n💬 Проблемы или вопросы — "
        f"<a href=\"{SUPPORT_TELEGRAM_URL}\">напиши в Telegram</a>."
    )
    await update.message.reply_text(
        f"👋 Привет, <b>{html_escape(user.first_name or 'друг')}</b>!\n"
        f"{sep_line()}\n\n"
        f"{hw_line}{code_hint}{support}\n\n"
        "<i>Шаг 1.</i> Выбери свою группу:",
        parse_mode=ParseMode.HTML,
        reply_markup=groups_kb(list_groups()),
    )

async def cb_group_select(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    group = query.data.split(":", 1)[1]
    set_group(ctx, group)
    try:
        await api_post("/users", {
            "telegram_id": update.effective_user.id,
            "name": update.effective_user.full_name,
            "group_name": group,
        })
    except Exception:
        pass
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📅 Сегодня",    callback_data="do:today"),
        InlineKeyboardButton("📆 Неделя",     callback_data="do:week"),
    ], [
        InlineKeyboardButton("📋 ДЗ",         callback_data="do:hw"),
        InlineKeyboardButton("➕ Добавить ДЗ", callback_data="do:addhw"),
    ], [
        InlineKeyboardButton("❌ Отмена пары", callback_data="do:cancellesson"),
    ]])
    support = (
        f"\n\n💬 <a href=\"{SUPPORT_TELEGRAM_URL}\">Техподдержка в Telegram</a>"
    )
    await query.edit_message_text(
        f"✅ <b>Группа сохранена</b>\n\n"
        f"<b>{html_escape(group)}</b>\n"
        f"{sep_line()}\n\n"
        f"Что показать?{support}",
        parse_mode=ParseMode.HTML, reply_markup=kb,
    )


# ─── /today, /tomorrow ────────────────────────────────────────────────────────

async def _show_day(update: Update, ctx, path: str, label: str):
    group = get_group(ctx)
    if not group:
        await update.effective_message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n"
            "Открой /start и выбери группу.",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        data = await api_get(f"/schedule/{group}{path}")
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Не удалось загрузить расписание</b>\n\n"
            f"<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    if not data.get("day"):
        await update.effective_message.reply_text(
            f"🎉 <b>{html_escape(label.capitalize())}</b>\n\n"
            f"{sep_line()}\n\n"
            "Занятий нет — можно отдохнуть.",
            parse_mode=ParseMode.HTML,
        )
        return
    day_title = {"сегодня": "Сегодня", "завтра": "Завтра"}.get(
        label.lower(), html_escape(label.capitalize())
    )
    body = format_day_text(data["day"]) + "\n" + sep_line("·", 12)
    await update.effective_message.reply_text(
        f"📅 <b>{day_title}</b>\n\n{body}",
        parse_mode=ParseMode.HTML,
    )

async def cmd_today(update: Update, ctx):
    await _show_day(update, ctx, "/today", "сегодня")

async def cmd_tomorrow(update: Update, ctx):
    await _show_day(update, ctx, "/tomorrow", "завтра")


# ─── /schedule, /week ─────────────────────────────────────────────────────────

async def _show_week(update: Update, ctx, week_num=None):
    group = get_group(ctx)
    if not group:
        await update.effective_message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n"
            "Открой /start и выбери группу.",
            parse_mode=ParseMode.HTML,
        )
        return
    if week_num is None:
        week_num = current_iso_week()
    try:
        week = await api_get(f"/schedule/{group}/week/{week_num}")
    except httpx.HTTPStatusError as e:
        msg = (
            f"📭 <b>Неделя {week_num}</b> не найдена в расписании."
            if e.response.status_code == 404
            else f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>"
        )
        await update.effective_message.reply_text(msg, parse_mode=ParseMode.HTML)
        return
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    title = week.get("date_range") or f"Неделя {week_num}"
    lines = [
        f"📆 <b>{html_escape(str(title))}</b>",
        "",
        sep_line(),
        "",
    ]
    for day in week.get("days", []):
        lines.extend(format_week_day_lines(day))
        lines.append("")

    text = "\n".join(lines).rstrip() + "\n" + sep_line("·", 12)
    if len(text) > 4000:
        text = text[:3990] + "\n…"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀ Пред.", callback_data=f"week:{week_num - 1}"),
        InlineKeyboardButton("▶ След.", callback_data=f"week:{week_num + 1}"),
    ]])
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def cmd_schedule(update: Update, ctx):
    await _show_week(update, ctx)

async def cmd_week(update: Update, ctx):
    await _show_week(update, ctx)

async def cb_week_nav(update: Update, ctx):
    await update.callback_query.answer()
    await _show_week(update, ctx, int(update.callback_query.data.split(":")[1]))


# ─── /hw — список ДЗ ──────────────────────────────────────────────────────────

async def _build_hw_list_message(ctx) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура списка ДЗ (group уже проверен)."""
    group = get_group(ctx)
    data = await api_get("/homework", group=group)
    items = data.get("homework", [])

    header = (
        f"📋 <b>Домашние задания</b>\n\n"
        f"<i>{html_escape(group)}</i>"
    )
    header += f"\n{sep_line()}"

    pending = [h for h in items if h["status"] != "done"]
    done = [h for h in items if h["status"] == "done"]

    if not items:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Добавить ДЗ", callback_data="do:addhw")],
        ])
        return (
            f"{header}\n\n"
            "<i>Пока пусто — добавь первое задание.</i>",
            kb,
        )

    if HW_STATUS_ENABLED:
        intro = (
            "Нажми <b>👁 Открыть</b>, чтобы прочитать текст, "
            "скачать файлы и затем выставить статус."
        )
    else:
        intro = "Нажми <b>👁 Открыть</b>, чтобы прочитать текст и скачать файлы."

    lines = [header, "", intro, ""]

    if HW_STATUS_ENABLED:
        if pending:
            lines.append(f"🔔 <b>Актуальные</b> <i>({len(pending)})</i>")
            lines.append("")
            for i, hw in enumerate(pending[:12], 1):
                lines.append(format_hw_line(hw, i))
        if done:
            lines.append("")
            lines.append(f"✅ <b>Выполнено</b> <i>({len(done)})</i>")
            lines.append("")
            for hw in done[:6]:
                lines.append(format_hw_line(hw, None))
    else:
        lines.append(f"📚 <b>Задания</b> <i>({len(items)})</i>")
        lines.append("")
        for i, hw in enumerate(items[:15], 1):
            lines.append(format_hw_line(hw, i))

    kb_rows = []
    if HW_STATUS_ENABLED:
        for hw in pending[:8]:
            kb_rows.append([
                InlineKeyboardButton(
                    f"👁 {trunc_btn(hw.get('subject') or 'ДЗ', 40)}",
                    callback_data=f"hwv:{hw['id']}",
                ),
            ])
        for hw in done[:3]:
            kb_rows.append([
                InlineKeyboardButton(
                    f"✅👁 {trunc_btn(hw.get('subject') or 'ДЗ', 36)}",
                    callback_data=f"hwv:{hw['id']}",
                ),
            ])
    else:
        for hw in items[:10]:
            kb_rows.append([
                InlineKeyboardButton(
                    f"👁 {trunc_btn(hw.get('subject') or 'ДЗ', 40)}",
                    callback_data=f"hwv:{hw['id']}",
                ),
            ])
    kb_rows.append([InlineKeyboardButton("➕ Добавить ДЗ", callback_data="do:addhw")])
    return "\n".join(lines), InlineKeyboardMarkup(kb_rows)


async def _show_hw(update: Update, ctx):
    group = get_group(ctx)
    if not group:
        await update.effective_message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n"
            "Открой /start и выбери группу.",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        text, kb = await _build_hw_list_message(ctx)
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

async def cmd_hw(update: Update, ctx):
    await _show_hw(update, ctx)

async def cb_hw_view(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    hw_id = int(query.data.split(":")[1])
    try:
        hw = await api_get(f"/homework/{hw_id}")
    except Exception:
        await query.answer("Не удалось загрузить задание", show_alert=True)
        return
    g = get_group(ctx)
    if g and hw.get("group_name") != g:
        await query.answer("Это задание относится к другой группе.", show_alert=True)
        return
    await query.message.reply_text(
        format_hw_card(hw),
        parse_mode=ParseMode.HTML,
        reply_markup=hw_detail_kb(hw_id),
        disable_web_page_preview=True,
    )

async def cb_hw_status(update: Update, ctx):
    query = update.callback_query
    if not HW_STATUS_ENABLED:
        await query.answer("Статусы заданий сейчас отключены.", show_alert=True)
        return
    parts = query.data.split(":")
    hw_id = int(parts[1])
    status = parts[2]
    if status not in ("pending", "in_progress", "done"):
        await query.answer()
        return
    try:
        hw = await api_put(f"/homework/{hw_id}", {"status": status})
    except Exception:
        await query.answer("Не удалось сохранить статус", show_alert=True)
        return
    label = hw_status_label(status)
    await query.answer(f"Статус: {label}")
    try:
        await query.edit_message_text(
            format_hw_card(hw),
            parse_mode=ParseMode.HTML,
            reply_markup=hw_detail_kb(hw_id),
            disable_web_page_preview=True,
        )
    except Exception:
        pass

async def cb_hw_back(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    group = get_group(ctx)
    if not group:
        await ctx.bot.send_message(
            chat_id,
            "⚠️ <b>Группа не выбрана</b>\n\n/start",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        await query.message.delete()
    except Exception:
        pass
    try:
        text, kb = await _build_hw_list_message(ctx)
    except Exception as e:
        await ctx.bot.send_message(
            chat_id,
            f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await ctx.bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )

# ─── /addhw ───────────────────────────────────────────────────────────────────

async def cmd_addhw(update: Update, ctx):
    group = get_group(ctx)
    if not group:
        await update.effective_message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n"
            "Сначала открой /start и выбери группу.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    ctx.user_data.pop("hw_draft", None)
    await update.effective_message.reply_text(
        "➕ <b>Новое домашнее задание</b>\n"
        f"{sep_line()}\n\n"
        "Добавлять задания могут только те, у кого есть <b>код</b>.\n\n"
        f"Отправь код одним сообщением ({len(HW_EDITOR_CODE)} цифры) или /cancel",
        parse_mode=ParseMode.HTML,
    )
    return HW_CODE


async def hw_check_editor_code(update: Update, ctx):
    if update.message.text.strip() != HW_EDITOR_CODE:
        await update.message.reply_text(
            "❌ <b>Неверный код.</b>\n\n"
            "Попробуй снова: /addhw",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    group = get_group(ctx)
    if not group:
        await update.message.reply_text(
            "⚠️ <b>Группа не выбрана.</b>\n\n"
            "Сначала открой /start и выбери группу.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    ctx.user_data["hw_draft"] = {"group_name": group, "created_by_tg": update.effective_user.id}
    await update.message.reply_text(
        "✅ Код принят.\n"
        f"{sep_line()}\n\n"
        "Выбери предмет из списка или введи свой текстом:",
        parse_mode=ParseMode.HTML,
        reply_markup=subjects_kb(),
    )
    return HW_SUBJECT

async def cb_subject_pick(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    val = query.data.split(":", 1)[1]
    if val == "custom":
        await query.message.reply_text(
            "✏️ <b>Свой предмет</b>\n\n"
            "Введи название предмета одним сообщением:",
            parse_mode=ParseMode.HTML,
        )
        return HW_SUBJECT
    try:
        subject = SUBJECTS[int(val)]
    except (ValueError, IndexError):
        await query.message.reply_text(
            "❌ <b>Ошибка</b>\n\n"
            "Попробуй ещё раз или отправь название текстом.",
            parse_mode=ParseMode.HTML,
        )
        return HW_SUBJECT
    ctx.user_data["hw_draft"]["subject"] = subject
    await query.message.reply_text(
        f"📚 Предмет: <b>{html_escape(subject)}</b>\n{sep_line()}\n\n"
        "📝 Опиши задание одним сообщением или отправь <code>/skip</code>, "
        "если достаточно только названия:",
        parse_mode=ParseMode.HTML,
    )
    return HW_DESCRIPTION

async def hw_get_subject(update: Update, ctx):
    text = update.message.text.strip()
    lo = text.lower()
    match = next((s for s in SUBJECTS if lo in s.lower() or s.lower()[:12] in lo), None)
    subject = match or text
    ctx.user_data["hw_draft"]["subject"] = subject
    if match and match != text:
        await update.message.reply_text(
            f"✅ Похоже на: <b>{html_escape(match)}</b>\n\n"
            "<i>Если всё верно — опиши задание следующим сообщением.</i>",
            parse_mode=ParseMode.HTML,
        )
    await update.message.reply_text(
        f"📚 Предмет: <b>{html_escape(subject)}</b>\n{sep_line()}\n\n"
        "📝 Опиши задание или <code>/skip</code>:",
        parse_mode=ParseMode.HTML,
    )
    return HW_DESCRIPTION

async def hw_get_description(update: Update, ctx):
    text = update.message.text.strip()
    if text.lower() != "/skip":
        ctx.user_data["hw_draft"]["description"] = text

    subject = ctx.user_data["hw_draft"].get("subject", "")
    group   = ctx.user_data["hw_draft"].get("group_name", "")
    suggestions = get_date_suggestions(subject, group)

    if suggestions:
        await update.message.reply_text(
            "⏰ <b>Дедлайн</b>\n"
            f"{sep_line()}\n\n"
            "Ниже — ближайшие занятия по этому предмету.\n\n"
            "Выбери дату кнопкой или введи вручную:",
            parse_mode=ParseMode.HTML,
            reply_markup=date_suggestions_kb(suggestions),
        )
    else:
        await update.message.reply_text(
            "⏰ <b>Дедлайн</b>\n"
            f"{sep_line()}\n\n"
            "Введи дату в одном из форматов:\n"
            "• <code>ДД.ММ.ГГГГ</code>\n"
            "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Или отправь <code>/skip</code>.",
            parse_mode=ParseMode.HTML,
        )
    return HW_DEADLINE

async def cb_date_pick(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")  # hw_date:DD/MM:HH  |  hw_date:manual  |  hw_date:skip

    if parts[1] == "skip":
        await query.message.reply_text(
            "⏭ <b>Дедлайн не указан</b>\n\n"
            "Сохраняю задание без срока…",
            parse_mode=ParseMode.HTML,
        )
        return await _save_hw(query.message, ctx)

    if parts[1] == "manual":
        await query.message.reply_text(
            "✏️ <b>Дата вручную</b>\n\n"
            "Формат: <code>ДД.ММ.ГГГГ</code> или <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
            parse_mode=ParseMode.HTML,
        )
        return HW_DEADLINE

    try:
        d, m = parts[1].split("/")
        hour = parts[2] if len(parts) > 2 else "08"
        dl_iso = f"2026-{m.zfill(2)}-{d.zfill(2)}T{hour.zfill(2)}:00"
        ctx.user_data["hw_draft"]["deadline"] = dl_iso
        dt = datetime.fromisoformat(dl_iso)
        await query.message.reply_text(
            f"📅 <b>Дедлайн задан</b>\n\n"
            f"⏰ <b>{dt.strftime('%d.%m.%Y %H:%M')}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await query.message.reply_text(
            "❌ <b>Ошибка даты</b>\n\n"
            "Дедлайн не установлен. Задание сохранится без даты.",
            parse_mode=ParseMode.HTML,
        )

    return await _save_hw(query.message, ctx)

async def hw_get_deadline(update: Update, ctx):
    text = update.message.text.strip()
    if text.lower() == "/skip":
        return await _save_hw(update.message, ctx)
    dt = None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(text, fmt); break
        except ValueError:
            pass
    if dt is None:
        await update.message.reply_text(
            "❌ <b>Формат даты</b>\n\n"
            "Нужно: <code>ДД.ММ.ГГГГ</code> или <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Или отправь <code>/skip</code>.",
            parse_mode=ParseMode.HTML,
        )
        return HW_DEADLINE
    ctx.user_data["hw_draft"]["deadline"] = dt.strftime("%Y-%m-%d %H:%M:%S")
    return await _save_hw(update.message, ctx)

async def _save_hw(message, ctx):
    draft = ctx.user_data.get("hw_draft", {})
    try:
        hw = await api_post("/homework", draft)
        dl_str = "—"
        if hw.get("deadline"):
            try:
                dl_str = datetime.fromisoformat(hw["deadline"]).strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass
        desc = html_escape((hw.get("description") or "—").strip() or "—")
        subj = html_escape(hw.get("subject") or "—")
        await message.reply_text(
            f"✅ <b>Задание сохранено</b>\n"
            f"{sep_line()}\n\n"
            f"📚 <b>{subj}</b>\n\n"
            f"📝 {desc}\n\n"
            f"⏰ <b>Дедлайн:</b> {html_escape(dl_str)}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Открыть список ДЗ", callback_data="do:hw"),
                InlineKeyboardButton("➕ Ещё одно", callback_data="do:addhw"),
            ]]),
        )
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Не сохранилось</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
    ctx.user_data.pop("hw_draft", None)
    return ConversationHandler.END

async def hw_cancel(update: Update, ctx):
    ctx.user_data.pop("hw_draft", None)
    await update.message.reply_text(
        "🚫 <b>Добавление отменено</b>\n\n"
        "Можно начать снова: /addhw",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ─── Отмена пары (код → день → пара) ─────────────────────────────────────────

async def _cancellesson_prompt_code(target):
    await target.reply_text(
        "❌ <b>Отмена / возврат пары</b>\n"
        f"{sep_line()}\n\n"
        "Если пару отменили, но PDF не обновили — отметьте здесь.\n"
        "Повторное нажатие по той же паре <b>снимает</b> отмену.\n\n"
        f"Отправь код ({len(config.EDITOR_CODE)} цифры) или /cancel",
        parse_mode=ParseMode.HTML,
    )


async def cmd_cancellesson(update: Update, ctx):
    group = get_group(ctx)
    if not group:
        await update.effective_message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n/start",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    await _cancellesson_prompt_code(update.effective_message)
    return LES_CODE


async def cb_cancellesson_start(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    group = get_group(ctx)
    if not group:
        await query.message.reply_text(
            "⚠️ <b>Группа не выбрана</b>\n\n/start",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    await _cancellesson_prompt_code(query.message)
    return LES_CODE


async def cancel_check_code(update: Update, ctx):
    if update.message.text.strip() != config.EDITOR_CODE:
        await update.message.reply_text(
            "❌ <b>Неверный код.</b>\n\n/cancellesson — попробовать снова",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    ctx.user_data["editor_code"] = config.EDITOR_CODE
    return await cancel_show_day_menu(update, ctx)


def _cancel_date_cb(day_date: str) -> str:
    """15/05 → cday:15_05 (callback_data ≤ 64 байт)."""
    return f"cday:{day_date.replace('/', '_')}"


def _cancel_date_from_cb(data: str) -> str:
    return data.split(":", 1)[1].replace("_", "/")


async def cancel_show_day_menu(update: Update, ctx):
    group = get_group(ctx)
    week_num = current_iso_week()
    try:
        week = await api_get(f"/schedule/{group}/week/{week_num}")
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    ctx.user_data["cancel_week"] = week
    ctx.user_data["cancel_week_num"] = week_num
    rows = [
        [
            InlineKeyboardButton("📅 Сегодня", callback_data="cday:t"),
            InlineKeyboardButton("📆 Завтра", callback_data="cday:tm"),
        ],
    ]
    for day in week.get("days", []):
        if not day.get("lessons"):
            continue
        d = day.get("date") or ""
        name = weekday_abbr_ru(day.get("day_name") or "") or d
        n_lessons = len(day["lessons"])
        n_cancel = sum(1 for ls in day["lessons"] if ls.get("cancelled"))
        mark = f" ({n_cancel}❌)" if n_cancel else ""
        rows.append([
            InlineKeyboardButton(
                f"{name} {d} · {n_lessons}{mark}",
                callback_data=_cancel_date_cb(d),
            ),
        ])
    if len(rows) == 1:
        await update.effective_message.reply_text(
            "📭 <b>На этой неделе нет занятий</b>\n\n"
            "Попробуй на сайте или другую неделю позже.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    rows.append([InlineKeyboardButton("🚫 Отмена", callback_data="cday:abort")])
    wr = week.get("date_range") or f"неделя {week_num}"
    await update.effective_message.reply_text(
        f"📅 <b>Выбери день</b>\n"
        f"{sep_line()}\n\n"
        f"<i>{html_escape(wr)}</i>\n\n"
        "Сегодня / завтра — быстрые кнопки; ниже — все дни недели с парами.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return LES_DAY


async def cancel_pick_day(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    if query.data == "cday:abort":
        await query.message.reply_text("🚫 Отменено.", parse_mode=ParseMode.HTML)
        ctx.user_data.pop("cancel_week", None)
        return ConversationHandler.END
    group = get_group(ctx)
    day = None
    try:
        if query.data == "cday:t":
            data = await api_get(f"/schedule/{group}/today")
            day = data.get("day")
        elif query.data == "cday:tm":
            data = await api_get(f"/schedule/{group}/tomorrow")
            day = data.get("day")
        else:
            date_key = _cancel_date_from_cb(query.data)
            week = ctx.user_data.get("cancel_week")
            if week:
                for d in week.get("days", []):
                    if d.get("date") == date_key:
                        day = d
                        break
            if day is None:
                week_num = ctx.user_data.get("cancel_week_num") or current_iso_week()
                week = await api_get(f"/schedule/{group}/week/{week_num}")
                ctx.user_data["cancel_week"] = week
                for d in week.get("days", []):
                    if d.get("date") == date_key:
                        day = d
                        break
    except Exception as e:
        await query.message.reply_text(
            f"❌ <b>Ошибка</b>\n\n<code>{html_escape(str(e))}</code>",
            parse_mode=ParseMode.HTML,
        )
        return LES_DAY
    if not day or not day.get("lessons"):
        await query.message.reply_text(
            "📭 <b>На этот день занятий нет</b>\n\nВыбери другой день.",
            parse_mode=ParseMode.HTML,
        )
        return LES_DAY
    return await cancel_show_lessons(query.message, ctx, day)


async def cancel_show_lessons(message, ctx, day: dict):
    lessons = []
    for ls in day["lessons"]:
        lessons.append({
            "day_date": day["date"],
            "time": ls.get("time") or "",
            "subject": ls.get("subject") or "",
            "cancelled": bool(ls.get("cancelled")),
        })
    ctx.user_data["cancel_lessons"] = lessons
    rows = []
    for i, ls in enumerate(lessons[:12]):
        subj = clean_subject(ls["subject"])[:32]
        mark = "↩" if ls["cancelled"] else "❌"
        rows.append([
            InlineKeyboardButton(
                f"{mark} {ls['time']} {subj}",
                callback_data=f"cles:{i}",
            ),
        ])
    rows.append([InlineKeyboardButton("◀️ Другой день", callback_data="cles:back")])
    rows.append([InlineKeyboardButton("🚫 Отмена", callback_data="cles:abort")])
    day_title = html_escape(day.get("day_name") or "")
    day_date = html_escape(day.get("date") or "")
    await message.reply_text(
        f"📅 <b>{day_title}, {day_date}</b>\n\n"
        "Нажми пару, чтобы <b>переключить</b> отмену (❌ отменить / ↩ вернуть):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return LES_PICK


async def cancel_pick_lesson(update: Update, ctx):
    query = update.callback_query
    await query.answer()
    if query.data == "cles:back":
        return await cancel_show_day_menu(update, ctx)
    if query.data == "cles:abort":
        await query.message.reply_text("🚫 Отменено.", parse_mode=ParseMode.HTML)
        ctx.user_data.pop("cancel_lessons", None)
        return ConversationHandler.END
    try:
        idx = int(query.data.split(":")[1])
    except ValueError:
        return LES_PICK
    lessons = ctx.user_data.get("cancel_lessons") or []
    if idx < 0 or idx >= len(lessons):
        await query.answer("Устаревшая кнопка", show_alert=True)
        return ConversationHandler.END
    ls = lessons[idx]
    code = ctx.user_data.get("editor_code") or config.EDITOR_CODE
    try:
        result = await api_post("/lesson-overrides/toggle", {
            "editor_code": code,
            "group_name": get_group(ctx),
            "day_date": ls["day_date"],
            "time": ls["time"],
            "subject": ls["subject"],
        })
    except Exception:
        await query.message.reply_text(
            "❌ Не удалось сохранить. Попробуй на сайте.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END
    if result.get("cancelled"):
        msg = "✅ Пара отмечена как <b>ОТМЕНЕНА</b>."
    else:
        msg = "↩ Отмена снята, пара снова <b>в расписании</b>."
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
    ctx.user_data.pop("cancel_lessons", None)
    ctx.user_data.pop("editor_code", None)
    return ConversationHandler.END


async def cancellesson_end(update: Update, ctx):
    ctx.user_data.pop("cancel_lessons", None)
    ctx.user_data.pop("cancel_week", None)
    ctx.user_data.pop("cancel_week_num", None)
    ctx.user_data.pop("editor_code", None)
    await update.message.reply_text(
        "🚫 <b>Отменено</b>",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ─── Callback router ──────────────────────────────────────────────────────────

async def cb_router(update: Update, ctx):
    query = update.callback_query
    data  = query.data
    if data == "do:today":
        await query.answer(); await cmd_today(update, ctx)
    elif data == "do:week":
        await query.answer(); await _show_week(update, ctx)
    elif data == "do:hw":
        await query.answer(); await _show_hw(update, ctx)
    elif data == "do:addhw":
        await query.answer(); await cmd_addhw(update, ctx)


# ─── Напоминания о дедлайнах ──────────────────────────────────────────────────

async def send_deadline_reminders(app):
    if not HW_STATUS_ENABLED:
        return
    from database import SessionLocal, Homework, User
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    db = SessionLocal()
    try:
        # Дедлайны в БД хранятся как введённые студентом — по местному времени
        # колледжа (Asia/Novosibirsk), не в UTC. Поэтому и "сейчас" берём в той
        # же таймзоне, а не utcnow() — иначе сравнение сдвинуто на несколько часов.
        now       = _dt.now(ZoneInfo(config.APP_TIMEZONE)).replace(tzinfo=None)
        threshold = now + timedelta(hours=config.NOTIFY_BEFORE_HOURS)
        items = (
            db.query(Homework)
            .filter(
                Homework.deadline >= now,
                Homework.deadline <= threshold,
                Homework.status   != "done",
                Homework.notified == False,
            ).all()
        )
        for hw in items:
            for user in db.query(User).filter(User.group_name == hw.group_name).all():
                if not user.telegram_id:
                    continue
                try:
                    dl = hw.deadline.strftime("%d.%m.%Y %H:%M")
                    await app.bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            f"⏰ <b>Скоро дедлайн</b>\n"
                            f"{sep_line()}\n\n"
                            f"📚 <b>{html_escape(hw.subject or '')}</b>\n\n"
                            f"📝 {html_escape((hw.description or '—').strip() or '—')}\n\n"
                            f"⏰ <b>Срок:</b> {html_escape(dl)}\n\n"
                            "<i>Открой /hw → 👁 Открыть, чтобы посмотреть файлы и отметить статус.</i>"
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e:
                    log.warning(f"Не удалось уведомить {user.telegram_id}: {e}")
            hw.notified = True
        db.commit()
    finally:
        db.close()


# ─── Сборка Application (polling локально / webhook на Vercel) ───────────────

_ptb_app: Optional[Application] = None
_ptb_ready = False


def build_application() -> Application:
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан")

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    cancellesson_conv = ConversationHandler(
        entry_points=[
            CommandHandler("cancellesson", cmd_cancellesson),
            CallbackQueryHandler(cb_cancellesson_start, pattern="^do:cancellesson$"),
        ],
        states={
            LES_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_check_code),
            ],
            LES_DAY: [
                CallbackQueryHandler(cancel_pick_day, pattern=r"^cday:"),
            ],
            LES_PICK: [
                CallbackQueryHandler(cancel_pick_lesson, pattern=r"^cles:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancellesson_end)],
        allow_reentry=True,
        per_message=True,
    )

    addhw_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addhw", cmd_addhw),
            CallbackQueryHandler(cmd_addhw, pattern="^do:addhw$"),
        ],
        states={
            HW_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, hw_check_editor_code),
            ],
            HW_SUBJECT: [
                CallbackQueryHandler(cb_subject_pick, pattern=r"^hw_subj:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, hw_get_subject),
            ],
            HW_DESCRIPTION: [
                MessageHandler(filters.TEXT, hw_get_description),
            ],
            HW_DEADLINE: [
                CallbackQueryHandler(cb_date_pick, pattern=r"^hw_date:"),
                MessageHandler(filters.TEXT, hw_get_deadline),
            ],
        },
        fallbacks=[CommandHandler("cancel", hw_cancel)],
        allow_reentry=True,
        per_message=True,
    )

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("today",    cmd_today))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("week",     cmd_week))
    app.add_handler(CommandHandler("hw",       cmd_hw))
    app.add_handler(addhw_conv)
    app.add_handler(cancellesson_conv)
    app.add_handler(CallbackQueryHandler(cb_group_select, pattern=r"^grp:"))
    app.add_handler(CallbackQueryHandler(cb_week_nav,     pattern=r"^week:"))
    app.add_handler(CallbackQueryHandler(cb_hw_back,      pattern=r"^hw_back$"))
    app.add_handler(CallbackQueryHandler(cb_hw_status,     pattern=r"^hws:\d+:(?:pending|in_progress|done)$"))
    app.add_handler(CallbackQueryHandler(cb_hw_view,      pattern=r"^hwv:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_router,       pattern=r"^do:"))

    if config.TELEGRAM_MODE == "polling" and not config.IS_VERCEL:
        app.job_queue.run_repeating(
            lambda _: send_deadline_reminders(app),
            interval=1800, first=60,
        )

    return app


async def get_ptb_application() -> Application:
    global _ptb_app, _ptb_ready
    if _ptb_app is None:
        _ptb_app = build_application()
    if not _ptb_ready:
        await _ptb_app.initialize()
        await _ptb_app.start()
        _ptb_ready = True
    return _ptb_app


async def process_webhook_update(payload: dict) -> None:
    ptb = await get_ptb_application()
    update = Update.de_json(payload, ptb.bot)
    await ptb.process_update(update)


async def notify_new_homework(hw_id: int) -> None:
    """Уведомляет в Telegram студентов группы о новом ДЗ. Вызывается фоново
    из /api/homework (POST) — не блокирует ответ API. Создателю (если он
    добавлял через бота) сообщение не дублируется — он уже видит подтверждение."""
    if not config.TELEGRAM_TOKEN:
        return
    from database import SessionLocal, Homework, User
    db = SessionLocal()
    try:
        hw = db.get(Homework, hw_id)
        if not hw:
            return
        creator_tg = None
        if hw.created_by:
            creator = db.get(User, hw.created_by)
            if creator:
                creator_tg = creator.telegram_id
        users = db.query(User).filter(
            User.group_name == hw.group_name, User.telegram_id.isnot(None)
        ).all()
        if not users:
            return
        dl_str = hw.deadline.strftime("%d.%m.%Y %H:%M") if hw.deadline else "—"
        subj = html_escape(hw.subject or "—")
        desc = html_escape((hw.description or "—").strip() or "—")
        text = (
            f"📚 <b>Новое задание</b>\n"
            f"{sep_line()}\n\n"
            f"<b>{subj}</b>\n\n"
            f"📝 {desc}\n\n"
            f"⏰ <b>Дедлайн:</b> {html_escape(dl_str)}"
        )
        ptb = await get_ptb_application()
        for user in users:
            if creator_tg and user.telegram_id == creator_tg:
                continue  # создатель уже получил подтверждение в самом боте
            try:
                await ptb.bot.send_message(chat_id=user.telegram_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("Не удалось уведомить %s: %s", user.telegram_id, e)
    finally:
        db.close()


async def notify_lesson_override(group_name: str, day_date: str, time: str, subject: str,
                                   cancelled: bool, note: Optional[str] = None) -> None:
    """Уведомляет в Telegram всех студентов группы об отмене/восстановлении пары.
    Вызывается фоново из /api/lesson-overrides/toggle — не блокирует ответ API."""
    if not config.TELEGRAM_TOKEN:
        return
    from database import SessionLocal, User
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.group_name == group_name, User.telegram_id.isnot(None)
        ).all()
        if not users:
            return
        ptb = await get_ptb_application()
        if cancelled:
            text = f"🚫 <b>Пара отменена</b>\n{day_date}, {time} — {subject}"
            if note:
                text += f"\n<i>{note}</i>"
        else:
            text = f"✅ <b>Отмена снята</b>\n{day_date}, {time} — {subject}"
        for user in users:
            try:
                await ptb.bot.send_message(chat_id=user.telegram_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as e:
                log.warning("Не удалось уведомить %s: %s", user.telegram_id, e)
    finally:
        db.close()


async def run_reminders_once() -> None:
    """Разовый прогон напоминаний о дедлайнах — вызывается из /api/cron/reminders.

    В webhook-режиме (Vercel) нет постоянного процесса, поэтому job_queue не
    работает: см. build_application(). Вместо этого внешний cron дёргает
    HTTP-эндпоинт с нужным интервалом, а тот вызывает эту функцию.
    """
    ptb = await get_ptb_application()
    await send_deadline_reminders(ptb)


async def register_webhook() -> str:
    ptb = await get_ptb_application()
    base = config.SITE_URL.rstrip("/")
    url = f"{base}/api/telegram/webhook"
    await ptb.bot.set_webhook(url=url, allowed_updates=Update.ALL_TYPES)
    log.info("Webhook установлен: %s", url)
    return url


def main():
    if not config.TELEGRAM_TOKEN:
        log.error("TELEGRAM_TOKEN не задан! Укажи его в .env или переменной окружения.")
        return
    if config.TELEGRAM_MODE == "webhook":
        log.error(
            "TELEGRAM_MODE=webhook: запускайте API (uvicorn/run.py) и вызовите "
            "GET /api/telegram/setup-webhook?secret=CRON_SECRET"
        )
        return

    app = build_application()
    log.info("Бот запущен (polling). Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
