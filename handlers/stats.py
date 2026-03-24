from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.queries import get_leaderboard_by_count, get_leaderboard_by_percent, get_user_stats

router = Router()


def _display_name(row: dict) -> str:
    username = (row.get("username") or "").strip()
    if username:
        return f"@{username}"
    return f"id{row['user_id']}"


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu")]
    ])


def leaderboard_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="По количеству", callback_data="lb_count"),
            InlineKeyboardButton(text="По проценту", callback_data="lb_pct"),
        ],
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu")],
    ])


def leaderboard_result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="По количеству", callback_data="lb_count"),
            InlineKeyboardButton(text="По проценту", callback_data="lb_pct"),
        ],
        [InlineKeyboardButton(text="‹ Назад", callback_data="leaderboard")],
    ])


@router.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    user_id = callback.from_user.id
    async with session_factory() as session:
        s = await get_user_stats(session, user_id)

    text = (
        "<b>Твой прогресс</b>\n\n"
        f"Ответов сегодня: <b>{s['answers_today']}</b>\n"
        f"Всего ответов: <b>{s['total_answers']}</b>\n"
        f"Правильных: <b>{s['total_correct']}</b> ({s['correct_pct']}%)\n"
        f"Слов изучено: <b>{s['words_studied']}</b>\n"
        f"Слов к повторению сегодня: <b>{s['words_due']}</b>"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "leaderboard")
async def cb_leaderboard(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "<b>Лидерборд</b>\n\nВыбери тип:", reply_markup=leaderboard_type_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "lb_count")
async def cb_lb_count(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        rows = await get_leaderboard_by_count(session)

    if not rows:
        text = "<b>Лидерборд (по количеству)</b>\n\nПока нет данных."
    else:
        lines = ["<b>Лидерборд — по количеству правильных ответов</b>\n"]
        for i, r in enumerate(rows, 1):
            name = _display_name(r)
            lines.append(f"{i}. {name} — {r['correct']}")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=leaderboard_result_kb())
    await callback.answer()


@router.callback_query(F.data == "lb_pct")
async def cb_lb_pct(callback: CallbackQuery, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        rows = await get_leaderboard_by_percent(session)

    if not rows:
        text = "<b>Лидерборд (по проценту)</b>\n\nПока нет данных. Нужно минимум 50 ответов."
    else:
        lines = ["<b>Лидерборд — по проценту правильных ответов</b>\n<i>(мин. 50 ответов)</i>\n"]
        for i, r in enumerate(rows, 1):
            name = _display_name(r)
            lines.append(f"{i}. {name} — {r['pct']}% ({r['total']} ответов)")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=leaderboard_result_kb())
    await callback.answer()
