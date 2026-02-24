from aiogram import Router, F
from aiogram.types import Message
from datetime import datetime
from database import get_user_data, get_currency_symbol, get_tap_emoji

router = Router()


def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


@router.message(F.text.lower() == "профиль")
async def show_profile(message: Message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)

    if not user:
        return await message.answer("Ошибка: профиль не найден. Попробуйте написать любое сообщение.")

    # 1. Получаем кастомные эмодзи из настроек
    cur_symbol = await get_currency_symbol()  # Эмодзи баланса
    status_icon = await get_tap_emoji()  # Второй кастомный эмодзи (статус)

    # 2. Данные пользователя
    name_mention = get_mention(user_id, message.from_user.first_name)
    balance_val = f"{user['balance']:,}".replace(',', ' ')

    # Дата регистрации (если в базе нет, ставим текущую для примера)
    reg_date = user['reg_date'] if user['reg_date'] else datetime.now().strftime("%d.%m.%Y")

    # 3. Формируем текст профиля согласно дизайну
    text = (
        f"<b>Ваш профиль</b> {name_mention}\n\n"
        f"{status_icon} <b>статус: новичок</b>\n"
        f" ID: <code>{user_id}</code>\n"
        f"{cur_symbol} <b>баланс: {balance_val}</b>\n\n"
        f"<blockquote>💬 <b>дата регистрации: {reg_date}</b></blockquote>"
    )

    await message.answer(text, parse_mode="HTML")