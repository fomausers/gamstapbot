import datetime
from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import database

donate_router = Router()

user_invoices = {}

PACKAGES = {
    "buy_25": {"stars": 25, "cron": 50000},
    "buy_50": {"stars": 50, "cron": 104000},
    "buy_100": {"stars": 100, "cron": 208000},
}


# Срабатывает и на команду, и на кнопку из меню
@donate_router.message((F.text.lower() == "донат") | (F.text == "💎 Донат"), F.chat.type == "private")
async def cmd_donate(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ 25 — 50 000 cron", callback_data="buy_25")],
        [InlineKeyboardButton(text="⭐️ 50 — 104 000 cron", callback_data="buy_50")],
        [InlineKeyboardButton(text="⭐️ 100 — 208 000 cron", callback_data="buy_100")]
    ])

    await message.answer(
        "<b>Пополнение баланса</b> 💎\n\n"
        "Вы можете приобрести игровую валюту за Telegram Stars. Выберите подходящий пакет ниже:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@donate_router.callback_query(F.data.in_(PACKAGES.keys()))
async def process_buy_callback(callback: CallbackQuery):
    package = PACKAGES[callback.data]
    stars_amount = package["stars"]
    cron_amount = package["cron"]
    formatted_cron = f"{cron_amount:,}".replace(',', ' ')

    prices = [LabeledPrice(label=f"{formatted_cron} cron", amount=stars_amount)]

    # provider_token оставляем пустым для Telegram Stars (XTR)
    invoice_msg = await callback.message.answer_invoice(
        title="Покупка игровой валюты",
        description=f"Начисление {formatted_cron} cron на ваш баланс в боте.",
        payload=callback.data,
        provider_token="",
        currency="XTR",
        prices=prices
    )

    user_invoices[callback.from_user.id] = invoice_msg.message_id
    await callback.answer()


@donate_router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@donate_router.message(F.successful_payment)
async def successful_payment_handler(message: Message, bot: Bot):
    payload = message.successful_payment.invoice_payload
    if payload not in PACKAGES: return

    package = PACKAGES[payload]
    cron_amount = package["cron"]
    stars_amount = package["stars"]
    charge_id = message.successful_payment.telegram_payment_charge_id
    user_id = message.from_user.id
    mention = message.from_user.mention_html(message.from_user.first_name)

    # Начисляем и сохраняем
    await database.add_balance(user_id, cron_amount)
    await database.add_donation(user_id, charge_id, cron_amount, stars_amount)

    # Удаляем инвойс
    invoice_msg_id = user_invoices.pop(user_id, None)
    if invoice_msg_id:
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=invoice_msg_id)
        except:
            pass

    formatted_cron = f"{cron_amount:,}".replace(',', ' ')
    ts = int(datetime.datetime.now().timestamp())
    cb_data = f"rc_{stars_amount}_{cron_amount}_{ts}"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🧾 Просмотр чека", callback_data=cb_data)
    ]])

    await message.answer(
        f"✅ {mention}, оплата прошла успешно!\n"
        f"➕ Начислено: <b>{formatted_cron} cron</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )


@donate_router.callback_query(F.data.startswith("rc_"))
async def show_receipt(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) == 4:
        _, stars, cron, ts = parts
        formatted_cron = f"{int(cron):,}".replace(',', ' ')
        dt = datetime.datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y %H:%M")

        await callback.answer(
            f"🧾 Чек об оплате\n\n"
            f"👤 Плательщик: {callback.from_user.first_name}\n"
            f"💰 Оплачено: {stars} ⭐️\n"
            f"💎 Получено: {formatted_cron} cron\n"
            f"📅 Время: {dt}",
            show_alert=True
        )