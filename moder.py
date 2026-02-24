import re
import logging
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, ChatPermissions,
    ChatMemberOwner, ChatMemberAdministrator,
    CallbackQuery
)
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    set_filter, get_filter, find_user_by_username,
    get_banlist_data, add_to_banlist, remove_from_banlist
)

router = Router()
scheduler = AsyncIOScheduler()

USERS_PER_PAGE = 25

FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_send_polls=True
)

# =========================================================
# ================= ВСПОМОГАТЕЛЬНЫЕ =======================
# =========================================================

def get_mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def parse_time(text: str) -> timedelta:
    match = re.search(r'(\d+)\s*(мин|час|дн|ден|сут)', text.lower())
    if not match:
        return timedelta(hours=1)

    value = int(match.group(1))
    unit = match.group(2)

    if "мин" in unit:
        return timedelta(minutes=value)
    if "час" in unit:
        return timedelta(hours=value)
    return timedelta(days=value)


async def is_admin(message: Message) -> bool:
    if message.chat.type == "private":
        return False
    try:
        member = await message.chat.get_member(message.from_user.id)
        return isinstance(member, (ChatMemberOwner, ChatMemberAdministrator))
    except Exception:
        return False


async def get_target(message: Message, bot: Bot):
    if message.reply_to_message:
        u = message.reply_to_message.from_user
        return u.id, u.first_name

    text = message.text or ""

    if message.entities:
        for entity in message.entities:
            if entity.type == "text_mention":
                return entity.user.id, entity.user.first_name

            if entity.type == "mention":
                username = text[entity.offset:entity.offset + entity.length].replace("@", "")
                db_user = await find_user_by_username(username)
                if db_user:
                    return db_user["user_id"], db_user["full_name"]

                try:
                    user = await bot.get_chat(f"@{username}")
                    return user.id, user.first_name
                except Exception:
                    continue

    ids = re.findall(r'\d{7,15}', text)
    if ids:
        return int(ids[0]), "Пользователь"

    return None, None


# =========================================================
# =================== СИСТЕМА НАКАЗАНИЙ ===================
# =========================================================

