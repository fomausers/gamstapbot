import asyncio
import re
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import (Message, ChatPermissions, InlineKeyboardMarkup,
                           InlineKeyboardButton, ChatMemberOwner, ChatMemberAdministrator, CallbackQuery)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ВСЕ ИМПОРТЫ ИЗ БАЗЫ В ОДНОМ МЕСТЕ
from database import (
    set_filter, get_filter, find_user_by_username,
    get_banlist_data, add_to_banlist, remove_from_banlist
)

router = Router()
scheduler = AsyncIOScheduler()

# Константа количества юзеров на страницу
USERS_PER_PAGE = 25


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_mention(user_id: int, name: str):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def parse_time(text: str):
    units = {
        'мин': ['мин', 'минут', 'минуту', 'минуты'],
        'час': ['час', 'часа', 'часов'],
        'ден': ['ден', 'день', 'дня', 'дней', 'сут']
    }
    match = re.search(r'(\d+)\s*([а-я]+)', text.lower())
    if not match:
        return timedelta(hours=1)
    count = int(match.group(1))
    unit_str = match.group(2)
    for key, values in units.items():
        if any(unit_str.startswith(v) for v in values):
            if key == 'мин': return timedelta(minutes=count)
            if key == 'час': return timedelta(hours=count)
            if key == 'ден': return timedelta(days=count)
    return timedelta(hours=1)


async def is_admin(message: Message):
    if message.chat.type == "private": return False
    try:
        member = await message.chat.get_member(message.from_user.id)
        return isinstance(member, (ChatMemberOwner, ChatMemberAdministrator))
    except:
        return False


async def get_target(message: Message, bot: Bot):
    # 1️⃣ Реплай — самый надёжный способ
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        return user.id, user.first_name

    text = message.text or ""

    # 2️⃣ Поиск через entities
    if message.entities:
        for entity in message.entities:

            # 🔹 Обычное @username
            if entity.type == "mention":
                username = text[entity.offset:entity.offset + entity.length].replace("@", "")

                # Сначала пробуем найти в БД
                db_user = await find_user_by_username(username)
                if db_user:
                    return db_user["user_id"], db_user["full_name"]

                # Если нет в БД — пробуем через Telegram
                try:
                    user = await bot.get_chat(f"@{username}")
                    return user.id, user.first_name
                except:
                    continue

            # 🔹 Текстовое упоминание (через выбор пользователя)
            if entity.type == "text_mention":
                return entity.user.id, entity.user.first_name

    # 3️⃣ Поиск числового ID
    ids = re.findall(r'\d{7,15}', text)
    if ids:
        target_id = int(ids[0])
        try:
            member = await bot.get_chat_member(message.chat.id, target_id)
            return member.user.id, member.user.first_name
        except:
            return target_id, "Пользователь"

    return None, None

# --- СИСТЕМА НАКАЗАНИЙ ---

async def uncheck_mute(chat_id: int, user_id: int, name: str, bot: Bot):
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_other_messages=True,
                can_add_web_page_previews=True, can_send_polls=True
            )
        )
        await bot.send_message(chat_id, f"🔔 {get_mention(user_id, name)}, время мута истекло!", parse_mode="HTML")
    except:
        pass

