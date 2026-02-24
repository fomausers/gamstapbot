from aiogram import Router, F
from aiogram.types import Message
from database import get_last_bonus, update_bonus_time, get_user_data
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

    # Если в базе '0', значит бонус еще никогда не брали
    if last_bonus_str != '0':
        try:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            # На случай, если в базе старый формат даты (без секунд)
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M")

        next_bonus_time = last_bonus_time + timedelta(hours=24)

        if now < next_bonus_time:
            # Вычисляем разницу
            remaining = next_bonus_time - now
            # Используем total_seconds, чтобы часы не обнулялись после 24
            total_seconds = int(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            return await message.answer(
                f"{mention}, вы уже забирали свой бонус.\n"
                f"Приходите снова через <b>{hours}ч. {minutes}мин.</b>",
                parse_mode="HTML"
            )

    # Выдаем бонус
    new_time_str = now.strftime("%d.%m.%Y %H:%M:%S")
    await update_bonus_time(user_id, new_time_str)

    # Получаем свежие данные, чтобы показать баланс
    user = await get_user_data(user_id)
    balance = user['balance'] if user else 5000

    await message.answer(
        f"{mention}, вам начислено <b>5000 cron</b>! 🎁\n"
        f"Ваш баланс: <b>{balance} cron</b>",
        parse_mode="HTML"

    )
