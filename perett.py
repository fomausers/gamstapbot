from aiogram import Router, F
from aiogram.types import Message
from database import make_transfer, get_history, check_user, get_currency_symbol
import logging

router = Router()


# Функция для создания безопасного упоминания по ID
def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


# Команда передачи: п (сумма) реплаем
@router.message(F.text.lower().startswith("п "), F.reply_to_message)
async def transfer_money(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        return

    amount = int(parts[1])
    if amount <= 0:
        return await message.answer("Сумма должна быть больше 0.")

    from_user = message.from_user
    to_user = message.reply_to_message.from_user

    # Проверка: нельзя переводить самому себе
    if from_user.id == to_user.id:
        return await message.answer("ты пытаешься передать себе")

    # Проверка: нельзя переводить ботам
    if to_user.is_bot:
        return await message.answer("Они ему не нужнны")

    # Регистрация получателя
    await check_user(to_user.id, to_user.username, to_user.full_name)

    success = await make_transfer(
        from_user.id, to_user.id,
        from_user.first_name, to_user.first_name,
        amount
    )

    if success:
        # Получаем текущий кастомный символ из базы
        cur_symbol = await get_currency_symbol()

        # Упоминания через ID
        from_mention = get_mention(from_user.id, from_user.first_name)
        to_mention = get_mention(to_user.id, to_user.first_name)

        # Дизайн: {Ник} передал {Сумма} {Эмодзи} для {Ник}
        text = f"{from_mention} <b>передал {amount} {cur_symbol} для</b> {to_mention}"

        await message.answer(text, parse_mode="HTML")
    else:
        await message.answer("❌ Недостаточно средств на балансе.")





# Команда история
@router.message(F.text.lower() == "история")
async def show_history(message: Message):
    history = await get_history(message.from_user.id)
    # Главное упоминание пользователя
    main_mention = get_mention(message.from_user.id, message.from_user.first_name)

    if not history:
        return await message.answer(f"{main_mention} ваша история переводов пуста.", parse_mode="HTML")

    lines = [f"{main_mention} ваша история переводов"]

    for row in history:
        amount = row['amount']
        # Преобразуем дату из БД (24.02.2026 01:59) в нужный формат (24.02 + 01:59)
        # Если в базе дата хранится как "24.02.2026 01:59", берем части строки
        raw_time = row['timestamp']
        try:
            date_part = raw_time[:5]     # 24.02
            time_part = raw_time[-5:]    # 01:59
            display_time = f"{date_part} + {time_part}"
        except:
            display_time = raw_time

        if row['from_user_id'] == message.from_user.id:
            # Исходящий перевод (-)
            # Упоминаем того, КОМУ перевели
            target_mention = get_mention(row['to_user_id'], row['to_user_name'])
            lines.append(f"➖ ({amount}) для {target_mention} ({display_time})")
        else:
            # Входящий перевод (+)
            # Упоминаем того, ОТ КОГО пришло
            target_mention = get_mention(row['from_user_id'], row['from_user_name'])
            lines.append(f"➕ ({amount}) от {target_mention} ({display_time})")

    await message.answer("\n".join(lines), parse_mode="HTML")