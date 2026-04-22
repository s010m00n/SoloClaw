from datetime import datetime
from zoneinfo import ZoneInfo

from config import CONVERSATION_DIR, USER_TIMEZONE


def archive_conversation(user_message: str, assistant_response: str) -> None:
    user_tz = ZoneInfo(USER_TIMEZONE)
    now = datetime.now(user_tz)
    today = now.strftime("%Y-%m-%d")
    filepath = CONVERSATION_DIR / f"{today}.md"

    timestamp = now.strftime("%H:%M:%S")
    entry = f"""## {timestamp}

**User**: {user_message}

**Ape**: {assistant_response}

---
"""

    if filepath.exists():
        content = filepath.read_text(encoding="utf-8") + entry
    else:
        content = f"# 对话记录 - {today}\n\n" + entry

    filepath.write_text(content, encoding="utf-8")
