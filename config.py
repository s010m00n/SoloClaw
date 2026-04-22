import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ANTHROPIC_BASE_URL = os.environ["ANTHROPIC_BASE_URL"]
OWNER_ID = int(os.environ["OWNER_ID"]) #亲测不加使用不了这个bot
ASSISTANT_NAME = os.environ["ASSISTANT_NAME"]
SCHEDULER_INTERVAL = int(os.environ["SCHEDULER_INTERVAL"])
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "Asia/Shanghai")

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace" #agent每一个新session的新手村
CONVERSATION_DIR = WORKSPACE_DIR / "conversation" #存放所有聊天记录，用来做长期记忆
STORE_DIR = BASE_DIR / "store" #存放db，db提供mcp工具以及被轮询驱动agent定时做事情，和workspace平级
DATA_DIR = BASE_DIR / "data" #存放session_id，用来做短期记忆

DB_PATH = STORE_DIR / "bionic_nanoclaw.db" #记录完成事项、待办事项等
STATE_FILE = DATA_DIR / "state.json" #记录session_id
