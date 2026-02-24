import re
import random
import asyncio
import time
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram import html

from database import (
    get_balance, add_balance, save_last_bet, get_last_bet,
    add_game_log, get_game_logs, get_currency_icon, add_daily_win, is_games_enabled
)

router = Router()
games = {}
user_locks = {}
chat_locks = {}
RED_NUMBERS = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]


def get_styled_mention(user):
    return f'<b><a href="tg://user?id={user.id}">{html.quote(user.full_name)}</a></b>'


def get_color(n):
    if n == 0: return "🟢"
    return "🔴" if n in RED_NUMBERS else "⚫"


@router.message(
    F.chat.type != "private",
    F.text.regexp(re.compile(r"^(лог|ставки|отмена|отменить|\d+)", re.IGNORECASE))
)
async def handle_bets(message: Message):
    chat_id = message.chat.id

    if not await is_games_enabled(chat_id):
        return

    text_parts = message.text.lower().split()
    if not text_parts:
        return

    command = text_parts[0]
    user_id = message.from_user.id

    if command == "лог":
        logs = await get_game_logs(chat_id)
        if not logs:
            return await message.answer("История игр пуста")
        res = "\n".join([f"<b>{n}</b> {c}" for n, c in logs[:10]])
        return await message.answer(f"<b>Последние игры:</b>\n{res}", parse_mode="HTML")

    game = games.setdefault(chat_id, {"bets": {}, "start_time": 0, "is_running": False})

    if game["is_running"]:
        if command.isdigit() or command in {"отмена", "отменить"}:
            return await message.reply("⏳ Дождитесь результата рулетки")
        return

    if command == "ставки":
        if user_id not in game["bets"]:
            return await message.answer("У вас нет активных ставок.")
        user_data = game["bets"][user_id]
        lines = [f"{user_data['mention']} {b['amount']} на {b['display']}" for b in user_data["items"]]
        for i in range(0, len(lines), 30):
            chunk = "\n".join(lines[i:i + 30])
            await message.answer(chunk, parse_mode="HTML")
        return

    lock = user_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        if command in {"отмена", "отменить"}:
            if user_id in game["bets"]:
                total_return = sum(bet['amount'] for bet in game["bets"][user_id]["items"])
                mention = game["bets"][user_id]["mention"]
                icon = get_currency_icon()
                await add_balance(user_id, total_return)
                del game["bets"][user_id]
                if not game["bets"]:
                    game["start_time"] = 0
                return await message.answer(f"{mention}, ставки отменены. Возвращено: {total_return} {icon}",
                                            parse_mode="HTML")
            return await message.answer("У вас нет активных ставок.")

        # --- ПРИЕМ СТАВОК С УЛУЧШЕННОЙ ПРОВЕРКОЙ ---
        if command.isdigit():
            amount = int(command)
            if amount <= 0:
                return

            args = text_parts[1:]
            if not args:
                return

            # Ограничиваем количество, но проверяем строгость
            if len(args) > 100:
                await message.reply("Максимум 100 ставок за сообщение.")
                args = args[:100]

            temp_new_bets = []
            red_aliases = {'к', 'красное', 'red'}
            black_aliases = {'ч', 'черное', 'black'}
            zero_aliases = {'з', 'зеленое', 'zero', '0'}

            for arg in args:
                # 1. Проверка на цвета
                if arg in red_aliases:
                    temp_new_bets.append({"type": "red", "amount": amount, "display": "RED"})
                elif arg in black_aliases:
                    temp_new_bets.append({"type": "black", "amount": amount, "display": "BLACK"})
                elif arg in zero_aliases:
                    temp_new_bets.append({"type": "number", "amount": amount, "value": 0, "display": "ZERO"})

                # 2. Проверка на диапазоны (строго число-число)
                elif '-' in arg:
                    try:
                        parts = arg.split('-')
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            s_raw, e_raw = int(parts[0]), int(parts[1])
                            s, e = sorted([s_raw, e_raw])
                            if 0 <= s <= 36 and 0 <= e <= 36:
                                temp_new_bets.append(
                                    {"type": "range", "amount": amount, "value": (s, e), "display": f"{s}-{e}"})
                    except ValueError:
                        continue

                # 3. Проверка на конкретные числа (строго цифры)
                elif arg.isdigit():
                    n = int(arg)
                    if 1 <= n <= 36:
                        temp_new_bets.append({"type": "number", "amount": amount, "value": n, "display": str(n)})

                # Если аргумент не подошел ни под одно правило (например "привет"), он просто игнорируется

            if not temp_new_bets:
                return  # Ставка не делается, если ни один аргумент не прошел проверку

            user_balance = await get_balance(user_id)
            icon = get_currency_icon()
            total_cost = len(temp_new_bets) * amount

            if user_balance < total_cost:
                can_afford = user_balance // amount
                if can_afford <= 0:
                    return await message.reply(f"Недостаточно {icon}!")
                temp_new_bets = temp_new_bets[:can_afford]
                total_cost = len(temp_new_bets) * amount

            await add_balance(user_id, -total_cost)

            mention = get_styled_mention(message.from_user)
            user_game_data = game["bets"].setdefault(user_id, {"items": [], "mention": mention})
            user_game_data["items"].extend(temp_new_bets)

            if game["start_time"] == 0:
                game["start_time"] = time.time() + 15

            confirm_lines = [f"Ставка принята: {mention} {amount} {icon} на {b['display']}" for b in temp_new_bets]

            for i in range(0, len(confirm_lines), 20):
                chunk = "\n".join(confirm_lines[i:i + 20])
                await message.answer(chunk, parse_mode="HTML")
                if i + 20 < len(confirm_lines):
                    await asyncio.sleep(0.3)