@router.message(F.text.lower().startswith(("размут", "разбан")))
async def unmute_unban_handler(message: Message, bot: Bot):
    if not await is_admin(message):
        return

    target_id, target_name = await get_target(message, bot)

    if not target_id:
        return await message.answer(
            "❓ <b>Кого освобождаем?</b>\nИспользуйте реплей или @юзер",
            parse_mode="HTML"
        )

    user_mention = get_mention(target_id, target_name)
    is_unban = message.text.lower().startswith("разбан")

    # --- Проверка статуса ---
    try:
        member = await bot.get_chat_member(message.chat.id, target_id)

        if is_unban:
            if member.status not in ("kicked", "left"):
                return await message.answer(
                    f"ℹ️ {user_mention} пользователь не в бане",
                    parse_mode="HTML"
                )
        else:
            if member.status != "restricted" or member.can_send_messages:
                return await message.answer(
                    f"ℹ️ {user_mention} пользователь не в муте",
                    parse_mode="HTML"
                )

    except Exception as e:
        logging.warning(f"Ошибка проверки статуса: {e}")

    # --- Парсинг причины ---
    clean_text = re.sub(
        r'^(размут|разбан)',
        '',
        message.text,
        flags=re.IGNORECASE
    ).strip()

    clean_text = re.sub(r'^(@\w+|\d{7,15})\s*', '', clean_text).strip()
    reason = clean_text if clean_text else "Причина не указана"

    try:
        if is_unban:
            await bot.unban_chat_member(
                message.chat.id,
                target_id,
                only_if_banned=True
            )
            await remove_from_banlist(target_id)
            action_text = "разбанен"
            emoji = "🦸‍♂️"

        else:
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_other_messages=True,
                    can_send_polls=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_add_web_page_previews=True
                )
            )
            action_text = "размучен"
            emoji = "🔊"

        admin_mention = get_mention(
            message.from_user.id,
            message.from_user.first_name
        )

        await message.answer(
            f"{emoji} {user_mention} {action_text} "
            f"администратором {admin_mention}\n"
            f"<b>Причина:</b>\n<blockquote>{reason}</blockquote>",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Ошибка при снятии наказания: {e}")
        await message.answer("❌ Ошибка выполнения. Проверьте права бота.")


# --- БАНЛИСТ С ПАГИНАЦИЕЙ ---

def get_banlist_kb(page: int, total_pages: int):
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.add(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"banlist_page:{page - 1}"))
    if page < total_pages - 1:
        builder.add(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"banlist_page:{page + 1}"))
    return builder.as_markup()


@router.message(Command("банлист"))
async def show_banlist(message: Message):
    if not await is_admin(message):
        return
    await render_banlist(message, page=0)


@router.callback_query(F.data.startswith("banlist_page:"))
async def process_banlist_page(call: CallbackQuery):
    if not await is_admin(call.message):
        return await call.answer("Недостаточно прав.", show_alert=True)

    try:
        page = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        return await call.answer("Ошибка страницы.", show_alert=True)

    await render_banlist(call.message, page=page, is_callback=True)
    await call.answer()


async def render_banlist(message: Message, page: int, is_callback: bool = False):
    bans = await get_banlist_data()

    if not bans:
        text = "<b>📜 БАН ЛИСТ</b>\n\nСписок банов пуст."
        try:
            if is_callback:
                await message.edit_text(text, parse_mode="HTML")
            else:
                await message.answer(text, parse_mode="HTML")
        except:
            pass
        return

    total_pages = (len(bans) + USERS_PER_PAGE - 1) // USERS_PER_PAGE

    # 🔒 Защита от выхода за границы
    page = max(0, min(page, total_pages - 1))

    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    curr_bans = bans[start:end]

    text = f"<b>📜 БАН ЛИСТ</b>\n"
    text += f"<i>Страница {page + 1} из {total_pages}</i>\n\n"

    for i, ban in enumerate(curr_bans, start + 1):
        text += (
            f"<b>{i}.</b> {get_mention(ban['user_id'], ban['user_name'])}\n"
            f"└ ⏳ Срок: {ban['duration']}\n"
            f"└ 👮 Админ: {get_mention(ban['admin_id'], ban['admin_name'])}\n\n"
        )

    # --- Клавиатура ---
    builder = InlineKeyboardBuilder()

    if page > 0:
        builder.button(text="⬅️ Назад", callback_data=f"banlist_page:{page - 1}")

    builder.button(text="🔄 Обновить", callback_data=f"banlist_page:{page}")

    if page < total_pages - 1:
        builder.button(text="Вперёд ➡️", callback_data=f"banlist_page:{page + 1}")

    builder.adjust(3)

    kb = builder.as_markup()

    try:
        if is_callback:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Ошибка отображения банлиста: {e}")


