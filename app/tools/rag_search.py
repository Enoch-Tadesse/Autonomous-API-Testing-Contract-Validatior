"""RAG: keyword search over spec chunks and workspace docs. No vector database."""

import json
import re
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import ToolContext, fail, ok

WORD = re.compile(r"[a-z0-9_]+")
DOC_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json"}


class RagSearchArgs(BaseModel):
    query: str
    top_k: int = 3


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def build_chunks(ctx: ToolContext) -> list[dict]:
    """One chunk per endpoint and per parameter, plus one per paragraph of each workspace doc."""
    chunks = []
    for ep in ctx.endpoints:
        responses = {code: (schema or {}).get("description", "") for code, schema in ep["responses"].items()}
        chunks.append({"source": ep["key"], "text": f"{ep['key']} secured={ep['secured']} responses={list(responses)}"})
        for p in ep["parameters"]:
            chunks.append({"source": f"{ep['key']} param {p['name']}",
                           "text": f"{ep['key']} parameter {p['name']} {json.dumps(p)}"})
    workspace = Path(ctx.workspace_dir)
    if workspace.is_dir():
        for path in sorted(workspace.rglob("*")):
            if path.suffix in DOC_SUFFIXES and path.is_file():
                for para in path.read_text(errors="replace").split("\n\n"):
                    if para.strip():
                        chunks.append({"source": str(path.relative_to(workspace)), "text": para.strip()})
    return chunks


async def run(args: RagSearchArgs, ctx: ToolContext) -> dict:
    query = words(args.query)
    scored = [(len(query & words(c["text"])), c) for c in build_chunks(ctx)]
    hits = [dict(c, score=s) for s, c in sorted(scored, key=lambda x: -x[0]) if s > 0][: args.top_k]
    if not hits:
        return fail("empty")
    return ok(output=hits)
