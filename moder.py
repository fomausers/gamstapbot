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
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name

    if message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                return entity.user.id, entity.user.first_name
            if entity.type == "mention":
                username = message.text[entity.offset:entity.offset + entity.length].replace("@", "")
                try:
                    chat_member = await bot.get_chat_member(message.chat.id, f"@{username}")
                    return chat_member.user.id, chat_member.user.first_name
                except:
                    db_user = await find_user_by_username(username)
                    if db_user:
                        return db_user['user_id'], db_user['full_name']

    ids = re.findall(r'\d{7,}', message.text)
    if ids:
        target_id = int(ids[0])
        try:
            u = await bot.get_chat_member(message.chat.id, target_id)
            return u.user.id, u.user.first_name
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

@router.message(F.text.lower().regexp(r"^(мут|бан)"))
async def restrict_handler(message: Message, bot: Bot):
    if not await is_admin(message): return
    target_id, target_name = await get_target(message, bot)

    if not target_id:
        return await message.answer("❓ <b>Кого наказываем?</b>\nИспользуйте реплей или @юзер", parse_mode="HTML")
    if target_id == message.from_user.id:
        return await message.answer("❌ Нельзя наказать самого себя.")

    try:
        member = await message.chat.get_member(target_id)
        if member.status in ["administrator", "creator"]:
            return await message.answer("❌ Нельзя наказывать администраторов.")
    except: pass

    duration = parse_time(message.text)
    until_date = datetime.now() + duration

    # Извлечение причины
    reason = "Не указана"
    match = re.search(r'(\d+)\s*(мин|час|ден|сут)[а-я]*', message.text.lower())
    if match:
        after_time = message.text[match.end():].strip()
        reason_clean = re.sub(r'^(@\w+|\d{7,})\s*', '', after_time).strip()
        if reason_clean: reason = reason_clean

    is_ban = message.text.lower().startswith("бан")
    time_str = f"{int(duration.total_seconds() // 60)} мин."

    try:
        if is_ban:
            await bot.ban_chat_member(message.chat.id, target_id, until_date=until_date)
            await add_to_banlist(target_id, target_name, message.from_user.id, message.from_user.first_name, time_str)
            await message.answer(f"🚫 {get_mention(target_id, target_name)} <b>забанен</b> на {time_str}\n<b>Причина:</b>\n<blockquote>{reason}</blockquote>", parse_mode="HTML")
        else:
            await bot.restrict_chat_member(message.chat.id, target_id, permissions=ChatPermissions(can_send_messages=False), until_date=until_date)
            scheduler.add_job(uncheck_mute, 'date', run_date=until_date, args=[message.chat.id, target_id, target_name, bot])
            await message.answer(f"🔇 {get_mention(target_id, target_name)} в муте на {time_str}\n<b>Причина:</b>\n<blockquote>{reason}</blockquote>", parse_mode="HTML")
    except Exception as e:
        await message.answer("❌ Ошибка прав бота.")


