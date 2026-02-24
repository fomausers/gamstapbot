import asyncio
import random
from aiogram import Router, F
from aiogram.types import Message
from database import get_balance, add_balance, get_currency_symbol, get_emoji_by_slot

router = Router()

# Словарь для хранения состояния игр (антифлуд)
active_games = {}


def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


@router.message(F.text.lower().startswith("баскет"))
async def play_basket(message: Message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Проверка антифлуда с подсказкой
    if active_games.get((chat_id, user_id)):
        return await message.reply("⏳ Дождись результата предыдущего броска!")

    # Разбор ставки
    parts = message.text.lower().split()
    if len(parts) < 2:
        return await message.answer("Введите сумму ставки или 'вб'. Пример: баскет 100")

    current_balance = await get_balance(user_id)

    # Логика "вб" (все в банк) или число
    if parts[1] == "вб":
        bet = current_balance
    elif parts[1].isdigit():
        bet = int(parts[1])
    else:
        return await message.answer("Сумма ставки должна быть числом или 'вб'.")

    if bet <= 0:
        if current_balance <= 0 and parts[1] == "вб":
            return await message.answer("❌ У вас нулевой баланс.")
        return await message.answer("Ставка должна быть больше 0.")

    if current_balance < bet:
        return await message.answer("❌ Недостаточно средств.")

    # Блокируем создание новых бросков для юзера
    active_games[(chat_id, user_id)] = True

    try:
        # Списываем ставку
        await add_balance(user_id, -bet)

        # Отправляем кубик баскетбола
        basket_msg = await message.answer_dice(emoji="🏀")

        # Ждем завершения анимации
        await asyncio.sleep(4)

        result_val = basket_msg.dice.value  # 1-5

        # Получаем данные для оформления
        cur_icon = await get_currency_symbol()
        win_emoji = await get_emoji_by_slot(3)  # Эмодзи победы
        lose_emoji = await get_emoji_by_slot(4)  # Эмодзи проигрыша
        mention = get_mention(user_id, message.from_user.first_name)

        is_win = result_val >= 4
        win_amount = 0
        status_text = "промах"
        result_icon = lose_emoji

        if is_win:
            status_text = "попал"
            result_icon = win_emoji
            if result_val == 5:
                multiplier = 2.0
            else:
                multiplier = round(random.uniform(1.4, 1.9), 1)

            win_amount = int(bet * multiplier)
            await add_balance(user_id, win_amount)

        # Форматирование чисел
        f_bet = f"{bet:,}".replace(',', ' ')
        f_win = f"{win_amount:,}".replace(',', ' ')

        # Текст результата
        text = (
            f"{result_icon} {mention} {status_text}\n\n"
            f"{cur_icon} <b>ставка: {f_bet}</b>\n"
            f"{cur_icon} <b>выиграш: {f_win}</b>"
        )

        await basket_msg.reply(text, parse_mode="HTML")

    finally:
        # Снимаем блокировку
        active_games[(chat_id, user_id)] = False