# ВЫНОСИМ СЛОВАРЬ ИЗ ФУНКЦИИ (чтобы не пересоздавать его каждую игру)
STICKER_MAP = {
    0: "CAACAgIAAxkBAAEQXcBpeqZEgxEU2tiUPeyDBIRXEnHYSQACMXEAAsGPqEvgtLCZn60BCTgE",
    1: "CAACAgIAAxkBAAEQXbJpeoOHpIEOtz18xXYtUmm0TmdAiQACYm0AAsV_qUvwV2I-O_92MzgE",
    2: "CAACAgIAAxkBAAEQYANpe9F6lzrE8IFbnhectUO2LoTM3QACu3AAAmt8qUuMHj22bDK7hDgE",
    3: "CAACAgIAAxkBAAEQX_Npe9F1lP4qfS3rAAGpODj0GZqdx40AAn9rAAKGzalL-TYQexywcy04BA",
    4: "CAACAgIAAxkBAAEQX-Jpe9Dx0qYPYLRF7DBLoy2cZWEnagACGWwAAgmWqEvDac6OXAABYnY4BA",
    5: "CAACAgIAAxkBAAEQYAlpe9F7qr1p3Woo50XN-XItV4aVOQACaG8AAvZ0qUs10WCEkqxX3DgE",
    6: "CAACAgIAAxkBAAEQX9hpe9CWu5vOlGy62cPPJb2bquJ3jgACInAAAkkgqUum3rYhVGMOYzgE",
    7: "CAACAgIAAxkBAAEQX9Bpe9BL5vM6ApenT43CWRN86gNGvgACpmUAAgxQsEvOOrqMWzDs9zgE",
    8: "CAACAgIAAxkBAAEQX9xpe9C5onkGvqIFItLSRGtAYMtDAQACc2kAAo0yqUsreLPxA-J-aTgE",
    9: "CAACAgIAAxkBAAEQX9Zpe9CCpQaRgDCxhEtTj7lKSO8VcAACg2YAArU-qUvBsA5QppMYBDgE",
    10: "CAACAgIAAxkBAAEQX_Zpe9F2AUWtvi-MOcQbQwzwOnifUwACCGwAAn9KqEtl9f_8GfnALDgE",
    11: "CAACAgIAAxkBAAEQX_1pe9F4qoUGFhHbKM1_Jc-EX_7mAwAC3msAAjl-qUtgCWpsiik4pDgE",
    12: "CAACAgIAAxkBAAEQXbBpeoJy-Gyw8EDx2wLa6xaUKdSdYwACc3cAAqZkqEsZBYHZtb4HsDgE",
    13: "CAACAgIAAxkBAAEQX85pe9A-BxpfX8EoImybMJxPXQTHRQAC9WUAAqUtsEu4A_dYVBl3EzgE",
    14: "CAACAgIAAxkBAAEQX9Jpe9BhUv8NPxt3iLNg_3mp5ZxsgAACaHUAAm06qUubaUhHHkRQtDgE",
    15: "CAACAgIAAxkBAAEQX-Rpe9EbwURz37Sw5b9zlpc9amOhFwACXnIAArg5qUueqto_IaZInTgE",
    16: "CAACAgIAAxkBAAEQX_ppe9F3o3Y54Czv8Jhk7rttFbh3qQAC3nQAAl2LqEti203L-GHZ8TgE",
    17: "CAACAgIAAxkBAAEQXb5peqYTsUL_gKXumjlD3-QDGqCJFAAC-XEAA8qoSzy-pE02t_7DOAQ",
    18: "CAACAgIAAxkBAAEQX_Rpe9F24unPigvU8JI-dG59acsH_gACu3EAApaoqUt4-NurUHdQCzgE",
    19: "CAACAgIAAxkBAAEQYAJpe9F62oiZaZRyzPMAAfM294r1akEAAtNvAAIUb6hLOIQHWBKuvrA4BA",
    20: "CAACAgIAAxkBAAEQX-ppe9EhbvY6sGHd1Hw6iTdwSPCsyQACmmMAAn-tqUuIolA0hUdGuzgE",
    21: "CAACAgIAAxkBAAEQX-hpe9EgyqfP7uE02yuiJYrjtNIZtQACDnkAAkJhqEsh2VgC776rRTgE",
    22: "CAACAgIAAxkBAAEQX9Rpe9Bxu4-hyiR5M9pZc2ZSPsSlLQAConUAAlt4qEue2yWiPIl8RTgE",
    23: "CAACAgIAAxkBAAEQX_lpe9F327-dKhLw7mw99TnbTlvEHwACxXEAAnmNqEsZVFvH7_y5lzgE",
    24: "CAACAgIAAxkBAAEQWvNpeUApDbVYFbfaye8zFvoRC1DVLgAC4nkAArFxsEu3KApsLo6nfDgE",
    25: "CAACAgIAAxkBAAEQX-Zpe9Ee-pGvirreqG6q7MoHkp4q0AACf3MAAkiqqUt2dUbW8-Qg9DgE",
    26: "CAACAgIAAxkBAAEQX8xpe9AwHt_q_vRcDictDW92cZnfqQACPmsAAv_5sUuGhpKQfUxwwDgE",
    27: "CAACAgIAAxkBAAEQX_9pe9F59AABiZ15ygNuaPsxr4FgSsIAAj1tAAKY9ahL8AhjC7wZ8W04BA",
    28: "CAACAgIAAxkBAAEQX8ppe9AbSlOQyF_RpPLLJI1l0McRPQACu2wAAiUkqEsTMHlkQoOOyzgE",
    29: "CAACAgIAAxkBAAEQX-xpe9EjeQdTk3RmXWb8M3AbNhiIWgAC324AAh7VqUte0Uc3aofKwzgE",
    30: "CAACAgIAAxkBAAEQX-5pe9FrGJrnujiib6kozWfO9W7Q_gAC3G0AAjoGsEumvpK88ed0uzgE",
    31: "CAACAgIAAxkBAAEQX_tpe9F3FO3594A2ekuO95jiPCERvAACFm8AAmRmqUvFyBdW_r3jBDgE",
    32: "CAACAgIAAxkBAAEQYAZpe9F7gnfFVNHrVLYOFCOC7IgvmQACY3EAAlBCsUunVsFT9ROxzzgE",
    33: "CAACAgIAAxkBAAEQYAVpe9F6B3Ie5WBEOIlYEIZ8xmdu5wACUXIAAiibsUu7t8mandGQuTgE",
    34: "CAACAgIAAxkBAAEQX-Bpe9Dt-43xw98RnE75FDiv_16Q2gACaXcAAq6jsUsGQj_3FSUlEzgE",
    35: "CAACAgIAAxkBAAEQYAABaXvReTMUZX4z8Ih4jYPTodALsrMAAr1oAALNl6hLC2JQEDSBpQ04BA",
    36: "CAACAgIAAxkBAAEQX95pe9DSuhvn43e6FY_Yin-ySANqpAACUW8AAi9JqEuBxymhD-OS3TgE"
}


