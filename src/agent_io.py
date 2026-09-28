"""Hand-off between the Python harness and the tool-using research agents.

The harness owns everything that must be deterministic -- which apps, the
exact brief text, schema validation, freezing, triage, grading. The agents
own only the part that needs judgment and a web browser: reading docs.

    emit    write batch briefs  -> out/work/<pass>/batch_NN.md
    agents  read a brief, write -> out/work/<pass>/raw/<id>_<slug>.json
    ingest  validate raw files  -> out/pass1.json | out/pass2.json

The briefs and raw outputs are committed, so a reviewer can read exactly what
each agent was told and exactly what it returned.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import OUT

WORK = OUT / "work"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def raw_path(pass_name: str, app: dict) -> Path:
    return WORK / pass_name / "raw" / f"{app['id']:03d}_{slug(app['name'])}.json"


def batch_path(pass_name: str, batch_id: int) -> Path:
    return WORK / pass_name / f"batch_{batch_id:02d}.md"


def read_raw(path: Path) -> tuple[dict | None, str | None]:
    """Parse an agent's output file. Returns (payload, error)."""
    if not path.exists():
        return None, "agent wrote no output file"
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("```"):
        text = text.split("```")[1].removeprefix("json").strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def write_batches(pass_name: str, groups: list[list[dict]], render) -> list[Path]:
    """`render(batch_id, apps) -> markdown`. Returns the brief paths."""
    (WORK / pass_name / "raw").mkdir(parents=True, exist_ok=True)
    paths = []
    for i, apps in enumerate(groups, 1):
        p = batch_path(pass_name, i)
        p.write_text(render(i, apps), encoding="utf-8")
        paths.append(p)
    return paths
