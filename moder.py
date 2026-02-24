import asyncio
import re
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import (Message, ChatPermissions, InlineKeyboardMarkup,
                           InlineKeyboardButton, ChatMemberOwner, ChatMemberAdministrator)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Импортируем функцию поиска из твоей базы
from database import set_filter, get_filter, find_user_by_username

router = Router()
scheduler = AsyncIOScheduler()


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
    """Улучшенный поиск цели: Реплей -> Entity -> База данных -> ID"""
    target_id = None
    target_name = "пользователь"

    # 1. Реплей
    if message.reply_to_message:
        return message.reply_to_message.from_user.id, message.reply_to_message.from_user.first_name

    # 2. Упоминание (Entity)
    if message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                return entity.user.id, entity.user.first_name
            if entity.type == "mention":
                username = message.text[entity.offset:entity.offset + entity.length].replace("@", "")

                # Сначала пробуем найти в самом чате (если юзер активен)
                try:
                    chat_member = await bot.get_chat_member(message.chat.id, f"@{username}")
                    return chat_member.user.id, chat_member.user.first_name
                except:
                    # Если бот не видит его в чате, ищем в нашей базе данных
                    db_user = await find_user_by_username(username)
                    if db_user:
                        return db_user['user_id'], db_user['full_name']

    # 3. Поиск ID в тексте
    ids = re.findall(r'\d{7,}', message.text)
    if ids:
        target_id = int(ids[0])
        try:
            u = await bot.get_chat_member(message.chat.id, target_id)
            target_name = u.user.first_name
        except:
            pass

    return target_id, target_name


# --- АВТОМАТИЧЕСКОЕ СНЯТИЕ ---

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


# --- ХЕНДЛЕРЫ ---

