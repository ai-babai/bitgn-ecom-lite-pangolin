import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from tool_gateway import ToolGateway, print_tool_result
from workspace import open_task_workspace

NATIVE_LOG_LEVEL = (os.getenv("NATIVE_LOG_LEVEL") or "info").strip().lower()


def _cli_tool(msg: str) -> None:
    print(msg, flush=True)


def _short_args(args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(args.keys()):
        value = args.get(key)
        if key == "content":
            parts.append(f"content_len={len(str(value))}")
            continue
        text = str(value)
        if len(text) > 60:
            text = text[:60] + "..."
        parts.append(f"{key}={text}")
    return " ".join(parts)


def _load_gateway() -> tuple[ToolGateway, str]:
    workspace_root = os.getenv("NATIVE_TASK_WORKSPACE", "").strip()
    if not workspace_root:
        raise SystemExit("NATIVE_TASK_WORKSPACE is required")
    workspace = open_task_workspace(workspace_root)
    gateway = ToolGateway.from_workspace_context(workspace)
    return gateway, workspace_root


def _read_json_arg() -> dict[str, Any]:
    if len(sys.argv) >= 3:
        raw = sys.argv[2]
        if raw.startswith("{"):
            return json.loads(raw)
        out: dict[str, Any] = {}
        for item in sys.argv[2:]:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if key in {"count", "limit", "level", "start_line", "end_line", "_step"}:
                try:
                    out[key] = int(value)
                    continue
                except ValueError:
                    pass
            if key in {"number"}:
                out[key] = value.lower() in {"1", "true", "yes", "on"}
                continue
            if key in {"grounding_refs", "args"}:
                out[key] = [x.strip() for x in value.split(",") if x.strip()]
                continue
            out[key] = value
        return out
    raw_stdin = sys.stdin.read().strip()
    return json.loads(raw_stdin) if raw_stdin else {}


def _submission_payload(env: str, args: dict[str, Any]) -> dict[str, Any]:
    refs_raw = args.get("grounding_refs", [])
    refs = refs_raw if isinstance(refs_raw, list) else []
    if env == "sandbox":
        clean_refs = [str(r).strip().lstrip("/") for r in refs if str(r).strip()]
        return {"answer": str(args.get("answer", args.get("message", ""))), "grounding_refs": clean_refs or ["AGENTS.MD"]}
    if env == "ecom":
        clean_refs = [str(r).strip() for r in refs if str(r).strip()]
        clean_refs = [r if r.startswith("/") else "/" + r.lstrip("/") for r in clean_refs]
        return {
            "message": str(args.get("message", args.get("answer", ""))),
            "answer": str(args.get("answer", args.get("message", ""))),
            "outcome": str(args.get("outcome", "OUTCOME_NONE_UNSUPPORTED")),
            "grounding_refs": clean_refs or ["/AGENTS.MD"],
        }
    clean_refs = [str(r).strip().lstrip("/") for r in refs if str(r).strip()]
    clean_refs = [r for r in clean_refs if not r.startswith("local-rules/") and not r.startswith("task-context-snapshots/")]
    return {
        "message": str(args.get("message", args.get("answer", ""))),
        "outcome": str(args.get("outcome", "OUTCOME_NONE_UNSUPPORTED")),
        "grounding_refs": clean_refs or ["AGENTS.MD"],
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python runtime_tools.py <tool> [json-args|key=value ...]")

    tool = str(sys.argv[1]).strip()
    args = _read_json_arg()
    if not isinstance(args, dict):
        raise SystemExit("Args must be a JSON object")

    gateway, workspace_root = _load_gateway()
    step = int(args.pop("_step", 0) or 0)
    _cli_tool(f"TOOL_CALL tool={tool} step={step} {_short_args(args)}")
    try:
        result = gateway.call(step=step, tool=tool, args=args)
        _cli_tool(f"TOOL_OK tool={tool}")
    except Exception as exc:
        _cli_tool(f"TOOL_ERR tool={tool} err={str(exc)}")
        raise

    if tool == "report_completion":
        ws = open_task_workspace(workspace_root)
        payload = _submission_payload(gateway.env, args)
        ws.write_json(ws.submission_path, payload)
        ws.append_jsonl(
            ws.events_path,
            {
                "event": "completion_reported",
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": tool,
                "submission": payload,
            },
        )

    if NATIVE_LOG_LEVEL == "debug":
        print_tool_result(result)


if __name__ == "__main__":
    main()
