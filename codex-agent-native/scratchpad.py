import json
import os
from pathlib import Path
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
COMPACT_MODE_VALUES = {"2", "v2", "compact", "scratchpad-v2"}
KEEP_FIELDS = {
    "goal",
    "target_scope",
    "must_not_touch",
    "mutation_plan",
    "identity_chain",
    "key_evidence",
    "evidence",
    "refs",
    "final_candidate_refs",
    "outcome",
    "message",
    "answer",
    "validation_status",
    "validation status",
    "verification",
    "pre_submit_checks",
    "remaining_risks",
}
DROP_FIELDS = {
    "system_tree",
    "cast_tree",
    "inbox_tree",
    "docs",
    "inbox_file",
    "inventory_query_result",
    "availability_left_join",
    "raw",
    "raw_result",
    "results",
    "search_results",
}


def scratchpad_enabled() -> bool:
    for name in ("PANGOLIN_SCRATCHPAD", "NATIVE_PANGOLIN_SCRATCHPAD"):
        value = (os.getenv(name) or "").strip().lower()
        if value:
            return value in TRUE_VALUES
    return False


def scratchpad_mode() -> str:
    value = (os.getenv("PANGOLIN_SCRATCHPAD_MODE") or os.getenv("NATIVE_PANGOLIN_SCRATCHPAD_MODE") or "v1").strip().lower()
    return "v2" if value in COMPACT_MODE_VALUES else "v1"


def scratchpad_compact_enabled() -> bool:
    return scratchpad_mode() == "v2"


def load_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def ensure_scratchpad_files(scratchpad_path: Path, state_path: Path) -> None:
    if not scratchpad_path.exists():
        save_json(scratchpad_path, {"refs": []})
    if not state_path.exists():
        save_json(state_path, {})


def is_json_serializable(value: Any) -> bool:
    try:
        json.dumps(value)
    except Exception:
        return False
    return True


def json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=True, default=str))


def _compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)].rstrip() + " ...[truncated]"


def _compact_value(value: Any, *, text_limit: int, list_limit: int, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _compact_text(value, text_limit)
    if isinstance(value, list):
        compacted = [_compact_value(item, text_limit=text_limit, list_limit=list_limit, depth=depth - 1) for item in value[:list_limit]]
        if len(value) > list_limit:
            compacted.append(f"...[{len(value) - list_limit} omitted]")
        return compacted
    if isinstance(value, dict):
        if depth <= 0:
            return _compact_text(json.dumps(value, ensure_ascii=True, default=str), text_limit)
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:list_limit]:
            out[str(key)] = _compact_value(item, text_limit=text_limit, list_limit=max(4, list_limit // 2), depth=depth - 1)
        if len(value) > list_limit:
            out["_omitted_keys"] = len(value) - list_limit
        return out
    return _compact_text(str(value), text_limit)


def compact_scratchpad(payload: Any, *, mode: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"refs": []}
    selected_mode = mode or scratchpad_mode()
    if selected_mode != "v2":
        return payload

    compacted: dict[str, Any] = {}
    for key, value in payload.items():
        name = str(key)
        lower = name.lower()
        if lower in DROP_FIELDS:
            continue
        if name in KEEP_FIELDS or lower in KEEP_FIELDS:
            compacted[name] = _compact_value(value, text_limit=320, list_limit=32, depth=1)
            continue
        if any(marker in lower for marker in ("ref", "path", "id", "outcome", "status", "risk", "scope")):
            compacted[name] = _compact_value(value, text_limit=220, list_limit=16, depth=1)
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compacted[name] = _compact_value(value, text_limit=160, list_limit=8, depth=0)
    compacted.setdefault("refs", [])
    return compacted


def compact_model_value(value: Any, *, text_limit: int = 600, list_limit: int = 24, depth: int = 2) -> Any:
    return _compact_value(value, text_limit=text_limit, list_limit=list_limit, depth=depth)


def scratchpad_profile(before: Any, after: Any) -> dict[str, Any]:
    before_keys = set(before.keys()) if isinstance(before, dict) else set()
    after_keys = set(after.keys()) if isinstance(after, dict) else set()
    return {
        "mode": scratchpad_mode(),
        "raw_size": json_size(before),
        "view_size": json_size(after),
        "dropped_keys": sorted(before_keys - after_keys),
        "keys": sorted(after_keys),
    }
