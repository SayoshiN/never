import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter
from aiogram.types import Message, ChatMemberUpdated, InlineKeyboardButton, User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus

import config
import database as db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

config.validate_config()
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

# ═══════════════════════════════════════════════════════════
# ИНЛАЙН КНОПКИ ДЛЯ /start
# ═══════════════════════════════════════════════════════════

START_TEXT = (
    "👋 Привет! Я твой незаменимый бот для управления репутацией в группах.\n\n"
    "Хочешь поднять актив в чате и наградить самых полезных участников? Я готов помочь!\n\n"
    "🚀 Как запустить меня за 2 шага:\n"
    "1️⃣ Добавь меня в свою группу.\n"
    "2️⃣ Сделай администратором, чтобы я мог читать команды и обновлять топы.\n\n"
    "📜 Шпаргалка по командам (ответом на сообщение):\n\n"
    "➕ /rep — выразить респект (+1 к карме)\n"
    "➖ /repdis — выразить дизреспект (-1 к карме)\n\n"
    "📊 Общие команды в чате:\n"
    "👤 /repinfo — посмотреть свой уровень репутации\n"
    "🏆 /reptop — открыть доску лидеров чата\n"
    "❓ /rep help — полная справка по всем фишкам"
)

INSTRUCTION_TEXT = (
    "⚙️ *Инструкция по настройке бота*\n\n"
    "*Шаг 1: Добавление в группу*\n"
    "• Нажми кнопку \"➕ Добавить в группу\"\n"
    "• Выбери свою группу из списка\n"
    "• Нажми \"Добавить\"\n\n"
    "*Шаг 2: Права администратора*\n"
    "• Зайди в группу → Управление группой\n"
    "• Администраторы → Добавить администратора\n"
    "• Выбери бота из списка\n"
    "• Включи права, которые нужны твоей группе\n\n"
    "✅ Готово! Бот начнёт работать."
)


def start_keyboard(bot_username: str):
    """Кнопки под приветствием"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить в группу",
            url=f"https://t.me/{bot_username}?startgroup=true"
        )
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Инструкция", callback_data="instruction")
    )
    return builder.as_markup()


def instruction_keyboard(bot_username: str):
    """Кнопки в инструкции"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="➕ Добавить в группу",
            url=f"https://t.me/{bot_username}?startgroup=true"
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")
    )
    return builder.as_markup()


async def get_bot_username() -> str:
    me = await bot.get_me()
    return me.username


def save_user(user: User | None):
    if not user:
        return

    db.save_user(
        user.id,
        user.username,
        user.first_name,
        user.last_name,
        user.language_code,
        user.is_bot,
    )


def save_chat(chat):
    db.save_chat(
        chat.id,
        chat.type,
        chat.title,
        chat.username,
        chat.first_name,
        chat.last_name,
    )


def display_name(user: User) -> str:
    return f"@{user.username}" if user.username else user.first_name or f"ID:{user.id}"

# ═══════════════════════════════════════════════════════════
# /start — приветствие
# ═══════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.chat.type == "private":
        await message.answer(
            START_TEXT,
            reply_markup=start_keyboard(await get_bot_username())
        )

# ═══════════════════════════════════════════════════════════
# CALLBACK ОБРАБОТЧИКИ (инлайн кнопки)
# ═══════════════════════════════════════════════════════════

