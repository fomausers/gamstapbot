import asyncio
import random
import time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import database

mines_router = Router()

# Хранилище активных игр
# Ключ: (chat_id, user_id)
# Значение: {"bet": int, "mines": list, "clicked": list, "active": bool, "msg_id": int}
active_mines = {}
mine_locks = {}

BOMBS_COUNT = 5


def get_multiplier(hits: int) -> float:
    if hits == 0:
        return 1.0
    mult = 0.95
    for i in range(hits):
        safe_tiles = 25 - i
        safe_choices = 25 - BOMBS_COUNT - i
        mult *= safe_tiles / safe_choices
    return round(mult, 2)


def get_mines_keyboard(user_id: int, bombs: list, clicked: list, game_over: bool = False):
    keyboard = []
    empty_char = "ㅤ"

    for row in range(5):
        row_buttons = []
        for col in range(5):
            cell_index = row * 5 + col
            if game_over:
                text = "💣" if cell_index in bombs else empty_char
                cb_data = "ignore"
            else:
                if cell_index in clicked:
                    text = empty_char
                    cb_data = "ignore"
                else:
                    text = "❓"
                    cb_data = f"mine_{cell_index}_{user_id}"
            row_buttons.append(InlineKeyboardButton(text=text, callback_data=cb_data))
        keyboard.append(row_buttons)

    if not game_over and len(clicked) > 0:
        keyboard.append([InlineKeyboardButton(text="💸 Забрать выигрыш", callback_data=f"cashout_{user_id}")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@mines_router.message(F.text.lower().startswith("мины"))
async def cmd_start_mines(message: Message, bot: Bot):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await database.is_games_enabled(chat_id):
        return

    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.answer("⚠️ Формат: <code>мины [ставка]</code>", parse_mode="HTML")

    bet = int(args[1])
    if bet <= 0: return

    balance = await database.get_balance(user_id)
    if balance < bet:
        return await message.answer("⚠️ Недостаточно cron!")

    game_key = (chat_id, user_id)
    lock = mine_locks.setdefault(game_key, asyncio.Lock())

    async with lock:
        # ЛОГИКА УДАЛЕНИЯ СТАРОЙ ИГРЫ
        if game_key in active_mines:
            old_game = active_mines[game_key]
            if old_game["active"]:
                # Возврат ставки
                await database.add_balance(user_id, old_game["bet"])
                # Попытка удалить старое сообщение с кнопками
                try:
                    await bot.delete_message(chat_id, old_game["msg_id"])
                except Exception:
                    pass

        await database.add_balance(user_id, -bet)
        bombs = random.sample(range(25), BOMBS_COUNT)

        formatted_bet = f"{bet:,}".replace(',', ' ')
        mention = message.from_user.mention_html(message.from_user.first_name)

        kb = get_mines_keyboard(user_id, bombs, [])
        new_msg = await message.answer(
            f"{mention}, вы начали игру минное поле!\n💰 Ставка: {formatted_bet} cron",
            reply_markup=kb,
            parse_mode="HTML"
        )

        # Сохраняем ID сообщения новой игры
        active_mines[game_key] = {
            "bet": bet,
            "mines": bombs,
            "clicked": [],
            "active": True,
            "msg_id": new_msg.message_id
        }


@mines_router.callback_query(F.data.startswith("mine_"))
async def process_mine_click(callback: CallbackQuery):
    parts = callback.data.split("_")
    cell_index, owner_id = int(parts[1]), int(parts[2])

    if callback.from_user.id != owner_id:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    game_key = (callback.message.chat.id, callback.from_user.id)
    if game_key not in active_mines or not active_mines[game_key]["active"]:
        return await callback.answer("Игра не найдена.", show_alert=True)

    game = active_mines[game_key]

    if callback.message.message_id != game["msg_id"]:
        return await callback.answer("Эта игра устарела.", show_alert=True)

    lock = mine_locks.setdefault(game_key, asyncio.Lock())
    async with lock:
        if not game["active"] or cell_index in game["clicked"]:
            return await callback.answer()

        game["clicked"].append(cell_index)
        mention = callback.from_user.mention_html(callback.from_user.first_name)

        # ПРОИГРЫШ
        if cell_index in game["mines"]:
            game["active"] = False
            kb = get_mines_keyboard(owner_id, game["mines"], game["clicked"], game_over=True)
            await callback.message.edit_text(
                f"{mention}, игра завершена!\n💵 Вы проиграли",
                reply_markup=kb,
                parse_mode="HTML"
            )
            active_mines.pop(game_key, None)
            mine_locks.pop(game_key, None)
            return

        hits = len(game["clicked"])
        mult = get_multiplier(hits)
        current_win = int(game["bet"] * mult)

        # ПОБЕДА (открыты все пустые клетки)
        if hits == (25 - BOMBS_COUNT):
            game["active"] = False
            await database.add_balance(owner_id, current_win)
            kb = get_mines_keyboard(owner_id, game["mines"], game["clicked"], game_over=True)
            await callback.message.edit_text(
                f"{mention}, поле пройдено!\n💰 Выигрыш: {current_win:,} cron".replace(',', ' '),
                reply_markup=kb,
                parse_mode="HTML"
            )
            active_mines.pop(game_key, None)
            mine_locks.pop(game_key, None)
        # ПРОДОЛЖЕНИЕ ИГРЫ
        else:
            kb = get_mines_keyboard(owner_id, game["mines"], game["clicked"])
            formatted_bet = f"{game['bet']:,}".replace(',', ' ')
            formatted_win = f"{current_win:,}".replace(',', ' ')
            await callback.message.edit_text(
                f"{mention}, вы начали игру минное поле!\n💰 Ставка: {formatted_bet}\n💵 Выигрыш: <b>x{mult}</b> | <b>{formatted_win}</b> cron",
                reply_markup=kb,
                parse_mode="HTML"
            )
        await callback.answer()


@mines_router.callback_query(F.data.startswith("cashout_"))
async def process_cashout(callback: CallbackQuery):
    owner_id = int(callback.data.split("_")[1])
    if callback.from_user.id != owner_id:
        return await callback.answer("Это не ваша игра!", show_alert=True)

    game_key = (callback.message.chat.id, owner_id)
    if game_key not in active_mines or not active_mines[game_key]["active"]:
        return await callback.answer("Игра уже завершена.")

    game = active_mines[game_key]
    lock = mine_locks.setdefault(game_key, asyncio.Lock())

    async with lock:
        game["active"] = False
        mult = get_multiplier(len(game["clicked"]))
        win_amount = int(game["bet"] * mult)

        # Начисляем баланс
        await database.add_balance(owner_id, win_amount)
        await database.add_daily_win(owner_id, win_amount)

        mention = callback.from_user.mention_html(callback.from_user.first_name)
        kb = get_mines_keyboard(owner_id, game["mines"], game["clicked"], game_over=True)

        # Исправленный вызов с parse_mode="HTML"
        await callback.message.edit_text(
            f"{mention}, вы забрали выигрыш!\n💰 Сумма: <b>{win_amount:,}</b> cron".replace(',', ' '),
            reply_markup=kb,
            parse_mode="HTML"
        )

        # Очищаем память
        active_mines.pop(game_key, None)
        mine_locks.pop(game_key, None)
        await callback.answer(f"Зачислено +{win_amount} cron")

@mines_router.callback_query(F.data == "ignore")
async def process_ignore(callback: CallbackQuery):
    await callback.answer()