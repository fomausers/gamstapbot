import asyncio
import re
import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import (Message, LabeledPrice, PreCheckoutQuery)
from aiogram.filters import Command
from database import (get_user_data, get_currency_symbol, check_user,
                      DB_PATH, get_emoji_by_slot, get_history, add_balance, add_donation)
import aiosqlite

router = Router()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0") as c:
            active = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as c:
            banned = (await c.fetchone())[0]
        return active, banned


async def format_emoji(slot):
    code = await get_emoji_by_slot(slot)
    if code and str(code).isdigit():
        return f'<tg-emoji emoji-id="{code}">✨</tg-emoji>'
    return code if code else "🔹"


# --- ОСНОВНОЙ ХЕНДЛЕР (ПРОФИЛЬ) ---

@router.message(Command("start", "profile", "p"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    # Регистрируем/обновляем юзера
    await check_user(user_id, message.from_user.username, message.from_user.full_name)

    user = await get_user_data(user_id)
    emoji_prof = await format_emoji(1)
    cur_symbol = await get_currency_symbol()

    balance_val = user['balance'] if user else 0
    formatted_balance = f"{balance_val:,}".replace(',', ' ')

    # Текстовый профиль с перечнем команд вместо кнопок
    text = (
        f"{emoji_prof} <b>Профиль {message.from_user.first_name}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"{cur_symbol} Баланс: <b>{formatted_balance}</b>\n"
        f"────────────────\n"
        f"💳 <code>/deposit [сумма]</code> — Пополнить\n"
        f"📝 <code>/history</code> — История переводов\n"
        f"📊 <code>/stats</code> — Статистика бота\n"
        f"🛡 <code>/status</code> — Статус аккаунта\n"
        f"🆘 <code>/help</code> — Поддержка"
    )

    await message.answer(text, parse_mode="HTML")


# --- СТАТИСТИКА (/stats) ---

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    active, banned = await get_stats()
    emoji_title = await format_emoji(2)
    emoji_active = await format_emoji(3)
    emoji_banned = await format_emoji(4)

    txt = (
        f"{emoji_title} <b>Статистика:</b>\n"
        f"{emoji_active} Активных: <b>{active}</b>\n"
        f"{emoji_banned} В бане: <b>{banned}</b>"
    )
    await message.answer(txt, parse_mode="HTML")


# --- СТАТУС (/status) ---

@router.message(Command("status"))
async def cmd_status(message: Message):
    user = await get_user_data(message.from_user.id)
    is_banned = user['is_banned'] if user and 'is_banned' in user.keys() else 0
    emoji = await format_emoji(4 if is_banned else 3)

    txt = "❌ <b>Ваш аккаунт заблокирован</b>" if is_banned else "✅ <b>Ваш аккаунт чист</b>"
    await message.answer(f"{emoji} {txt}", parse_mode="HTML")


# --- ИСТОРИЯ (/history) ---

@router.message(Command("history"))
async def cmd_history(message: Message):
    user_id = message.from_user.id
    history = await get_history(user_id)
    mention = get_mention(user_id, message.from_user.first_name)

    if not history:
        return await message.answer(f"{mention}, ваша история пуста.", parse_mode="HTML")

    lines = [f"📝 <b>История переводов {mention}:</b>"]
    for row in history[:15]:  # Ограничим 15 записями для чистоты
        amount = f"{row['amount']:,}".replace(',', ' ')
        time = row['timestamp']
        if row['from_user_id'] == user_id:
            target = get_mention(row['to_user_id'], row['to_user_name'])
            lines.append(f"➖ <code>{amount}</code> ➔ {target} | <small>{time}</small>")
        else:
            target = get_mention(row['from_user_id'], row['from_user_name'])
            lines.append(f"➕ <code>{amount}</code> ⬅️ {target} | <small>{time}</small>")

    await message.answer("\n".join(lines), parse_mode="HTML")


# --- ПОПОЛНЕНИЕ (/deposit сумма) ---

@router.message(Command("deposit"))
async def cmd_deposit(message: Message):
    # Пытаемся взять сумму из аргумента команды: /deposit 100
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer(
            "ℹ️ Используйте: <code>/deposit [сумма в Stars]</code>\nПример: <code>/deposit 50</code>",
            parse_mode="HTML")

    stars = int(args[1])
    if stars < 1:
        return await message.answer("❌ Минимальная сумма — 1 Star")

    cron_amount = stars * 2500

    await message.answer_invoice(
        title="Пополнение баланса",
        description=f"К зачислению: {cron_amount:,} cron".replace(',', ' '),
        prices=[LabeledPrice(label="Stars", amount=stars)],
        provider_token="",  # Для Telegram Stars пусто
        currency="XTR",
        payload=f"stars_{stars}"
    )


@router.pre_checkout_query()
async def pre_checkout(pre_query: PreCheckoutQuery):
    await pre_query.answer(ok=True)


@router.message(F.successful_payment)
async def success_pay(message: Message):
    stars = message.successful_payment.total_amount
    cron = stars * 2500
    await add_balance(message.from_user.id, cron)
    await add_donation(message.from_user.id, message.successful_payment.telegram_payment_charge_id, cron, stars)

    await message.answer(f"✅ <b>Успешно!</b>\nЗачислено: +{cron:,} cron".replace(',', ' '), parse_mode="HTML")


# --- ПОМОЩЬ ---

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer("🆘 Поддержка: @hhikasi\n\nВсе команды бота доступны в <code>/start</code>", parse_mode="HTML")
