from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, LabeledPrice, PreCheckoutQuery)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database import (get_user_data, get_currency_symbol, check_user,
                      DB_PATH, get_emoji_by_slot, get_history, add_balance, add_donation)
import aiosqlite

router = Router()


class DepositState(StatesGroup):
    waiting_for_amount = State()


# --- ТЕХНИЧЕСКИЕ ФУНКЦИИ ---

async def set_user_language(user_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'none'")
        except:
            pass
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        await db.commit()


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


# --- КЛАВИАТУРЫ ---

def get_profile_kb(lang: str):
    support_url = "https://t.me/hhikasi"
    if lang == "ukr":
        btns = [
            [InlineKeyboardButton(text="💰 Поповнити", callback_data=f"deposit:{lang}")],
            [InlineKeyboardButton(text="📝 Перекази", callback_data=f"my_transfers:{lang}"),
             InlineKeyboardButton(text="🛡️ Статус", callback_data=f"check_status:{lang}")],
            [InlineKeyboardButton(text="👥 Користувачі", callback_data=f"user_list:{lang}")],
            [InlineKeyboardButton(text="🆘 Підтримка", url=support_url)]
        ]
    else:
        btns = [
            [InlineKeyboardButton(text="💰 Пополнить", callback_data=f"deposit:{lang}")],
            [InlineKeyboardButton(text="📝 Переводы", callback_data=f"my_transfers:{lang}"),
             InlineKeyboardButton(text="🛡️ Статус", callback_data=f"check_status:{lang}")],
            [InlineKeyboardButton(text="👥 Пользователи", callback_data=f"user_list:{lang}")],
            [InlineKeyboardButton(text="🆘 Поддержка", url=support_url)]
        ]
    return InlineKeyboardMarkup(inline_keyboard=btns)


# --- ХЕНДЛЕРЫ ПРОФИЛЯ ---

@router.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    await check_user(user_id, message.from_user.username, message.from_user.full_name)
    user = await get_user_data(user_id)
    user_lang = user['language'] if user and 'language' in user.keys() else 'none'

    if user_lang and user_lang != 'none':
        await show_profile(message, user_id, user_lang)
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🇺🇦 Українська", callback_data="set_lang:ukr"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang:rus")
        ]])
        await message.answer("Выбирите язык / Оберіть мову:", reply_markup=kb)


async def show_profile(event: Message | CallbackQuery, user_id: int, lang: str, is_new_message: bool = False):
    user = await get_user_data(user_id)

    emoji_prof = await format_emoji(1)  # Слот 1: 👋 Рука
    cur_symbol = await get_currency_symbol()

    name = event.from_user.first_name
    balance_val = user['balance'] if user else 0
    formatted_balance = f"{balance_val:,}".replace(',', ' ')

    text = (f"{emoji_prof} {'Профіль' if lang == 'ukr' else 'Профиль'} {name}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"{cur_symbol} {'Баланс' if lang == 'ukr' else 'Баланс'}: <b>{formatted_balance}</b>")

    # Если это CallbackQuery и мы НЕ удаляли сообщение ранее
    if isinstance(event, CallbackQuery) and not is_new_message:
        try:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=get_profile_kb(lang))
        except Exception:
            # Если редактирование не удалось (сообщение удалено), отправляем новое
            await event.message.answer(text, parse_mode="HTML", reply_markup=get_profile_kb(lang))
    else:
        # Если это Message или мы явно просим новое сообщение
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, parse_mode="HTML", reply_markup=get_profile_kb(lang))
        else:
            await event.answer(text, parse_mode="HTML", reply_markup=get_profile_kb(lang))

# --- СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ---

@router.callback_query(F.data.startswith("user_list:"))
async def show_user_list(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    active, banned = await get_stats()

    emoji_title = await format_emoji(2)  # Слот 2: 🛡️ Щит
    emoji_active = await format_emoji(3)  # Слот 3: 🟢 Зеленый
    emoji_banned = await format_emoji(4)  # Слот 4: 🔴 Красный

    if lang == "ukr":
        txt = (f"{emoji_title} <b>Статистика користувачів:</b>\n"
               f"{emoji_active} Кількість активних: <b>{active}</b>\n"
               f"{emoji_banned} Кількість в бані: <b>{banned}</b>")
    else:
        txt = (f"{emoji_title} <b>Статистика пользователей:</b>\n"
               f"{emoji_active} Количество активных: <b>{active}</b>\n"
               f"{emoji_banned} Количество в бане: <b>{banned}</b>")

    back_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_profile:{lang}")
    ]])
    await callback.message.edit_text(txt, parse_mode="HTML", reply_markup=back_kb)
    await callback.answer()