# --- ИНФОРМАЦИОННЫЕ КОМАНДЫ ---

@router.message(F.text.lower() == "кто админ")
async def get_admins_list(message: Message):
    try:
        admins = await message.chat.get_administrators()
        human_admins = [admin for admin in admins if not admin.user.is_bot]
        owner_text = "⭐⭐⭐⭐⭐ <b>Создатель</b>\n"
        admins_text = "\n⭐⭐⭐⭐ <b>Администраторы</b>\n"
        has_admins = False
        for admin in human_admins:
            mention = get_mention(admin.user.id, admin.user.first_name)
            if isinstance(admin, ChatMemberOwner):
                owner_text += f"👨🏻‍💼 {mention}\n"
            else:
                admins_text += f"🦸 {mention}\n"
                has_admins = True
        res = f"<b>Администрация {message.chat.title}</b>\n\n{owner_text}"
        if has_admins: res += admins_text
        await message.answer(res, parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка.")


@router.message(Command("help", "помощь"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>🛠 Список команд:</b>\n\n• <code>мут 10 мин @user</code>\n• <code>бан 1 час @user</code>\n• <code>размут/разбан</code>\n• <code>банлист</code>\n• <code>кто админ</code>",
        parse_mode="HTML")


# --- ФИЛЬТРЫ И СЕРВИСНЫЕ СООБЩЕНИЯ ---

@router.message(F.new_chat_members | F.left_chat_member)
async def clean_service_messages(message: Message):
    try:
        await message.delete()
    except:
        pass


@router.message(F.text.in_(["-чаты", "+чаты"]))
async def toggle_filters(message: Message):
    if not await is_admin(message): return
    val = 1 if message.text == "-чаты" else 0
    await set_filter(message.chat.id, "anti_link", val)
    await message.answer("🚫 Ссылки запрещены." if val else "✅ Ссылки разрешены.")


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def check_filters(message: Message, bot: Bot):
    if await is_admin(message): return
    if await get_filter(message.chat.id, "anti_link") == 1:
        if "t.me/" in (message.text or "") or "@" in (message.text or ""):
            try:
                await message.delete()
                until = datetime.now() + timedelta(minutes=15)
                await bot.restrict_chat_member(message.chat.id, message.from_user.id,
                                               permissions=ChatPermissions(can_send_messages=False), until_date=until)
                scheduler.add_job(uncheck_mute, 'date', run_date=until,
                                  args=[message.chat.id, message.from_user.id, message.from_user.first_name, bot])
            except:
                pass


@router.message(Command("help", "помощь"))
async def cmd_help(message: Message):
    help_text = (
        "<b>🛠 Список команд бота-модератора</b>\n\n"

        "<b>🛡 Модерация:</b>\n"
        "• <code>мут (время) @юзер (причина)</code> — ограничить чат\n"
        "• <code>бан (время) @юзер (причина)</code> — заблокировать\n"
        "• <code>размут / разбан</code> — снять наказание (реплеем или @юзер)\n"
        "• <code>-смс</code> — удалить сообщение (ответом на него)\n\n"

        "<b>⚙️ Настройки фильтров:</b>\n"
        "• <code>-чаты</code> / <code>+чаты</code> — запретить/разрешить ссылки\n"
        "• <code>-каналы</code> / <code>+каналы</code> — запретить сообщения от каналов\n\n"

        "<b>ℹ️ Информация:</b>\n"
        "• <code>кто админ</code> — список администрации чата\n"
        "• <code>обновить чат</code> — обновить данные админов\n"
        "• <code>/start</code> — запуск бота в личке\n\n"

        "<i>Пример мута:</i>\n"
        "<code>мут 60 мин @username спам в чате</code>"
    )

    await message.answer(help_text, parse_mode="HTML")
