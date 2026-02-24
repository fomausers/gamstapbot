import asyncio
import logging
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.types import Message, TelegramObject
from typing import Callable, Dict, Any, Awaitable

# Импорты БД
from database import init_db, check_user, get_user_data

# Импорты роутеров основного бота
from handlers import router
from perett import router as perett_router
from dmin import router as admin_router
from bonus import router as bonus_router
from roulette import router as roulette_router
from start import router as start_router
from help import router as help_router
from mines import mines_router
from donate import donate_router
from profile import router as profile_router
from bask import router as bask_router

# Импорт роутера саппорт-бота
from saport import router as saport_router

# --- КОНФИГ ТОКЕНОВ ---
MAIN_TOKEN = "8535768087:AAF9D6Sm4hVIYGgaGLA9h8qGvrfSFI5hrmk"
SUPPORT_TOKEN = "8203910368:AAH4BSgNWJMpqLw3ZE7lieVwej1rzOjNrGA"  # Вставьте сюда токен саппорт-бота


# --- Глобальная мидлварь (для основного бота) ---
class GlobalCheckMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        if isinstance(event, Message) and event.from_user:
            await check_user(
                user_id=event.from_user.id,
                username=event.from_user.username,
                full_name=event.from_user.full_name
            )
            user = await get_user_data(event.from_user.id)
            if user and user['is_banned']:
                return
        return await handler(event, data)


async def main():
    logging.basicConfig(level=logging.INFO)

    # 1. Инициализация общей БД
    await init_db()

    # --- НАСТРОЙКА ОСНОВНОГО БОТА ---
    main_bot = Bot(token=MAIN_TOKEN)
    main_dp = Dispatcher()

    main_dp.message.outer_middleware(GlobalCheckMiddleware())

    main_dp.include_router(start_router)
    main_dp.include_router(admin_router)
    main_dp.include_router(perett_router)
    main_dp.include_router(bonus_router)
    main_dp.include_router(roulette_router)
    main_dp.include_router(mines_router)
    main_dp.include_router(bask_router)
    main_dp.include_router(help_router)
    main_dp.include_router(donate_router)
    main_dp.include_router(profile_router)
    main_dp.include_router(router)

    # --- НАСТРОЙКА САППОРТ БОТА ---
    support_bot = Bot(token=SUPPORT_TOKEN)
    support_dp = Dispatcher()

    # Подключаем только файл saport.py
    support_dp.include_router(saport_router)

    print("✅ Оба бота запущены!")

    # Запускаем обоих ботов одновременно
    # Бот 1 (Main) и Бот 2 (Support) будут работать параллельно
    try:
        await asyncio.gather(
            main_dp.start_polling(main_bot),
            support_dp.start_polling(support_bot)
        )
    finally:
        await main_bot.session.close()
        await support_bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Боты остановлены.")