@router.message(F.text.lower() == "го", F.chat.type != "private")
async def start_roulette(message: Message, bot: Bot):
    chat_id = message.chat.id

    if not await is_games_enabled(chat_id):
        return

    if chat_id not in games or not games[chat_id]["bets"]:
        return
    game = games[chat_id]

    chat_lock = chat_locks.setdefault(chat_id, asyncio.Lock())
    if chat_lock.locked():
        return

    if message.from_user.id not in game["bets"]:
        return await message.reply("❌ Вы не можете запустить рулетку, так как не сделали ставку!")

    remaining = game["start_time"] - time.time()
    if remaining > 0:
        return await message.answer(f"⏳ Осталось еще {int(remaining)} сек.")

    async with chat_lock:
        game["is_running"] = True

        win_num = random.randint(0, 36)
        win_color = get_color(win_num)
        ball_emoji = "🟢" if win_num == 0 else ("🔴" if win_color == "🔴" else "⚫")

        await add_game_log(chat_id, win_num, win_color)

        all_lines = []
        winners_summary = []

        # --- РАСЧЕТ ВЫИГРЫШЕЙ ---
        for u_id, user_data in game["bets"].items():
            mention = user_data["mention"]
            total_win = 0

            await save_last_bet(u_id, user_data["items"])

            for b in user_data["items"]:
                amount_val = b['amount']
                # УБРАЛИ {icon} ИЗ ЭТОЙ СТРОКИ
                all_lines.append(f"{mention} {amount_val} на {b['display']}")

                win, mult = False, 0

                # Логика выигрыша (компактная запись)
                if b["type"] == "red" and win_color == "🔴":
                    win, mult = True, 2
                elif b["type"] == "black" and win_color == "⚫":
                    win, mult = True, 2
                elif b["type"] == "number" and b["value"] == win_num:
                    win, mult = True, 36
                elif b["type"] == "range":
                    start, end = b["value"]
                    if start <= win_num <= end:
                        diff = end - start + 1
                        win, mult = True, (36 / diff) * 0.98

                if win:
                    win_amt = int(amount_val * mult)
                    total_win += win_amt
                    # УБРАЛИ {icon} ИЗ ЭТОЙ СТРОКИ
                    winners_summary.append(f"{mention} выиграл {win_amt} на {b['display']}")

            if total_win > 0:
                await add_balance(u_id, total_win)
                await add_daily_win(u_id, total_win)

        # --- АНИМАЦИЯ (СТИКЕРЫ) ---
        s_id = STICKER_MAP.get(win_num)
        if s_id:
            try:
                sticker_msg = await message.answer_sticker(s_id)
                await asyncio.sleep(4.5)
                try:
                    await bot.delete_message(chat_id, sticker_msg.message_id)
                except Exception:  # Безопасный перехват
                    pass
            except Exception:  # Безопасный перехват
                await asyncio.sleep(2)

        # --- ЗАВЕРШЕНИЕ И ОЧИСТКА ---
        games.pop(chat_id, None)
        chat_locks.pop(chat_id, None)  # Очищаем замок, чтобы не было утечки памяти

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Повторить", callback_data="rebet"),
            InlineKeyboardButton(text="Удвоить", callback_data="double")
        ]])

        # Формируем текст с умным разделением на блоки (лимит 4096 символов)
        messages_to_send = []
        current_text = f"<b>Результаты рулетки: {win_num} {ball_emoji}</b>\n\n<b>Ставки:</b>\n"

        # Заполняем ставки
        for line in all_lines:
            if len(current_text) + len(line) > 3800:
                messages_to_send.append(current_text)
                current_text = "<b>Ставки (продолжение):</b>\n" + line + "\n"
            else:
                current_text += line + "\n"

        current_text += "\n<b>Победители:</b>\n"

        # Заполняем победителей
        if not winners_summary:
            current_text += "Никто не выиграл\n"
        else:
            for line in winners_summary:
                if len(current_text) + len(line) > 3800:
                    messages_to_send.append(current_text)
                    current_text = "<b>Победители (продолжение):</b>\n" + line + "\n"
                else:
                    current_text += line + "\n"

        # Добавляем финальный кусок текста в список отправки
        messages_to_send.append(current_text)

        # Отправляем все собранные сообщения
        for i, text_block in enumerate(messages_to_send):
            # Клавиатуру с кнопками цепляем только к самому последнему сообщению
            markup = kb if i == len(messages_to_send) - 1 else None

            await message.answer(text_block, parse_mode="HTML", reply_markup=markup)

            # Если это не последнее сообщение, делаем микро-паузу
            if i < len(messages_to_send) - 1:
                await asyncio.sleep(0.3)

