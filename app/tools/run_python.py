"""Code and compute: run a short Python snippet in an isolated subprocess."""

import asyncio
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import ToolContext, fail, ok

TIMEOUT_S = 5
MAX_OUTPUT = 4096


class RunPythonArgs(BaseModel):
    code: str


async def run(args: RunPythonArgs, ctx: ToolContext) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "snippet.py"
        script.write_text(args.code)
        # -I: isolated mode (no user site, no env vars, no cwd on sys.path). No shell is involved.
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(script), cwd=tmp, env={},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), TIMEOUT_S)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return fail(f"timeout after {TIMEOUT_S}s")
    output = stdout.decode(errors="replace")[:MAX_OUTPUT]
    if proc.returncode != 0:
        return fail(stderr.decode(errors="replace")[-MAX_OUTPUT:], output=output)
    return ok(output=output)
