from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import Integer, func, select, update, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Answer, Explanation, Progress, User, Word


async def get_or_create_user(session: AsyncSession, user_id: int, username: Optional[str]) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(id=user_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif user.username != username:
        user.username = username
        await session.commit()
    return user


async def get_next_word(
    session: AsyncSession, user_id: int, task_number: Optional[int] = None
) -> Optional[Word]:
    today = date.today()

    task_filter = [Word.task_number == task_number] if task_number else []

    # First try: word due for review
    result = await session.execute(
        select(Word)
        .join(Progress, and_(Progress.word_id == Word.id, Progress.user_id == user_id))
        .where(Word.is_active == True, Progress.next_review <= today, *task_filter)
        .order_by(Progress.next_review.asc())
        .limit(1)
    )
    word = result.scalar_one_or_none()
    if word is not None:
        return word

    # Second try: new word not yet in progress
    result = await session.execute(
        select(Word)
        .where(
            Word.is_active == True,
            ~Word.id.in_(select(Progress.word_id).where(Progress.user_id == user_id)),
            *task_filter,
        )
        .order_by(Word.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_progress(session: AsyncSession, user_id: int, word_id: int) -> Optional[Progress]:
    result = await session.execute(
        select(Progress).where(
            Progress.user_id == user_id,
            Progress.word_id == word_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_progress(
    session: AsyncSession,
    user_id: int,
    word_id: int,
    interval: int,
    repetitions: int,
    ef: float,
    next_review: date,
) -> None:
    existing = await get_progress(session, user_id, word_id)
    if existing is None:
        progress = Progress(
            user_id=user_id,
            word_id=word_id,
            interval=interval,
            repetitions=repetitions,
            ef=ef,
            next_review=next_review,
        )
        session.add(progress)
    else:
        existing.interval = interval
        existing.repetitions = repetitions
        existing.ef = ef
        existing.next_review = next_review
    await session.commit()


async def record_answer(
    session: AsyncSession,
    user_id: int,
    word_id: int,
    is_correct: bool,
) -> None:
    answer = Answer(user_id=user_id, word_id=word_id, is_correct=is_correct)
    session.add(answer)
    await session.commit()


async def get_user_stats(session: AsyncSession, user_id: int) -> dict:
    today = date.today()

    # Total answers
    total_result = await session.execute(
        select(func.count(Answer.id), func.sum(Answer.is_correct.cast(Integer)))
        .where(Answer.user_id == user_id)
    )
    row = total_result.one()
    total_answers = row[0] or 0
    total_correct = int(row[1] or 0)

    # Words studied
    words_studied_result = await session.execute(
        select(func.count(Progress.word_id)).where(Progress.user_id == user_id)
    )
    words_studied = words_studied_result.scalar() or 0

    # Words due today
    words_due_result = await session.execute(
        select(func.count(Progress.word_id)).where(
            Progress.user_id == user_id,
            Progress.next_review <= today,
        )
    )
    words_due = words_due_result.scalar() or 0

    # Answers today
    today_start = datetime.combine(today, datetime.min.time())
    answers_today_result = await session.execute(
        select(func.count(Answer.id)).where(
            Answer.user_id == user_id,
            Answer.ts >= today_start,
        )
    )
    answers_today = answers_today_result.scalar() or 0

    correct_pct = round(total_correct / total_answers * 100, 1) if total_answers > 0 else 0.0

    return {
        "total_answers": total_answers,
        "total_correct": total_correct,
        "correct_pct": correct_pct,
        "words_studied": words_studied,
        "words_due": words_due,
        "answers_today": answers_today,
    }


async def get_leaderboard_by_count(session: AsyncSession, limit: int = 10) -> list[dict]:
    result = await session.execute(
        select(
            User.id,
            User.username,
            func.count(Answer.id).label("total"),
            func.sum(Answer.is_correct.cast(Integer)).label("correct"),
        )
        .join(Answer, Answer.user_id == User.id)
        .group_by(User.id, User.username)
        .order_by(func.sum(Answer.is_correct.cast(Integer)).desc())
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "user_id": r.id,
            "username": r.username or f"id{r.id}",
            "total": r.total,
            "correct": int(r.correct or 0),
        }
        for r in rows
    ]


async def get_leaderboard_by_percent(session: AsyncSession, min_answers: int = 50, limit: int = 10) -> list[dict]:
    result = await session.execute(
        select(
            User.id,
            User.username,
            func.count(Answer.id).label("total"),
            func.sum(Answer.is_correct.cast(Integer)).label("correct"),
        )
        .join(Answer, Answer.user_id == User.id)
        .group_by(User.id, User.username)
        .having(func.count(Answer.id) >= min_answers)
        .order_by(
            (func.sum(Answer.is_correct.cast(Integer)) * 100.0 / func.count(Answer.id)).desc()
        )
        .limit(limit)
    )
    rows = result.all()
    return [
        {
            "user_id": r.id,
            "username": r.username or f"id{r.id}",
            "total": r.total,
            "correct": int(r.correct or 0),
            "pct": round(int(r.correct or 0) / r.total * 100, 1),
        }
        for r in rows
    ]


async def get_explanation(session: AsyncSession, word_id: int) -> Optional[str]:
    result = await session.execute(
        select(Explanation.text).where(Explanation.word_id == word_id)
    )
    row = result.scalar_one_or_none()
    return row


async def save_explanation(session: AsyncSession, word_id: int, text_content: str) -> None:
    existing = await session.execute(
        select(Explanation).where(Explanation.word_id == word_id)
    )
    expl = existing.scalar_one_or_none()
    if expl is None:
        expl = Explanation(word_id=word_id, text=text_content)
        session.add(expl)
    else:
        expl.text = text_content
        expl.generated_at = datetime.utcnow()
    await session.commit()


async def get_due_words_users(session: AsyncSession) -> list[int]:
    """Return user IDs who have words due today and haven't answered today."""
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # Users with due words
    due_subq = (
        select(Progress.user_id)
        .where(Progress.next_review <= today)
        .distinct()
        .subquery()
    )

    # Users who answered today
    active_subq = (
        select(Answer.user_id)
        .where(Answer.ts >= today_start)
        .distinct()
        .subquery()
    )

    result = await session.execute(
        select(due_subq.c.user_id)
        .where(due_subq.c.user_id.not_in(select(active_subq.c.user_id)))
    )
    return [row[0] for row in result.all()]
