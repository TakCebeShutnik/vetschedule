# -*- coding: utf-8 -*-
"""
Тесты для «чистых» функций-утилит schedule_parser.py — тех, что не требуют
реального PDF/DOCX (парсинг дат, времени, недель). Запуск: pytest tests/

Это не защищает от ЛЮБОЙ поломки парсера (реальную структуру PDF колледжа
не воспроизвести без самого файла), но ловит регрессии в логике, которая
уже один раз ломалась и чинилась: переход через день/месяц/год, сортировка
пар по времени, склейка диапазона дат недели.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schedule_parser import (
    clean_text, parse_day_date, time_slot_index, should_advance_day,
    advance_weekday, date_range_str, infer_year, build_week_number,
    group_by_weeks, GROUPS,
)


def test_clean_text_strips_and_collapses_whitespace():
    assert clean_text("  Организация   ветеринарного \n дела  ") == "Организация ветеринарного дела"
    assert clean_text("") == ""


def test_parse_day_date_valid():
    assert parse_day_date("ВТР 7/04") == ("ВТР", 7, 4)
    assert parse_day_date("  ПНД 11/05  ") == ("ПНД", 11, 5)


def test_parse_day_date_invalid_returns_none():
    assert parse_day_date("что-то не то") is None
    assert parse_day_date("") is None
    assert parse_day_date("09.00-10.30") is None  # это время, не дата


def test_time_slot_index_known_and_unknown():
    assert time_slot_index("09.00-10.30") == 0
    assert time_slot_index("16.15-17.45") == 4
    assert time_slot_index("") == -1
    assert time_slot_index("случайный текст") == -1


def test_should_advance_day_detects_wraparound():
    # 16.15 -> 09.00 на следующей строке = перешли на новый день (после разрыва страницы)
    assert should_advance_day("16.15-17.45", "09.00-10.30") is True
    # обычный порядок в течение одного дня — не переход
    assert should_advance_day("09.00-10.30", "10.45-12.15") is False
    # неизвестные слоты — не считаем переходом (fail-safe, не плодим лишние дни)
    assert should_advance_day("", "09.00-10.30") is False


def test_advance_weekday_simple_next_day():
    abbr, day_n, month_n = advance_weekday("ВТР", 7, 4, year=2026)
    assert (abbr, day_n, month_n) == ("СРД", 8, 4)


def test_advance_weekday_skips_weekend():
    # пятница 2026-04-10 -> следующий учебный день должен быть понедельник, не суббота
    abbr, day_n, month_n = advance_weekday("ПТН", 10, 4, year=2026)
    assert abbr == "ПНД"
    assert (day_n, month_n) == (13, 4)


def test_advance_weekday_crosses_month_boundary():
    abbr, day_n, month_n = advance_weekday("ПТН", 30, 4, year=2026)
    assert (day_n, month_n) == (1, 5)


def test_date_range_str_same_month():
    assert date_range_str([(7, 4), (8, 4), (10, 4)], year=2026) == "7–10 апреля 2026"


def test_date_range_str_crosses_month():
    result = date_range_str([(30, 4), (1, 5)], year=2026)
    assert "апреля" in result and "мая" in result


def test_date_range_str_empty_input():
    assert date_range_str([], year=2026) == ""


def test_infer_year_rolls_over_at_december_to_january():
    assert infer_year(month_n=1, prev_month=12, year=2026) == 2027


def test_infer_year_stays_same_for_normal_progression():
    assert infer_year(month_n=5, prev_month=4, year=2026) == 2026


def test_build_week_number_matches_iso_calendar():
    import datetime
    assert build_week_number(7, 4, year=2026) == datetime.date(2026, 4, 7).isocalendar()[1]


def test_build_week_number_invalid_date_returns_zero():
    assert build_week_number(31, 2, year=2026) == 0  # 31 февраля не существует


def test_group_by_weeks_sorts_lessons_and_builds_date_range():
    """Регрессия на саму сборку недели: две пары одного дня в БД-порядке идут
    не по времени — group_by_weeks должен сохранить их как есть (сортировка
    по времени происходит позже, в export_to_json), но date_range обязан
    покрыть все дни недели."""
    lesson_a = {"subject": "Химия", "teacher": "Иванов И.И.", "room": "101"}
    all_rows_data = [
        ("ВТР", 7, 4, "09.00-10.30", [lesson_a] + [None] * (len(GROUPS) - 1)),
        ("СРД", 8, 4, "10.45-12.15", [lesson_a] + [None] * (len(GROUPS) - 1)),
    ]
    grouped = group_by_weeks(all_rows_data, base_year=2026)
    g1 = grouped[GROUPS[0]]
    assert len(g1) == 1  # обе даты попадают в одну и ту же неделю
    week = next(iter(g1.values()))
    assert set(week["days"].keys()) == {"7/04", "8/04"}
    assert "апреля 2026" in week["date_range"]
    # у групп, для которых пары не было (None), запись отсутствует
    for other_group in GROUPS[1:]:
        assert grouped[other_group] == {}
