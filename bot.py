from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from agent import ask_claude, clear_session_id
from conversations import archive_conversation
from scheduler import post_init

from config import OWNER_ID, TELEGRAM_BOT_TOKEN, ASSISTANT_NAME


async def handle_message(update: Update, context) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("你没有权限使用这个 bot。")
        return

    if not update.message or not update.message.text:
        return

    response = await ask_claude(update.message.text, context.bot, update.effective_chat.id)
    archive_conversation(update.message.text, response)

    max_length = 4000
    for i in range(0, len(response), max_length):
        await update.message.reply_text(response[i : i + max_length])


async def start(update: Update, context) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("你没有权限使用这个 bot。")
        return

    if not update.message:
        return
    await update.message.reply_text(
        "Hi~ 我是 {ASSISTANT_NAME}，请尽情吩咐~"
    )


async def clear(update: Update, context) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("你没有权限使用这个 bot。")
        return

    if not update.message:
        return
    clear_session_id()
    await update.message.reply_text("会话已清除，重新开始！")


async def compact(update: Update, context) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("你没有权限使用这个 bot。")
        return

    if not update.message:
        return

    await update.message.reply_text("正在压缩会话上下文，请稍候...")
    response = await ask_claude("/compact", context.bot, update.effective_chat.id)
    await update.message.reply_text(
        f"会话已压缩！\n{response}" if response else "会话已压缩！"
    )


def setup_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("compact", compact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