@dp.callback_query(F.data == "instruction")
async def show_instruction(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return

    await callback.message.edit_text(
        INSTRUCTION_TEXT,
        parse_mode="Markdown",
        reply_markup=instruction_keyboard(await get_bot_username())
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    if not callback.message:
        await callback.answer()
        return

    await callback.message.edit_text(
        START_TEXT,
        reply_markup=start_keyboard(await get_bot_username())
    )
    await callback.answer()

# ═══════════════════════════════════════════════════════════
# РЕПУТАЦИЯ (команды в группах)
# ═══════════════════════════════════════════════════════════

@dp.message(Command("rep"))
async def cmd_rep(message: Message):
    args = (message.text or "").split()
    if len(args) > 1 and args[1].lower() == "help":
        await message.answer(
            "🤖 Бот Репутации\n\n"
            "Команды:\n"
            "• /rep — ответь на сообщение = +1\n"
            "• /repdis — ответь на сообщение = -1\n"
            "• /repinfo — твоя репутация\n"
            "• /reptop — топ репутации\n\n"
            "⚡ Можно проголосовать за человека только 1 раз!"
        )
        return

    await process_reputation_vote(message, 1)

@dp.message(Command("repdis"))
async def cmd_repdis(message: Message):
    await process_reputation_vote(message, -1)


async def process_reputation_vote(message: Message, amount: int):
    chat = message.chat
    actor = message.from_user

    if chat.type == "private":
        return

    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user

    if not target_user:
        command = "/rep" if amount > 0 else "/repdis"
        await message.answer(f"❌ Ответьте на сообщение пользователя командой {command}")
        return

    if not actor:
        await message.answer("❌ Не удалось определить отправителя команды.")
        return

    if target_user.id == actor.id:
        await message.answer("🚫 Нельзя себе!")
        return

    if target_user.is_bot:
        await message.answer("🤖 Ботам не нужна репутация!")
        return

    try:
        save_chat(chat)
        save_user(actor)
        save_user(target_user)

        success, msg = db.give_rep(chat.id, actor.id, target_user.id, amount)
        if not success:
            await message.answer(f"❌ {msg}")
            return

        rep = db.get_user_rep(chat.id, target_user.id)
    except Exception:
        logger.exception("Failed to update reputation")
        await message.answer("❌ Не удалось обновить репутацию. Попробуйте позже.")
        return

    sign = "+1" if amount > 0 else "-1"
    prefix = "✅" if amount > 0 else "👎"
    await message.answer(
        f"{prefix} {display_name(target_user)} получил {sign} репутации!\n\n"
        f"📊 Счёт: {rep['rep_score']}"
    )

@dp.message(Command("repinfo"))
async def cmd_repinfo(message: Message):
    chat = message.chat
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    if not target:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    try:
        save_chat(chat)
        save_user(target)
        rep = db.get_user_rep(chat.id, target.id)
    except Exception:
        logger.exception("Failed to fetch reputation")
        await message.answer("❌ Не удалось получить репутацию. Попробуйте позже.")
        return

    await message.answer(
        f"👤 Репутация: {display_name(target)}\n\n"
        f"📊 Счёт: {rep['rep_score']}\n"
        f"📈 Получено +: {rep['rep_received']}\n"
        f"👎 Получено -: {rep['rep_dis_received']}\n"
        f"🎁 Выдано +: {rep['rep_given']}\n"
        f"👎 Выдано -: {rep['rep_dis_given']}"
    )

@dp.message(Command("reptop"))
async def cmd_reptop(message: Message):
    chat = message.chat
    if chat.type == "private":
        return

    try:
        save_chat(chat)
        top = db.get_top_rep(chat.id, 10)
    except Exception:
        logger.exception("Failed to fetch reputation top")
        await message.answer("❌ Не удалось получить топ. Попробуйте позже.")
        return

    if not top:
        await message.answer("📭 Пока никто не получал репутацию!")
        return

    result = "🏆 Топ репутации:\n\n"
    for i, user in enumerate(top, 1):
        name = f"@{user['username']}" if user['username'] else (user['first_name'] or f"ID:{user['user_id']}")
        result += f"{i}. {name} — {user['rep_score']}\n"

    await message.answer(result)

# ═══════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ ВСЕХ СООБЩЕНИЙ
# ═══════════════════════════════════════════════════════════

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=True))
async def on_chat_member_update(event: ChatMemberUpdated):
    bot_user = await bot.get_me()
    if event.new_chat_member.user.id == bot_user.id:
        if event.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            try:
                save_chat(event.chat)
            except Exception:
                logger.exception("Failed to save chat member update")
            logger.info(f"✅ Бот добавлен в: {event.chat.title or event.chat.id}")

@dp.message()
async def log_all_messages(message: Message):
    chat = message.chat
    user = message.from_user

    content_type = "text"
    text = message.text or message.caption or ""

    if message.photo: content_type = "photo"
    elif message.video: content_type = "video"
    elif message.document: content_type = "document"
    elif message.audio: content_type = "audio"
    elif message.voice: content_type = "voice"
    elif message.sticker: content_type = "sticker"
    elif message.poll: content_type = "poll"
    elif message.location: content_type = "location"
    elif message.new_chat_members: content_type = "new_chat_members"
    elif message.left_chat_member: content_type = "left_chat_member"
    elif message.pinned_message: content_type = "pinned_message"

    try:
        save_chat(chat)
        save_user(user)

        db.save_message(
            chat.id, message.message_id, user.id if user else None,
            text, content_type,
            message.reply_to_message.message_id if message.reply_to_message else None
        )
    except Exception:
        logger.exception("Failed to save incoming message")

    author = (user.username or user.id) if user else "system"
    logger.info(f"[{chat.title or chat.id}] {author}: {text[:50] if text else f'[{content_type}]'}")

# ═══════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════

async def main():
    try:
        db.init_db()
    except Exception:
        logger.exception("Failed to initialize database")
        logger.error(
            "Проверь SUPABASE_URI в .env: хост, порт, пользователь, пароль и имя базы."
        )
        raise

    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот @{bot_info.username} запущен!")
    logger.info("⏱️ Поллинг: 10 секунд")
    logger.info("⚠️ Проверь: @BotFather → /setprivacy → Disable")

    await asyncio.gather(
        start_health_server(),
        dp.start_polling(
            bot,
            polling_timeout=10
        ),
    )


async def health_check(request):
    return web.Response(text="OK")


async def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Health server started on port {port}")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
