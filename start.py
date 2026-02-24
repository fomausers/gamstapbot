import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from database import check_user, get_user_data, get_emoji_by_slot  # Добавили импорт
import aiosqlite

router = Router()


# Функция для создания обычной клавиатуры (меню)
def get_main_menu():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Бонус"), KeyboardButton(text="💎 Донат")],
            [KeyboardButton(text="❓ Помощь")]
        ],
        resize_keyboard=True
    )
    return keyboard


# Функция для создания инлайн-кнопок
def get_start_inline(bot_username):
    url = f"https://t.me/{bot_username}?startgroup=true"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в чат", url=url)]
    ])
    return keyboard


@router.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: Message):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет"
    full_name = message.from_user.full_name

    # 1. Регистрация
    await check_user(user_id, username, full_name)

    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
            (username, full_name, user_id)
        )
        await db.commit()

    # 2. Получаем данные для дизайна
    bot_info = await message.bot.get_me()
    welcome_emoji = await get_emoji_by_slot(1)  # Берем эмодзи из слота №1

    # 3. Текст сообщения по твоему дизайну
    text = (
        f"{welcome_emoji} <b>Добро пожаловать!</b>\n\n"
        f"<b>Я — развлекательный бот для вашего чата:</b>\n\n"
        f"• 🏆 Участие в турнирах\n"
        f"• 🎮 Мини-игры\n\n"
        f"<i>Запуская бота, вы автоматически соглашаетесь с условиями использования.</i>"
    )

    # Отправляем одним сообщением с меню и инлайн-кнопкой
    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )

    # Дополнительное сообщение с кнопкой добавления
    await message.answer(
        "Нажмите кнопку ниже, чтобы пригласить меня в группу:",
        reply_markup=get_start_inline(bot_info.username)
    )