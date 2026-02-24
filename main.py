import asyncio
import logging
from aiogram import Bot, Dispatcher
from database import init_db, check_user, get_user_data  # Импортируем нужные функции БД
from handlers import router
from perett import router as perett_router
from dmin import router as admin_router

# Импорты для мидлвари
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from typing import Callable, Dict, Any, Awaitable
from bonus import router as bonus_router
from roulette import router as roulette_router
from start import router as start_router
from help import router as help_router
from mines import mines_router
from donate import donate_router
from profile import router as profile_router
from bask import router as bask_router


TOKEN = "8535768087:AAF9D6Sm4hVIYGgaGLA9h8qGvrfSFI5hrmk"


# --- Глобальная мидлварь ---
class GlobalCheckMiddleware(BaseMiddleware):
    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: Message,
            data: Dict[str, Any]
    ) -> Any:
        # Проверяем только сообщения
        if isinstance(event, Message) and event.from_user:
            # 1. Авто-регистрация
            await check_user(
                user_id=event.from_user.id,
                username=event.from_user.username,
                full_name=event.from_user.full_name
            )

            # 2. Проверка на бан
            user = await get_user_data(event.from_user.id)
            if user and user['is_banned']:
                # Если забанен — просто игнорируем (прерываем выполнение)
                return

        return await handler(event, data)


# ---------------------------

async def main():
    logging.basicConfig(level=logging.INFO)

    # Инициализируем БД
    await init_db()

    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    # Подключаем глобальную мидлварь ко всем сообщениям
    dp.message.outer_middleware(GlobalCheckMiddleware())

    # Подключаем роутеры (порядок важен: сначала админ, потом остальные)
    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(perett_router)
    dp.include_router(bonus_router)
    dp.include_router(roulette_router)
    dp.include_router(mines_router)
    dp.include_router(bask_router)
    dp.include_router(help_router)
    dp.include_router(donate_router)
    dp.include_router(profile_router)
    dp.include_router(router)

    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass