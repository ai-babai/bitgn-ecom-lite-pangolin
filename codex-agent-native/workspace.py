import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sanitize_id(value: str, fallback: str) -> str:
    cleaned = "".join(ch for ch in str(value) if ch.isalnum() or ch in {"-", "_", "."})
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _normalize_local_run_id(value: str | None) -> str:
    base = _sanitize_id(value or "", "")
    if not base:
        base = f"{_utc_stamp()}_{uuid.uuid4().hex[:8]}"
    if not base.startswith("local_run_"):
        base = f"local_run_{base}"
    return base


@dataclass
class TaskWorkspace:
    root: Path
    events_path: Path
    tool_calls_path: Path
    agent_session_path: Path
    submission_path: Path
    score_path: Path
    meta_path: Path
    instruction_path: Path
    context_path: Path
    codex_last_message_path: Path
    codex_prompt_path: Path
    codex_session_raw_path: Path
    codex_session_parsed_path: Path
    codex_session_meta_path: Path
    pangolin_scratchpad_path: Path
    pangolin_state_path: Path

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")


def create_task_workspace(
    *,
    base_dir: str,
    benchmark_id: str,
    task_id: str,
    env: str,
    model: str,
    local_run_id: str | None = None,
) -> TaskWorkspace:
    base = Path(base_dir)
    run_id = _normalize_local_run_id(local_run_id)
    attempt_id = f"attempt_{_utc_stamp()}_{uuid.uuid4().hex[:6]}"
    root = base / run_id / task_id / attempt_id
    root.mkdir(parents=True, exist_ok=True)

    ws = TaskWorkspace(
        root=root,
        events_path=root / "events.jsonl",
        tool_calls_path=root / "tool_calls.jsonl",
        agent_session_path=root / "agent_session.jsonl",
        submission_path=root / "submission.json",
        score_path=root / "score.json",
        meta_path=root / "meta.json",
        instruction_path=root / "instruction.txt",
        context_path=root / "task_context.json",
        codex_last_message_path=root / "session" / "codex_last_message.json",
        codex_prompt_path=root / "session" / "codex_prompt.txt",
        codex_session_raw_path=root / "session" / "codex_session_raw.jsonl",
        codex_session_parsed_path=root / "session" / "codex_session_parsed.jsonl",
        codex_session_meta_path=root / "session" / "codex_session_meta.json",
        pangolin_scratchpad_path=root / "session" / "pangolin_scratchpad.json",
        pangolin_state_path=root / "session" / "pangolin_state.json",
    )
    (root / "session").mkdir(parents=True, exist_ok=True)
    ws.write_json(
        ws.meta_path,
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "local_run_id": run_id,
            "benchmark_id": benchmark_id,
            "task_id": task_id,
            "env": env,
            "model": model,
            "workspace_root": str(ws.root),
            "host": os.getenv("BENCHMARK_HOST", "https://api.bitgn.com"),
        },
    )
    return ws


def open_task_workspace(root_dir: str) -> TaskWorkspace:
    root = Path(root_dir)
    return TaskWorkspace(
        root=root,
        events_path=root / "events.jsonl",
        tool_calls_path=root / "tool_calls.jsonl",
        agent_session_path=root / "agent_session.jsonl",
        submission_path=root / "submission.json",
        score_path=root / "score.json",
        meta_path=root / "meta.json",
        instruction_path=root / "instruction.txt",
        context_path=root / "task_context.json",
        codex_last_message_path=root / "session" / "codex_last_message.json",
        codex_prompt_path=root / "session" / "codex_prompt.txt",
        codex_session_raw_path=root / "session" / "codex_session_raw.jsonl",
        codex_session_parsed_path=root / "session" / "codex_session_parsed.jsonl",
        codex_session_meta_path=root / "session" / "codex_session_meta.json",
        pangolin_scratchpad_path=root / "session" / "pangolin_scratchpad.json",
        pangolin_state_path=root / "session" / "pangolin_state.json",
    )
