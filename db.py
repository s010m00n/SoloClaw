import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

"""
数据库中一共有两张表，一张叫做 scheduled_tasks -> 用来存“有哪些定时任务”；另一张叫做 task_run_logs -> 用来存“这些任务每次执行的记录”

这其实就是两张excel表格。

第一张表格 scheduled_tasks 里面存了这些字段：
id：任务id
chat_id：谁创建的
prompt：任务内容
schedule_type：cron/interval/once -> cron=按照日历规则执行；interval=按照固定间隔反复执行；once=只执行一次
schedule_value：调度表达式或时间值
next_run：下次执行时间
last_run：上次执行时间
last_result：上次执行结果
status：active/paused/completed
created_at：任务创建时间

所以这张表格的作用就是：定义“任务本身现在是什么状态”。
我们还在这张 scheduled_tasks 表上建立了一个 idx_scheduled_tasks_next_run 索引，用来快速查找 next_run 字段；以及一个 idx_scheduled_tasks_status 字段，用来快速查找 status 字段

第二张表格 tasks_run_logs 里面主要存这些字段：
id：这条日志自己的id
task_id：这条日志属于哪个任务 -> 外键指向“id：任务id”
run_at：这次执行发生的时间
duration_ms：执行耗时
status：这次执行时成功还是失败
result：成功结果
error：失败信息

所以这张表格的作用就是：记录“任务每一次运行发送了什么”。
我们还在这张 tasks_run_logs 表上建立了一个 idx_task_run_logs_task_id 索引，用来快速查找 task_id 字段

整体上就是：
scheduled_tasks 存任务定义
task_run_logs 存任务运行历史

它们之间的关系是：一个任务，可以对应很多条运行日志
"""

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run TEXT,
    last_run TEXT,
    last_result TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status);

CREATE TABLE IF NOT EXISTS task_run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_task_run_logs_task_id ON task_run_logs(task_id);
"""

# TL;DR -> 往 scheduled_tasks 里插入一条新任务，并返回任务 id
# 提供给 MCP工具 —— schedule_task 使用
# 增
async def create_task(
    db_path: Path,
    chat_id: int,
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    next_run: str,
) -> str:
    task_id = uuid.uuid4().hex[:8] #本来先生成了一个非常长、非常难重复的随机 id，然后为了好看、好输、好展示，只截了前 8 位出来。
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            INSERT INTO scheduled_tasks ( id, chat_id, prompt, schedule_type, schedule_value, next_run, created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, #刚生成的 task_id
                chat_id,
                prompt,
                schedule_type,
                schedule_value,
                next_run,
                datetime.now(timezone.utc).isoformat(), #这是在记录这条任务的创建时间 #这里没填 next_run、last_run、last_result 三个值
            ),
        )
        await conn.commit()
    return task_id

# TL;DR -> 从 scheduled_tasks 里取出所有任务，并按 created_at 降序返回（即时间新的在上面，时间旧的在后面）
# 提供给 MCP 工具 —— list_tasks 使用
# 查
async def get_all_tasks(db_path: Path) -> list[dict[str, Any]]:
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM scheduled_tasks ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# TL;DR -> 找出所有 active 且 next_run <= 当前时间 的任务
# 提供给 check_due_tasks 函数使用
# 查
async def get_due_tasks(db_path: Path) -> list[dict[str, Any]]:
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT * FROM scheduled_tasks
            WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= ?
            ORDER BY next_run ASC
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# TL;DR -> 按 task_id 更新某条任务的状态，比如改成 paused 或 active
# 提供给 MCP 工具 —— pause_task和resume_task 使用
# 改
async def update_task_status(db_path: Path, task_id: str, status: str) -> bool:
    async with aiosqlite.connect(str(db_path)) as conn:
        cursor = await conn.execute( #这里返回的cursor有个属性，即 rowcount，代表着这次update/delete/insert/select影响了多少行，但是一般来说，insert和select的cursor.rowcount没啥意义
            "UPDATE scheduled_tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        await conn.commit()
        return cursor.rowcount > 0 #返回的是bool对象

# TL;DR -> 删除任务
# 提供给 MCP 工具 —— cancel_task 使用
# 删
async def delete_task(db_path: Path, task_id: str) -> bool:
    async with aiosqlite.connect(str(db_path)) as conn:
        cursor = await conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        await conn.commit()
        return cursor.rowcount > 0 #返回的是bool对象

# TL;DR -> 任务执行完后，回写 last_run / last_result / next_run / status
# 提供给 execute_task 函数使用
# 改
async def update_task_after_run(
    db_path: Path,
    task_id: str,
    last_result: str,
    next_run: str | None,
    status: str,
) -> None:
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            UPDATE scheduled_tasks
            SET last_run = ?, last_result = ?, next_run = ?, status = ?
            WHERE id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(), #这里记录的是上次执行时间，注意可能有偏差，因为claude运行的比较慢
                last_result,
                next_run,
                status,
                task_id,
            ),
        )
        await conn.commit()

# TL;DR -> 往 task_run_logs 里插入一条任务执行日志
# 提供给 execute_task 函数使用
# 增
async def log_task_run(
    db_path: Path,
    task_id: str,
    duration_ms: int,
    status: str,
    result: str | None = None,
    error: str | None = None,
) -> None:
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.execute(
            """
            INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                datetime.now(timezone.utc).isoformat(), #这里记录的是这条log的入墙时间
                duration_ms,
                status,
                result,
                error,
            ),
        )
        await conn.commit()

# TL;DR -> 初始化数据库表结构，如果表不存在就创建（也创建文件），存在不会重复创建
async def init_db(db_path: Path) -> None:
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.executescript(_CREATE_TABLES)
        await conn.commit()