@router.callback_query(F.data.in_(["rebet", "double"]))
async def fast_rebet_handler(callback: CallbackQuery):
    chat_id = callback.message.chat.id

    # 1. Проверяем, не отключили ли игры в чате (этого не было в оригинале)
    if not await is_games_enabled(chat_id):
        return await callback.answer("Игры в этом чате отключены!", show_alert=True)

    # 2. Сначала проверяем, не крутится ли рулетка, чтобы не дергать базу зря
    game = games.setdefault(chat_id, {"bets": {}, "start_time": 0, "is_running": False})
    if game["is_running"]:
        return await callback.answer("Рулетка уже крутится!", show_alert=True)

    user_id = callback.from_user.id

    # 3. Блокировка от случайных двойных нажатий (защита баланса от спама кнопкой)
    lock = user_locks.setdefault(user_id, asyncio.Lock())

    async with lock:
        # Внутри замка на всякий случай проверяем игру еще раз (вдруг она запустилась пока мы ждали очередь)
        if game["is_running"]:
            return await callback.answer("Рулетка уже крутится!", show_alert=True)

        # Теперь можно безопасно обращаться к БД
        last_bets = await get_last_bet(user_id)
        if not last_bets:
            return await callback.answer("Нет прошлых ставок!", show_alert=True)

        multiplier = 2 if callback.data == "double" else 1
        total_cost = sum(b['amount'] for b in last_bets) * multiplier

        if await get_balance(user_id) < total_cost:
            return await callback.answer("Недостаточно средств!", show_alert=True)

        # Списываем баланс
        await add_balance(user_id, -total_cost)

        mention = get_styled_mention(callback.from_user)
        u_data = game["bets"].setdefault(user_id, {"mention": mention, "items": []})

        if game["start_time"] == 0:
            game["start_time"] = time.time() + 15

        lines = []

        for b in last_bets:
            new_amt = b['amount'] * multiplier
            u_data["items"].append({
                "type": b["type"],
                "amount": new_amt,
                "display": b["display"],
                "value": b.get("value")
            })
            # УБРАЛИ {icon} ИЗ ЭТОЙ СТРОКИ
            lines.append(f"<b>{b['display']}</b> — {new_amt}")

        title = f"{mention} повторил ставки:" if multiplier == 1 else f"{mention} удвоил ставки:"
        await callback.answer("Ставки приняты!")

        # 4. Безопасная отправка (защита от лимита в 4096 символов)
        full_text = f"{title}\n" + "\n".join(lines)

        if len(full_text) > 4000:
            for i in range(0, len(lines), 30):
                chunk = lines[i:i + 30]
                if i == 0:
                    await callback.message.answer(f"{title}\n" + "\n".join(chunk), parse_mode="HTML")
                else:
                    await callback.message.answer("\n".join(chunk), parse_mode="HTML")
                await asyncio.sleep(0.3)
        else:
            await callback.message.answer(full_text, parse_mode="HTML")