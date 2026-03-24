import asyncio
import json
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import BOT_TOKEN, DATABASE_URL, REDIS_URL
from db.models import Base, Word
from db.queries import get_due_words_users
from handlers.practice import router as practice_router
from handlers.stats import router as stats_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def seed_words(session_factory: async_sessionmaker) -> None:
    """Load words.json into DB if the words table is empty."""
    from sqlalchemy import select, func

    async with session_factory() as session:
        count = await session.scalar(select(func.count(Word.id)))
        if count and count > 0:
            return

        words_path = Path(__file__).parent / "data" / "words.json"
        if not words_path.exists():
            logger.warning("words.json not found, skipping seed")
            return

        with open(words_path, encoding="utf-8") as f:
            words_data = json.load(f)

        for item in words_data:
            word = Word(
                display=item["display"],
                answer=item["answer"],
                options=item.get("options"),
                question_type=item["question_type"],
                rule=item["rule"],
                task_number=item["task_number"],
            )
            session.add(word)
        await session.commit()
        logger.info("Seeded %d words from words.json", len(words_data))


async def send_reminders(bot: Bot, session_factory: async_sessionmaker) -> None:
    """APScheduler job: notify users with due words who haven't practiced today."""
    async with session_factory() as session:
        user_ids = await get_due_words_users(session)

    for user_id in user_ids:
        try:
            await bot.send_message(
                user_id,
                "Привет! У тебя есть слова для повторения. Нажми /start чтобы продолжить.",
            )
        except Exception as exc:
            logger.debug("Cannot notify user %s: %s", user_id, exc)


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await seed_words(session_factory)

    storage = RedisStorage.from_url(REDIS_URL)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)

    # Make session_factory available to handlers via bot data
    dp["session_factory"] = session_factory

    dp.include_router(practice_router)
    dp.include_router(stats_router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders,
        trigger="cron",
        hour=10,
        minute=0,
        args=[bot, session_factory],
    )
    scheduler.start()

    logger.info("Bot started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