async def uncheck_mute(chat_id: int, user_id: int, name: str, bot: Bot):
    try:
        await bot.restrict_chat_member(chat_id, user_id, permissions=FULL_PERMISSIONS)
        await bot.send_message(
            chat_id,
            f"🔔 {get_mention(user_id, name)}, мут автоматически снят.",
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.message(F.text.lower().regexp(r"^(мут|бан)"))
async def restrict_handler(message: Message, bot: Bot):
    if not await is_admin(message):
        return

    target_id, target_name = await get_target(message, bot)

    if not target_id:
        return await message.answer("❓ Укажите пользователя (реплай или @username).")

    if target_id in (message.from_user.id, bot.id):
        return await message.answer("❌ Нельзя наказать себя или бота.")

    try:
        member = await message.chat.get_member(target_id)
        if member.status in ("administrator", "creator"):
            return await message.answer("❌ Нельзя наказывать администратора.")
    except Exception:
        return await message.answer("❌ Пользователь не найден.")

    duration = parse_time(message.text)
    until_date = datetime.now() + duration
    is_ban = message.text.lower().startswith("бан")

    reason = re.sub(r'^(мут|бан)\s*', '', message.text, flags=re.I)
    reason = re.sub(r'@\w+|\d{7,15}', '', reason).strip()
    if not reason:
        reason = "Не указана"

    try:
        if is_ban:
            await bot.ban_chat_member(message.chat.id, target_id, until_date=until_date)
            await add_to_banlist(
                target_id, target_name,
                message.from_user.id, message.from_user.first_name,
                str(duration)
            )
            action = "🚫 забанен"
        else:
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            scheduler.add_job(
                uncheck_mute,
                "date",
                run_date=until_date,
                args=[message.chat.id, target_id, target_name, bot]
            )
            action = "🔇 замучен"

        await message.answer(
            f"{get_mention(target_id, target_name)} {action}\n"
            f"<b>Причина:</b>\n<blockquote>{reason}</blockquote>",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Restrict error: {e}")
        await message.answer("❌ Ошибка прав бота.")


@router.message(F.text.lower().startswith(("размут", "разбан")))
async def unmute_unban_handler(message: Message, bot: Bot):
    if not await is_admin(message):
        return

    target_id, target_name = await get_target(message, bot)
    if not target_id:
        return await message.answer("❓ Укажите пользователя.")

    is_unban = message.text.lower().startswith("разбан")

    try:
        if is_unban:
            await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
            await remove_from_banlist(target_id)
            action = "🦸‍♂️ разбанен"
        else:
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=FULL_PERMISSIONS
            )
            action = "🔊 размучен"

        await message.answer(
            f"{get_mention(target_id, target_name)} {action}",
            parse_mode="HTML"
        )

    except Exception as e:
        logging.error(f"Unmute error: {e}")
        await message.answer("❌ Ошибка выполнения.")


# =========================================================
# ======================== БАНЛИСТ ========================
# =========================================================

@router.message(Command("банлист"))
async def show_banlist(message: Message):
    if not await is_admin(message):
        return
    await render_banlist(message, 0)


@router.callback_query(F.data.startswith("banlist_page:"))
async def process_banlist_page(call: CallbackQuery):
    if not await is_admin(call.message):
        return await call.answer("Нет прав.", show_alert=True)

    page = int(call.data.split(":")[1])
    await render_banlist(call.message, page, is_callback=True)
    await call.answer()


async def render_banlist(message: Message, page: int, is_callback=False):
    bans = await get_banlist_data()

    if not bans:
        text = "<b>Банлист пуст.</b>"
        return await (
            message.edit_text(text, parse_mode="HTML")
            if is_callback else
            message.answer(text, parse_mode="HTML")
        )

    total_pages = (len(bans) + USERS_PER_PAGE - 1) // USERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))

    start = page * USERS_PER_PAGE
    current = bans[start:start + USERS_PER_PAGE]

    text = f"<b>📜 БАН ЛИСТ</b>\nСтраница {page+1}/{total_pages}\n\n"

    for i, ban in enumerate(current, start + 1):
        text += (
            f"<b>{i}.</b> {get_mention(ban['user_id'], ban['user_name'])}\n"
            f"└ ⏳ {ban['duration']}\n"
            f"└ 👮 {get_mention(ban['admin_id'], ban['admin_name'])}\n\n"
        )

    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="⬅️", callback_data=f"banlist_page:{page-1}")
    if page < total_pages - 1:
        kb.button(text="➡️", callback_data=f"banlist_page:{page+1}")
    kb.adjust(2)

    if is_callback:
        await message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


# =========================================================
# ====================== ФИЛЬТР ССЫЛОК ====================
# =========================================================

@router.message(F.text.in_(["-чаты", "+чаты"]))
async def toggle_links(message: Message):
    if not await is_admin(message):
        return
    value = 1 if message.text == "-чаты" else 0
    await set_filter(message.chat.id, "anti_link", value)
    await message.answer("🚫 Ссылки запрещены." if value else "✅ Ссылки разрешены.")


@router.message(F.chat.type.in_(["group", "supergroup"]))
async def anti_link_filter(message: Message, bot: Bot):
    if await is_admin(message):
        return

    if await get_filter(message.chat.id, "anti_link") == 1:
        if "t.me/" in (message.text or ""):
            try:
                await message.delete()
                await bot.restrict_chat_member(
                    message.chat.id,
                    message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.now() + timedelta(minutes=15)
                )
            except Exception:
                pass


# =========================================================
# ======================== HELP ===========================
# =========================================================

@router.message(Command("help", "помощь"))
async def help_handler(message: Message):
    await message.answer(
        "<b>🛡 Команды модерации:</b>\n\n"
        "• мут 10 мин @user причина\n"
        "• бан 1 час @user причина\n"
        "• размут / разбан\n"
        "• /банлист\n"
        "• кто админ\n",
        parse_mode="HTML"
    )