@router.message(F.text.lower().regexp(r"^(мут|бан)"))
async def restrict_handler(message: Message, bot: Bot):
    if not await is_admin(message): return

    target_id, target_name = await get_target(message, bot)

    if not target_id:
        return await message.answer("❓ <b>Кого наказываем?</b>\nИспользуйте реплей или @юзер", parse_mode="HTML")

    if target_id == message.from_user.id:
        return await message.answer("❌ Нельзя наказать самого себя.")

    # Проверка на админа
    try:
        member = await message.chat.get_member(target_id)
        if member.status in ["administrator", "creator"]:
            return await message.answer("❌ Нельзя наказывать администраторов.")
    except:
        pass

    # --- ПАРСИНГ ВРЕМЕНИ И ПРИЧИНЫ ---
    duration = parse_time(message.text)
    until_date = datetime.now() + duration

    # Извлекаем причину: берем весь текст и отрезаем команду и упоминание
    # Ищем текст после @username или после ID
    text_parts = message.text.split(maxsplit=3)
    # Обычно формат: мут 10 мин @user Причина...
    # Если это реплей: мут 10 мин Причина...

    reason = "Не указана"
    if len(text_parts) > 2:
        # Пытаемся найти всё, что идет после упоминания или времени
        # Самый простой способ — найти последнее вхождение упоминания/времени и взять текст после него
        full_text = message.text
        # Ищем, где заканчивается время/юзернейм (примерно)
        match = re.search(r'(\d+)\s*(мин|час|ден|сут)[а-я]*', full_text.lower())
        if match:
            # Берем текст после указания времени и очищаем от возможных упоминаний @user
            after_time = full_text[match.end():].strip()
            # Убираем юзернейм из начала причины, если он там есть
            reason_clean = re.sub(r'^@\w+\s*', '', after_time).strip()
            if reason_clean:
                reason = reason_clean

    is_ban = message.text.lower().startswith("бан")

    # Считаем минуты для вывода (для краткости)
    total_minutes = int(duration.total_seconds() // 60)
    time_str = f"{total_minutes} мин."

    try:
        if is_ban:
            await bot.ban_chat_member(message.chat.id, target_id, until_date=until_date)
            await message.answer(
                f"🚫 {get_mention(target_id, target_name)} <b>забанен</b> на {time_str}\n"
                f"<b>Причина:</b>\n<blockquote>{reason}</blockquote>",
                parse_mode="HTML"
            )
        else:
            await bot.restrict_chat_member(
                message.chat.id, target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            # Планируем авто-размут (уведомление)
            scheduler.add_job(uncheck_mute, 'date', run_date=until_date,
                              args=[message.chat.id, target_id, target_name, bot])

            await message.answer(
                f"🔇 {get_mention(target_id, target_name)} в муте на {time_str}\n"
                f"<b>Причина:</b>\n<blockquote>{reason}</blockquote>",
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка прав. Проверьте, что бот — админ.")


@router.message(F.text.lower().startswith(("размут", "разбан")))
async def unmute_unban_handler(message: Message, bot: Bot):
    if not await is_admin(message): return
    target_id, target_name = await get_target(message, bot)

    if not target_id:
        return await message.answer("❓ Кого освобождаем?")

    try:
        if "разбан" in message.text.lower():
            await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
            res = "разбанен"
        else:
            await bot.restrict_chat_member(message.chat.id, target_id, permissions=ChatPermissions(
                can_send_messages=True, can_send_other_messages=True, can_send_polls=True,
                can_send_audios=True, can_send_documents=True, can_send_photos=True,
                can_send_videos=True, can_add_web_page_previews=True
            ))
            res = "размучен"
        await message.answer(f"🦸‍♂️ {get_mention(target_id, target_name)} {res}!", parse_mode="HTML")
    except:
        await message.answer("❌ Ошибка выполнения.")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (ОЧИСТКА, ФИЛЬТРЫ) ---

@router.message(F.new_chat_members | F.left_chat_member | F.new_chat_title | F.new_chat_photo | F.delete_chat_photo)
async def clean_service_messages(message: Message):
    try:
        await message.delete()
    except:
        pass


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, bot: Bot):
    bot_info = await bot.get_me()
    builder = InlineKeyboardBuilder()

    # Кнопка добавления в чат
    builder.row(InlineKeyboardButton(
        text="➕ Добавить в чат",
        url=f"https://t.me/{bot_info.username}?startgroup=true")
    )

    await message.answer(
        f"Привет, {message.from_user.first_name}! Я бот-модератор.\n\n"
        "Добавь меня в свой чат и дай права администратора, чтобы я мог следить за порядком.\n\n"
        "📖 Список всех доступных команд можно посмотреть, написав: <b>/help</b> или <b>помощь</b>.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@router.message(F.text == "-смс")
async def delete_sms(message: Message):
    if not await is_admin(message): return
    if message.reply_to_message:
        try:
            await message.reply_to_message.delete()
            await message.delete()
        except:
            pass


@router.message(F.text.lower() == "кто админ")
async def get_admins_list(message: Message):
    try:
        admins = await message.chat.get_administrators()
        # Фильтруем только людей
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

        # Собираем итоговое сообщение
        full_text = f"<b>Администрация чата {message.chat.title}</b>\n\n"
        full_text += owner_text

        if has_admins:
            full_text += admins_text

        await message.answer(full_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка в списке админов: {e}")
        await message.answer("❌ Ошибка получения списка. Проверьте мои права.")


@router.message(F.text.in_(["-чаты", "+чаты", "-каналы", "+каналы"]))
async def toggle_filters(message: Message):
    if not await is_admin(message): return
    chat_id = message.chat.id
    if message.text == "-чаты":
        await set_filter(chat_id, "anti_link", 1)
        await message.answer("🚫 Ссылки запрещены.")
    elif message.text == "+чаты":
        await set_filter(chat_id, "anti_link", 0)
        await message.answer("✅ Ссылки разрешены.")
    # ... остальные фильтры по аналогии


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def check_filters(message: Message, bot: Bot):
    if await is_admin(message): return
    chat_id = message.chat.id
    content = message.text or message.caption or ""

    if await get_filter(chat_id, "anti_link") == 1 and ("t.me/" in content or "@" in content):
        try:
            await message.delete()
            until = datetime.now() + timedelta(minutes=15)
            await bot.restrict_chat_member(chat_id, message.from_user.id,
                                           permissions=ChatPermissions(can_send_messages=False), until_date=until)
            scheduler.add_job(uncheck_mute, 'date', run_date=until,
                              args=[chat_id, message.from_user.id, message.from_user.first_name, bot])
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

