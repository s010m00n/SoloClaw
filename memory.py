from config import ASSISTANT_NAME, WORKSPACE_DIR
from prompts import load_prompt


def render_claude_md_template() -> str:
    return load_prompt("claude_md_template").format(assistant_name=ASSISTANT_NAME)


def ensure_memory_files() -> None:
    claude_md = WORKSPACE_DIR / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(render_claude_md_template(), encoding="utf-8")
