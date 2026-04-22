import time
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter
from telegram.ext import Application

import db
from agent import ask_claude
from config import DB_PATH, SCHEDULER_INTERVAL


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_due_tasks, "interval", seconds=SCHEDULER_INTERVAL, args=[bot])
    return scheduler


async def post_init(app: Application) -> None:
    scheduler = setup_scheduler(app.bot)
    scheduler.start()
    print("调度器已启动")


async def execute_task(task: dict[str, Any], bot: Any) -> None:
    task_id = task["id"]
    task_chat_id = task["chat_id"]
    prompt = task["prompt"]
    start_time = time.monotonic()

    try:
        wrapped_prompt = (
            "You are executing a scheduled task. "
            "You MUST use the send_message tool to notify the user in Telegram. "
            f"Task: {prompt}"
        )
        result = await ask_claude(wrapped_prompt, bot, task_chat_id)
        duration_ms = int((time.monotonic() - start_time) * 1000)
        await db.log_task_run(DB_PATH, task_id, duration_ms, "success", result=result)

        now = datetime.now(timezone.utc)
        if task["schedule_type"] == "cron":
            next_run = croniter(task["schedule_value"], now).get_next(datetime).isoformat()
            await db.update_task_after_run(DB_PATH, task_id, result, next_run, "active")
        elif task["schedule_type"] == "interval":
            next_run = (now + timedelta(milliseconds=int(task["schedule_value"]))).isoformat()
            await db.update_task_after_run(DB_PATH, task_id, result, next_run, "active")
        elif task["schedule_type"] == "once":
            await db.update_task_after_run(DB_PATH, task_id, result, None, "completed")
    except Exception as exc:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        await db.log_task_run(DB_PATH, task_id, duration_ms, "error", error=str(exc))
        await db.update_task_after_run(DB_PATH, task_id, f"Error: {exc}", task.get("next_run"), "active")


async def check_due_tasks(bot: Any) -> None:
    try:
        tasks = await db.get_due_tasks(DB_PATH)
    except Exception as exc:
        print(f"Failed to query due tasks: {exc}")
        return

    for task in tasks:
        try:
            await execute_task(task, bot)
        except Exception as exc:
            print(f"Failed to execute task {task.get('id')}: {exc}")
