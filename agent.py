import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator
from zoneinfo import ZoneInfo

import db
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    query,
    tool,
)
from croniter import croniter

from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    DB_PATH,
    STATE_FILE,
    USER_TIMEZONE,
    WORKSPACE_DIR,
)

_agent_lock = asyncio.Lock()


def create_mcp_server_tools(bot: Any, chat_id: int) -> list:
    @tool("send_message", "Send a message to the user via Telegram.", {"text": str})
    async def send_message(args: dict[str, Any]) -> dict[str, Any]:
        await bot.send_message(chat_id=chat_id, text=args["text"])
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Message sent to the user: {args['text']}",
                }
            ]
        }

    @tool(
        "schedule_task",
        (
            f"Schedule a task for the user. The user's timezone is {USER_TIMEZONE}. "
            "schedule_type must be one of: 'cron', 'interval', or 'once'. "
            "For 'cron', schedule_value must be a cron expression. "
            "For 'interval', schedule_value must be milliseconds as a string. "
            "For 'once', schedule_value must be an ISO 8601 timestamp with timezone offset."
        ),
        {"prompt": str, "schedule_type": str, "schedule_value": str},
    )
    async def schedule_task(args: dict[str, Any]) -> dict[str, Any]:
        stype = args["schedule_type"]
        svalue = args["schedule_value"]
        now = datetime.now(timezone.utc)

        try:
            if stype == "cron":
                next_run = croniter(svalue, now).get_next(datetime).isoformat()
            elif stype == "interval":
                next_run = (now + timedelta(milliseconds=int(svalue))).isoformat()
            elif stype == "once":
                parsed = datetime.fromisoformat(svalue)
                if parsed.tzinfo is None:
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "For schedule_type='once', schedule_value must be an ISO 8601 "
                                    f"timestamp with timezone offset. The user's timezone is {USER_TIMEZONE}."
                                ),
                            }
                        ],
                        "is_error": True,
                    }
                next_run = parsed.astimezone(timezone.utc).isoformat()
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown schedule_type: {stype}"}],
                    "is_error": True,
                }
        except (TypeError, ValueError) as exc:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Invalid schedule_value '{svalue}': {exc}",
                    }
                ],
                "is_error": True,
            }

        task_id = await db.create_task(DB_PATH, chat_id, args["prompt"], stype, svalue, next_run)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Task {task_id} scheduled. Next run (UTC): {next_run}",
                }
            ]
        }

    @tool("list_tasks", "List all scheduled tasks", {})
    async def list_tasks(args: dict[str, Any]) -> dict[str, Any]:
        tasks = await db.get_all_tasks(DB_PATH)
        if not tasks:
            return {"content": [{"type": "text", "text": "No scheduled tasks."}]}
        user_tz = ZoneInfo(USER_TIMEZONE)
        lines = []
        for t in tasks:
            schedule_display = t["schedule_value"]
            if t["schedule_type"] == "once":
                schedule_dt = datetime.fromisoformat(t["schedule_value"])
                schedule_display = schedule_dt.astimezone(user_tz).isoformat()
            lines.append(
                f"- [{t['id']}] {t['status']} | {t['schedule_type']}({schedule_display}) | {t['prompt'][:60]}"
            )
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool("pause_task", "Pause a scheduled task", {"task_id": str})
    async def pause_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await db.update_task_status(DB_PATH, args["task_id"], "paused")
        msg = f"Task {args['task_id']} paused." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    @tool("resume_task", "Resume a paused task", {"task_id": str})
    async def resume_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await db.update_task_status(DB_PATH, args["task_id"], "active")
        msg = f"Task {args['task_id']} resumed." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    @tool("cancel_task", "Cancel and delete a scheduled task", {"task_id": str})
    async def cancel_task(args: dict[str, Any]) -> dict[str, Any]:
        ok = await db.delete_task(DB_PATH, args["task_id"])
        msg = f"Task {args['task_id']} cancelled." if ok else f"Task {args['task_id']} not found."
        return {"content": [{"type": "text", "text": msg}]}

    return [send_message, schedule_task, list_tasks, pause_task, resume_task, cancel_task]


def load_session_id() -> str | None:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("session_id")
    return None


def save_session_id(session_id: str) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"session_id": session_id}, f)


def clear_session_id() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


async def _make_prompt(text: str) -> AsyncGenerator[dict[str, Any], None]:
    yield {"type": "user", "message": {"role": "user", "content": text}}


async def ask_claude(prompt: str, bot: Any, chat_id: int) -> str:
    async with _agent_lock:
        return await _ask_claude(prompt, bot, chat_id)


async def _ask_claude(prompt: str, bot: Any, chat_id: int) -> str:
    tools = create_mcp_server_tools(bot, chat_id)
    mcp_server = create_sdk_mcp_server(name="assistant", tools=tools) #mcp__<server_name>__<tool_name>

    env = {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
    }

    async def _allow_all_tools(*_) -> PermissionResultAllow:
        return PermissionResultAllow(behavior="allow")

    options = ClaudeAgentOptions(
        allowed_tools=[
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "Bash",
            "mcp__assistant__send_message", #mcp__<server_name>__<tool_name>
            "mcp__assistant__schedule_task", #mcp__<server_name>__<tool_name>
            "mcp__assistant__list_tasks", #mcp__<server_name>__<tool_name>
            "mcp__assistant__pause_task", #mcp__<server_name>__<tool_name>
            "mcp__assistant__resume_task", #mcp__<server_name>__<tool_name>
            "mcp__assistant__cancel_task", #mcp__<server_name>__<tool_name>
        ],
        permission_mode="acceptEdits",
        env=env,
        cwd=str(WORKSPACE_DIR),
        mcp_servers={"assistant": mcp_server},
        setting_sources=["project"],
        can_use_tool=_allow_all_tools,
    )

    session_id = load_session_id()
    if session_id:
        options.resume = session_id

    response_parts: list[str] = []
    final_result: str | None = None

    async for message in query(prompt=_make_prompt(prompt), options=options):
        if isinstance(message, AssistantMessage):
            for content in message.content:
                if isinstance(content, TextBlock):
                    response_parts.append(content.text)
                    print("[TEXT BLOCK]", content.text)
                elif isinstance(content, ToolUseBlock):
                    print("[TOOL USE BLOCK]", content)
        elif isinstance(message, UserMessage):
            for content in message.content:
                if isinstance(content, ToolResultBlock):
                    print("[TOOL RESULT BLOCK]", content)
        elif isinstance(message, ResultMessage):
            save_session_id(message.session_id)
            if message.result:
                final_result = message.result

    response = "\n".join(response_parts).strip()
    if response:
        return response
    if final_result:
        print("claudeCodeCli only have final result", final_result)
        return final_result
    print("claudeCodeCli is missing...")
    return "claudeCodeCli is missing..."
