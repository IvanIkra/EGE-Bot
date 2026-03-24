import logging
from typing import Optional

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.queries import (
    get_next_word,
    get_or_create_user,
    get_progress,
    record_answer,
    upsert_progress,
)
from db.models import Word
from services.sm2 import sm2_update

logger = logging.getLogger(__name__)
router = Router()

TASK_NUMBERS = list(range(9, 16))


class PracticeState(StatesGroup):
    idle = State()
    waiting_answer = State()


# ── Keyboards ────────────────────────────────────────────────────────────────

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✦ Практика", callback_data="practice")],
        [InlineKeyboardButton(text="◔ Прогресс", callback_data="stats")],
        [InlineKeyboardButton(text="◈ Рейтинг", callback_data="leaderboard")],
    ])


def task_select_kb() -> InlineKeyboardMarkup:
    task_buttons = [
        InlineKeyboardButton(text=str(n), callback_data=f"task:{n}")
        for n in TASK_NUMBERS
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Все задания", callback_data="task:0")],
        task_buttons,
        [InlineKeyboardButton(text="‹ Назад", callback_data="menu")],
    ])


def choice_kb(options: list[str], word_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=opt, callback_data=f"ans:{word_id}:{opt}")
        for opt in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="‹ Назад", callback_data="back_to_tasks")],
    ])


def input_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹ Назад", callback_data="back_to_tasks")],
    ])


def next_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="› Далее", callback_data="next_question")],
        [InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")],
    ])


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        await get_or_create_user(session, message.from_user.id, message.from_user.username)

    await state.set_state(PracticeState.idle)
    await message.answer("Привет! Я помогу тебе подготовиться к ЕГЭ по русскому языку.\nВыбери действие:", reply_markup=main_menu_kb())


# ── Menu ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PracticeState.idle)
    await callback.message.edit_text("Выбери действие:", reply_markup=main_menu_kb())
    await callback.answer()


# ── Practice: выбор задания ───────────────────────────────────────────────────

@router.callback_query(F.data == "practice")
async def cb_practice(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PracticeState.idle)
    await callback.message.edit_text("Выбери задание:", reply_markup=task_select_kb())
    await callback.answer()


@router.callback_query(F.data == "back_to_tasks")
async def cb_back_to_tasks(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PracticeState.idle)
    await callback.message.edit_text("Выбери задание:", reply_markup=task_select_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("task:"))
async def cb_task_select(callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker) -> None:
    task_number = int(callback.data.split(":")[1])
    await state.update_data(task_filter=task_number or None)
    await send_question(callback, state, session_factory, edit=True)
    await callback.answer()


@router.callback_query(F.data == "next_question")
async def cb_next_question(callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker) -> None:
    await send_question(callback, state, session_factory, edit=True)
    await callback.answer()


# ── Отправка вопроса ──────────────────────────────────────────────────────────

async def send_question(
    target: Message | CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker,
    edit: bool = False,
) -> None:
    msg = target if isinstance(target, Message) else target.message
    user_id = target.from_user.id

    data = await state.get_data()
    task_filter: Optional[int] = data.get("task_filter")

    async with session_factory() as session:
        word: Optional[Word] = await get_next_word(session, user_id, task_filter)

    if word is None:
        text = "Все слова выучены! Загляни позже."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="‹ Назад", callback_data="practice")],
            [InlineKeyboardButton(text="⌂ Главное меню", callback_data="menu")],
        ])
        if edit:
            await msg.edit_text(text, reply_markup=kb)
        else:
            await msg.answer(text, reply_markup=kb)
        await state.set_state(PracticeState.idle)
        return

    await state.set_state(PracticeState.waiting_answer)
    await state.update_data(word_id=word.id, question_type=word.question_type, attempts=0)

    task_label = f"Задание {word.task_number}"

    if word.question_type == "choice" and word.options:
        question_text = f"<b>{task_label}</b>\n\nВыберите вариант:\n\n<code>{word.display}</code>"
        kb = choice_kb(word.options, word.id)
    else:
        question_text = f"<b>{task_label}</b>\n\nВпишите пропущенную букву(ы):\n\n<code>{word.display}</code>"
        kb = input_back_kb()

    if edit:
        await msg.edit_text(question_text, reply_markup=kb)
    else:
        await msg.answer(question_text, reply_markup=kb)


# ── Проверка ответа ───────────────────────────────────────────────────────────

async def process_answer(
    user_id: int,
    user_answer: str,
    msg: Message,
    state: FSMContext,
    session_factory: async_sessionmaker,
) -> None:
    data = await state.get_data()
    word_id: int = data["word_id"]
    attempts: int = data.get("attempts", 0)

    async with session_factory() as session:
        from sqlalchemy import select
        from db.models import Word as WordModel
        result = await session.execute(select(WordModel).where(WordModel.id == word_id))
        word = result.scalar_one_or_none()

        if word is None:
            await state.set_state(PracticeState.idle)
            await msg.answer("Произошла ошибка. Попробуй ещё раз.", reply_markup=main_menu_kb())
            return

        correct = word.answer.strip().lower()
        given = user_answer.strip().lower()
        is_correct = given == correct

        # Первая ошибка — даём второй шанс, не записываем в БД
        if not is_correct and attempts == 0:
            await state.update_data(attempts=1)
            await msg.answer("❌ Неверно. Попробуй ещё раз:")
            return

        await record_answer(session, user_id, word_id, is_correct)

        if is_correct:
            quality = 5 if attempts == 0 else 3
        else:
            quality = 1

        progress = await get_progress(session, user_id, word_id)
        if progress:
            sm2 = sm2_update(quality, progress.interval, progress.repetitions, progress.ef)
        else:
            sm2 = sm2_update(quality, 0, 0, 2.5)

        await upsert_progress(
            session, user_id, word_id,
            sm2.interval, sm2.repetitions, sm2.ef, sm2.next_review,
        )

    def fmt(display: str, answer: str) -> str:
        if "_" in display and " " not in answer and len(answer) <= 3:
            return display.replace("_", answer)
        return answer

    if is_correct:
        text = f"✅ Верно! <b>{fmt(word.display, word.answer)}</b>"
    else:
        text = (
            f"❌ Неверно. Правильный ответ: <b>{fmt(word.display, word.answer)}</b>\n\n"
            f"<i>{word.rule}</i>"
        )

    await state.set_state(PracticeState.idle)
    await msg.answer(text, reply_markup=next_kb())


# ── Текстовый ответ (input) ───────────────────────────────────────────────────

@router.message(PracticeState.waiting_answer)
async def handle_text_answer(message: Message, state: FSMContext, session_factory: async_sessionmaker) -> None:
    data = await state.get_data()
    if data.get("question_type") != "input":
        await message.answer("Пожалуйста, нажми на кнопку с вариантом ответа.")
        return

    await process_answer(message.from_user.id, message.text or "", message, state, session_factory)


# ── Кнопочный ответ (choice) ──────────────────────────────────────────────────

@router.callback_query(PracticeState.waiting_answer, F.data.startswith("ans:"))
async def handle_choice_answer(callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker) -> None:
    _, word_id_str, answer = callback.data.split(":", 2)
    data = await state.get_data()

    if int(word_id_str) != data.get("word_id"):
        await callback.answer("Устаревший вопрос, начни новую практику.")
        return

    await callback.answer()
    await process_answer(callback.from_user.id, answer, callback.message, state, session_factory)
