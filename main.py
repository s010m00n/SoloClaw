import asyncio

import db
from bot import setup_bot
from memory import ensure_memory_files

from config import CONVERSATION_DIR, DATA_DIR, DB_PATH, STORE_DIR, WORKSPACE_DIR


async def init_db() -> None:
    await db.init_db(DB_PATH)


async def _prepare() -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATION_DIR.mkdir(parents=True, exist_ok=True)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ensure_memory_files()
    await init_db()


def main() -> None:
    asyncio.run(_prepare())
    app = setup_bot()

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("正在中断...")
