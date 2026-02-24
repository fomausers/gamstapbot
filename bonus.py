from aiogram import Router, F
from aiogram.types import Message
from database import get_last_bonus, update_bonus_time, get_user_data, get_currency_symbol # Добавили импорт
from datetime import datetime, timedelta

router = Router()

def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'

# Реагирует и на "бонус", и на кнопку "🎁 Бонус"
@router.message((F.text.lower() == "бонус") | (F.text == "🎁 Бонус"))
async def get_daily_bonus(message: Message):
    user_id = message.from_user.id
    mention = get_mention(user_id, message.from_user.first_name)

    now = datetime.now()
    last_bonus_str = await get_last_bonus(user_id)

    # Получаем текущий символ валюты из базы
    cur_symbol = await get_currency_symbol()

    # Если в базе '0', значит бонус еще никогда не брали
    if last_bonus_str != '0':
        try:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M")

        next_bonus_time = last_bonus_time + timedelta(hours=24)

        if now < next_bonus_time:
            remaining = next_bonus_time - now
            total_seconds = int(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            return await message.answer(
                f"{mention}, вы уже забирали свой бонус.\n"
                f"Приходите снова через <b>{hours}ч. {minutes}мин.</b>",
                parse_mode="HTML"
            )

    # Выдаем бонус (в базе прибавится 5000)
    new_time_str = now.strftime("%d.%m.%Y %H:%M:%S")
    await update_bonus_time(user_id, new_time_str)

    # Получаем свежие данные, чтобы показать баланс
    user = await get_user_data(user_id)
    balance_val = user['balance'] if user else 0
    
    # Форматируем баланс (красивые пробелы)
    formatted_balance = f"{balance_val:,}".replace(',', ' ')

    await message.answer(
        f"{mention}, вам начислено <b>5 000 {cur_symbol}</b>! 🎁\n"
        f"Ваш баланс: <b>{formatted_balance} {cur_symbol}</b>",
        parse_mode="HTML"
    )
