from aiogram import Router, F
from aiogram.types import Message
from database import set_balance, set_ban_status, set_custom_currency, get_currency_symbol, set_tap_emoji, save_custom_emoji, get_all_custom_emojis

router = Router()
ADMIN_ID = 621856176


# Мидлварь для проверки админа
@router.message.middleware()
async def admin_check_middleware(handler, event, data):
    if event.from_user.id != ADMIN_ID:
        return
    return await handler(event, data)


# --- НОВАЯ КОМАНДА: ПОСТАВИТЬ (СИМВОЛ) ---
@router.message(F.text.lower().startswith("поставить"))
async def admin_set_currency_symbol(message: Message):
    try:
        # Проверяем, есть ли в сообщении кастомные эмодзи
        custom_emoji = None
        if message.entities:
            for entity in message.entities:
                if entity.type == "custom_emoji":
                    # Формируем специальный тег, который Telegram поймет как кастомный эмодзи
                    custom_emoji = f'<tg-emoji emoji-id="{entity.custom_emoji_id}">⏳</tg-emoji>'
                    break

        # Если кастомный эмодзи найден — берем его, если нет — берем обычный текст
        if custom_emoji:
            new_symbol = custom_emoji
        else:
            new_symbol = message.text[10:].strip()

        if not new_symbol:
            return await message.answer("Ошибка. Введите символ.")

        await set_custom_currency(new_symbol)

        # Отвечаем с использованием HTML, чтобы кастомный эмодзи отобразился
        await message.answer(
            f"✅ Символ валюты изменен на: {new_symbol}",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(F.text.lower().startswith("тап"))
async def admin_set_tap_emoji(message: Message):
    try:
        custom_emoji = None
        # Проверяем на наличие кастомного эмодзи (entities)
        if message.entities:
            for entity in message.entities:
                if entity.type == "custom_emoji":
                    custom_emoji = f'<tg-emoji emoji-id="{entity.custom_emoji_id}">🔘</tg-emoji>'
                    break

        if custom_emoji:
            new_tap = custom_emoji
        else:
            # Если это просто текст, берем всё после слова "тап "
            new_tap = message.text[4:].strip()

        if not new_tap:
            return await message.answer("Ошибка. Введите эмодзи. Пример: <code>тап ⚡️</code>")

        await set_tap_emoji(new_tap)
        await message.answer(f"✅ Эмодзи для тапа изменен на: {new_tap}", parse_mode="HTML")

    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(F.text.lower().startswith("ск"))
async def admin_save_emoji_to_list(message: Message):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            return await message.answer("Формат: <code>ск (эмодзи) (номер)</code>")

        # Проверяем номер (последний аргумент)
        try:
            slot_number = int(parts[-1])
        except ValueError:
            return await message.answer("Ошибка: номер должен быть числом.")

        # Извлекаем эмодзи
        custom_emoji = None
        if message.entities:
            for entity in message.entities:
                if entity.type == "custom_emoji":
                    custom_emoji = f'<tg-emoji emoji-id="{entity.custom_emoji_id}">✨</tg-emoji>'
                    break

        # Если кастомного нет, берем текст между "ск" и "номером"
        if not custom_emoji:
            # Склеиваем всё что между командой и номером
            custom_emoji = " ".join(parts[1:-1]).strip()

        if not custom_emoji:
            return await message.answer("Не удалось распознать эмодзи.")

        await save_custom_emoji(custom_emoji, slot_number)
        await message.answer(f"✅ Эмодзи сохранен в слот №{slot_number}: {custom_emoji}", parse_mode="HTML")

    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(F.text.lower() == "список ск")
async def admin_show_emoji_list(message: Message):
    emojis = await get_all_custom_emojis()
    if not emojis:
        return await message.answer("Список пуст.")

    text = "<b>Список сохраненных эмодзи:</b>\n\n"
    for slot, emoji in emojis:
        text += f"{slot}. {emoji}\n"

    await message.answer(text, parse_mode="HTML")



# 1. Выдать (сумма) ид
@router.message(F.text.lower().startswith("выдать"))
async def admin_give_money(message: Message):
    try:
        parts = message.text.split()
        amount = int(parts[1])
        target_id = int(parts[2])

        cur = await get_currency_symbol()  # Получаем текущий символ из базы
        await set_balance(target_id, amount, mode="add")
        await message.answer(f"✅ Игроку <code>{target_id}</code> начислено {amount} {cur}", parse_mode="HTML")
    except:
        await message.answer("Ошибка. Формат: выдать (сумма) (ид)")


# 2. Обнулить ид
@router.message(F.text.lower().startswith("обнулить"))
async def admin_reset_balance(message: Message):
    try:
        target_id = int(message.text.split()[1])
        await set_balance(target_id, 0, mode="set")
        await message.answer(f"✅ Баланс игрока <code>{target_id}</code> обнулен", parse_mode="HTML")
    except:
        await message.answer("Ошибка. Формат: обнулить (ид)")


# 3. Бан ид
@router.message(F.text.lower().startswith("бан"))
async def admin_ban(message: Message):
    try:
        target_id = int(message.text.split()[1])
        await set_ban_status(target_id, 1)
        await message.answer(f"🚫 Пользователь <code>{target_id}</code> забанен", parse_mode="HTML")
    except:
        await message.answer("Ошибка. Формат: бан (ид)")


# 4. Разбан ид
@router.message(F.text.lower().startswith("разбан"))
async def admin_unban(message: Message):
    try:
        target_id = int(message.text.split()[1])
        await set_ban_status(target_id, 0)
        await message.answer(f"😇 Пользователь <code>{target_id}</code> разбанен", parse_mode="HTML")
    except:
        await message.answer("Ошибка. Формат: разбан (ид)")