# --- ИСТОРИЯ ПЕРЕВОДОВ ---

@router.callback_query(F.data.startswith("my_transfers:"))
async def show_transfers(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    user_id = callback.from_user.id
    history = await get_history(user_id)
    main_mention = get_mention(user_id, callback.from_user.first_name)

    if not history:
        content = f"{main_mention}, ваша історія порожня." if lang == "ukr" else f"{main_mention}, ваша история пуста."
    else:
        lines = [
            f"{main_mention} ваша історія переказів:" if lang == "ukr" else f"{main_mention} ваша история переводов:"]
        for row in history:
            amount = row['amount']
            raw_time = row['timestamp']
            try:
                display_time = f"{raw_time[:5]} + {raw_time[-5:]}"
            except:
                display_time = raw_time

            if row['from_user_id'] == user_id:
                target = get_mention(row['to_user_id'], row['to_user_name'])
                lines.append(f"➖ ({amount}) для {target} ({display_time})")
            else:
                target = get_mention(row['from_user_id'], row['from_user_name'])
                lines.append(f"➕ ({amount}) от {target} ({display_time})")
        content = "\n".join(lines)

    back_btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_profile:{lang}")
    ]])
    await callback.message.edit_text(content, parse_mode="HTML", reply_markup=back_btn)
    await callback.answer()


# --- ПОПОЛНЕНИЕ И ОТМЕНА ---

@router.callback_query(F.data.startswith("deposit:"))
async def deposit_start(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]
    await state.update_data(lang=lang)
    txt = "Введите сумму (Stars):" if lang == "rus" else "Введіть суму (Stars):"

    cancel_btn = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_deposit:{lang}")]])

    await callback.message.edit_text(txt, reply_markup=cancel_btn)
    await state.set_state(DepositState.waiting_for_amount)
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_deposit:"))
async def cancel_deposit(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]
    data = await state.get_data()

    # 1. Удаляем сообщение с инвойсом, если оно было
    if "invoice_msg_id" in data:
        try:
            await callback.bot.delete_message(callback.message.chat.id, data["invoice_msg_id"])
        except Exception:
            pass

    # 2. Удаляем само сообщение "Введите сумму"
    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.clear()

    # 3. Вызываем профиль, передавая флаг is_new_message=True
    await show_profile(callback, callback.from_user.id, lang, is_new_message=True)
    await callback.answer()


@router.message(DepositState.waiting_for_amount)
async def send_invoice(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        return await message.answer("Число!")

    stars = int(message.text)
    cron = stars * 2500

    inv_msg = await message.answer_invoice(
        title="Cron Recharge",
        description=f"{stars} Stars ➜ {cron} cron",
        prices=[LabeledPrice(label="XTR", amount=stars)],
        provider_token="", currency="XTR", payload=f"stars_{stars}"
    )
    # Сохраняем ID, чтобы удалить при отмене
    await state.update_data(invoice_msg_id=inv_msg.message_id)


@router.pre_checkout_query()
async def pre_checkout(pre_query: PreCheckoutQuery):
    await pre_query.answer(ok=True)


@router.message(F.successful_payment)
async def success_pay(message: Message):
    stars = message.successful_payment.total_amount
    cron = stars * 2500
    await add_balance(message.from_user.id, cron)
    await add_donation(message.from_user.id, message.successful_payment.telegram_payment_charge_id, cron, stars)
    try:
        await message.delete()
    except:
        pass
    await message.answer(f"✅ +{cron:,} cron".replace(',', ' '))


@router.callback_query(F.data.startswith("back_to_profile:"))
async def back_to_profile(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    await show_profile(callback, callback.from_user.id, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("check_status:"))
async def check_status(callback: CallbackQuery):
    lang = callback.data.split(":")[1]
    user = await get_user_data(callback.from_user.id)
    is_banned = user['is_banned'] if user and 'is_banned' in user.keys() else 0
    emoji = await format_emoji(4 if is_banned else 3)

    txt = "Блокировка активна" if is_banned else "Аккаунт чист"
    back = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_to_profile:{lang}")
    ]])
    await callback.message.edit_text(f"{emoji} {txt}", parse_mode="HTML", reply_markup=back)
    await callback.answer()