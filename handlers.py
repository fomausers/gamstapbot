import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database import get_user_data, get_last_bonus, update_bonus_time
from datetime import datetime, timedelta
from database import get_user_data, get_last_bonus, get_currency_symbol # Добавь её сюда

router = Router()


def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


@router.message(F.text.lower() == "б")
async def show_balance(message: Message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    balance_val = user['balance'] if user else 0
    mention = get_mention(user_id, message.from_user.first_name)

    # --- ПОЛУЧАЕМ КАСТОМНЫЙ СИМВОЛ ИЗ БАЗЫ ---
    # (тот самый, который ты сохранил командой "поставить")
    cur_symbol = await get_currency_symbol()

    # Форматируем баланс: 50000 -> 50 000
    formatted_balance = f"{balance_val:,}".replace(',', ' ')

    # Заменяем Луну и cron на переменную cur_symbol
    text = (
        f"{mention}\n"
        f"<b>{cur_symbol} баланс: {formatted_balance}</b>"
    )

    # Проверка бонуса
    keyboard = None
    last_bonus_str = await get_last_bonus(user_id)

    can_get_bonus = False
    if last_bonus_str == '0':
        can_get_bonus = True
    else:
        try:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M")

        if datetime.now() >= last_bonus_time + timedelta(hours=24):
            can_get_bonus = True

    if can_get_bonus:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Получить бонус", callback_data=f"claim_bonus:{user_id}")]
        ])

    # parse_mode="HTML" обязателен, чтобы кастомный эмодзи отрисовался
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# Обработка нажатия на кнопку бонуса
@router.callback_query(F.data.startswith("claim_bonus:"))
async def process_bonus_callback(callback: CallbackQuery):
    # Извлекаем ID владельца кнопки из callback_data
    owner_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # ЗАЩИТА: проверяем, тот ли человек нажал кнопку
    if user_id != owner_id:
        return await callback.answer("❌ Это не ваша кнопка!", show_alert=True)

    last_bonus_str = await get_last_bonus(user_id)
    now = datetime.now()

    can_get = False
    if last_bonus_str == '0':
        can_get = True
    else:
        try:
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            # На случай, если в базе дата без секунд
            last_bonus_time = datetime.strptime(last_bonus_str, "%d.%m.%Y %H:%M")

        if now >= last_bonus_time + timedelta(hours=24):
            can_get = True

    if can_get:
        new_time_str = now.strftime("%d.%m.%Y %H:%M:%S")
        await update_bonus_time(user_id, new_time_str)

        user = await get_user_data(user_id)
        mention = get_mention(user_id, callback.from_user.first_name)

        # Форматируем баланс с пробелами: 50000 -> 50 000
        balance_val = user['balance'] if user else 0
        formatted_balance = f"{balance_val:,}".replace(',', ' ')

        # Редактируем сообщение, убирая кнопку
        await callback.message.edit_text(
            f"{mention}\n"
            f"<b>🌕 баланс: {formatted_balance} cron</b>\n\n"
            f" <b>5 000 cron</b> зачислено!",
            parse_mode="HTML"
        )
        await callback.answer("💰 Бонус получен!")
    else:
        # Если кнопка осталась висеть, а время еще не пришло
        await callback.answer("⚠️ Бонус еще не доступен.", show_alert=True)
        # Опционально: можно удалить кнопку, если она уже не актуальна
        await callback.message.edit_reply_markup(reply_markup=None)


# 2. Эхо-заглушка
@router.message()
async def echo_all(message: Message):

    logging.info(f"Текст получен: {message.text}")