@router.message(F.text.lower().startswith(("размут", "разбан")))
async def unmute_unban_handler(message: Message, bot: Bot):
    if not await is_admin(message): return

    target_id, target_name = await get_target(message, bot)
    if not target_id:
        return await message.answer("❓ <b>Кого освобождаем?</b>\nИспользуйте реплей или @юзер", parse_mode="HTML")

    user_mention = get_mention(target_id, target_name)
    is_unban = "разбан" in message.text.lower()

    # --- ПРОВЕРКА ТЕКУЩЕГО СТАТУСА ---
    try:
        member = await bot.get_chat_member(message.chat.id, target_id)

        if is_unban:
            # Если статус не 'kicked' (забанен), значит он не в бане
            if member.status != "kicked":
                return await message.answer(f"ℹ️ {user_mention} пользователь не является в бане", parse_mode="HTML")
        else:
            # Если это обычный участник и у него есть право слать сообщения — он не в муте
            # (Статус 'restricted' означает наличие ограничений)
            if member.status != "restricted" or getattr(member, 'can_send_messages', True):
                return await message.answer(f"ℹ️ {user_mention} пользователь не в муте", parse_mode="HTML")

    except Exception as e:
        # Если пользователя никогда не было в чате, Telegram может выдать ошибку
        logging.warning(f"Не удалось проверить статус при разбане: {e}")

    # --- ПАРСИНГ ПРИЧИНЫ ---
    clean_text = re.sub(r'^(размут|разбан)', '', message.text, flags=re.IGNORECASE).strip()
    clean_text = re.sub(r'^(@\w+|\d{7,})\s*', '', clean_text).strip()

    reason = clean_text if clean_text else "Причина не указана"

    try:
        if is_unban:
            await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
            await remove_from_banlist(target_id)
            res_action = "разбанен"
            emoji = "🦸‍♂️"
        else:
            await bot.restrict_chat_member(
                message.chat.id, target_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_other_messages=True, can_send_polls=True,
                    can_send_audios=True, can_send_documents=True, can_send_photos=True,
                    can_send_videos=True, can_add_web_page_previews=True
                )
            )
            res_action = "размучен"
            emoji = "🔊"

        admin_mention = get_mention(message.from_user.id, message.from_user.first_name)

        await message.answer(
            f"{emoji} {user_mention} {res_action} администратором {admin_mention}\n"
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
    if not await is_admin(message): return
    await render_banlist(message, 0)

@router.callback_query(F.data.startswith("banlist_page:"))
async def process_banlist_page(call: CallbackQuery):
    page = int(call.data.split(":")[1])
    await render_banlist(call.message, page, is_callback=True)
    await call.answer()

async def render_banlist(message: Message, page: int, is_callback=False):
    bans = await get_banlist_data()
    if not bans:
        text = "<b>Список банов пуст.</b>"
        return await (message.edit_text(text, parse_mode="HTML") if is_callback else message.answer(text, parse_mode="HTML"))

    total_pages = (len(bans) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    curr_bans = bans[page * USERS_PER_PAGE : (page + 1) * USERS_PER_PAGE]

    text = f"<b>📜 БАН ЛИСТ (Страница {page + 1}/{total_pages})</b>\n\n"
    for i, ban in enumerate(curr_bans, page * USERS_PER_PAGE + 1):
        text += f"<b>{i}.</b> забанен {get_mention(ban['user_id'], ban['user_name'])} (на {ban['duration']})\n└ админом {get_mention(ban['admin_id'], ban['admin_name'])}\n\n"

    kb = get_banlist_kb(page, total_pages)
    if is_callback: await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else: await message.answer(text, reply_markup=kb, parse_mode="HTML")

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
            if isinstance(admin, ChatMemberOwner): owner_text += f"👨🏻‍💼 {mention}\n"
            else:
                admins_text += f"🦸 {mention}\n"
                has_admins = True
        res = f"<b>Администрация {message.chat.title}</b>\n\n{owner_text}"
        if has_admins: res += admins_text
        await message.answer(res, parse_mode="HTML")
    except: await message.answer("❌ Ошибка.")

@router.message(Command("help", "помощь"))
async def cmd_help(message: Message):
    await message.answer("<b>🛠 Список команд:</b>\n\n• <code>мут 10 мин @user</code>\n• <code>бан 1 час @user</code>\n• <code>размут/разбан</code>\n• <code>банлист</code>\n• <code>кто админ</code>", parse_mode="HTML")

# --- ФИЛЬТРЫ И СЕРВИСНЫЕ СООБЩЕНИЯ ---

@router.message(F.new_chat_members | F.left_chat_member)
async def clean_service_messages(message: Message):
    try: await message.delete()
    except: pass

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
                await bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                scheduler.add_job(uncheck_mute, 'date', run_date=until, args=[message.chat.id, message.from_user.id, message.from_user.first_name, bot])
            except: pass

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

