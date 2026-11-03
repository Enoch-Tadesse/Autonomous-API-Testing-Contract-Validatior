"""System: read a file inside WORKSPACE_DIR. Anything outside is rejected."""

from pathlib import Path

from pydantic import BaseModel

from app.tools.base import ToolContext, fail, ok

MAX_BYTES = 4096


class ReadFileArgs(BaseModel):
    path: str


async def run(args: ReadFileArgs, ctx: ToolContext) -> dict:
    workspace = Path(ctx.workspace_dir).resolve()
    target = (workspace / args.path).resolve()
    if not target.is_relative_to(workspace):
        return fail("path outside the workspace")
    if not target.is_file():
        return fail("file not found")
    return ok(output=target.read_text(errors="replace")[:MAX_BYTES])
