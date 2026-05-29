import contextlib
import io
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from runtime_tools import _submission_payload
from scratchpad import (
    compact_scratchpad,
    compact_model_value,
    ensure_scratchpad_files,
    is_json_serializable,
    json_size,
    load_json,
    scratchpad_profile,
    save_json,
    scratchpad_enabled,
    scratchpad_mode,
)
from tool_gateway import ToolGateway
from workspace import open_task_workspace


VALID_OUTCOMES = {
    "OUTCOME_OK",
    "OUTCOME_DENIED_SECURITY",
    "OUTCOME_NONE_CLARIFICATION",
    "OUTCOME_NONE_UNSUPPORTED",
    "OUTCOME_ERR_INTERNAL",
}


def _env_enabled(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


def _json_default(value: Any) -> str:
    return str(value)


def _output_limit() -> int:
    default = 40_000 if scratchpad_mode() == "v2" else 200_000
    try:
        return max(4_000, int(os.getenv("NATIVE_EXEC_OUTPUT_LIMIT") or default))
    except Exception:
        return default


def _truncate(text: str, limit: int | None = None) -> str:
    if limit is None:
        limit = _output_limit()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated {len(text) - limit} chars"


def _model_result(value: Any) -> Any:
    if scratchpad_mode() != "v2":
        return value
    limit = _output_limit()
    if json_size(value) <= limit:
        return value
    return {
        "_compact_result": True,
        "raw_json_size": json_size(value),
        "value": compact_model_value(value, text_limit=500, list_limit=24, depth=2),
    }


def _load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("exec payload must be a JSON object")
    return payload


def _empty_tracking() -> dict[str, list[str]]:
    return {"read_paths": [], "write_paths": [], "delete_paths": []}


def _load_tracking(path: Any) -> dict[str, list[str]]:
    try:
        data = load_json(path, _empty_tracking())
    except Exception:
        return _empty_tracking()
    if not isinstance(data, dict):
        return _empty_tracking()
    tracking = _empty_tracking()
    for key in tracking:
        values = data.get(key, [])
        if isinstance(values, list):
            tracking[key] = [str(value) for value in values if str(value).strip()]
    return tracking


def _track_path(tracking: dict[str, list[str]], key: str, path: Any) -> None:
    text = str(path or "").strip()
    if text and text not in tracking[key]:
        tracking[key].append(text)


def _save_tracking(path: Any, tracking: dict[str, list[str]]) -> None:
    try:
        save_json(path, tracking)
    except Exception:
        pass


def _persisted_state(globals_dict: dict[str, Any]) -> dict[str, Any]:
    skip = {
        "__name__",
        "json",
        "os",
        "call_tool",
        "ws",
        "finish",
        "run",
        "workspace_root",
        "scratchpad",
        "result",
    }
    state: dict[str, Any] = {}
    for key, value in globals_dict.items():
        if key.startswith("_") or key in skip:
            continue
        if is_json_serializable(value):
            state[key] = value
    return state


def _install_alarm(timeout_sec: int):
    if timeout_sec <= 0:
        return None

    def _timeout(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"exec python timeout after {timeout_sec}s")

    old_handler = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(timeout_sec)
    return old_handler


def _clear_alarm(old_handler: Any) -> None:
    if old_handler is None:
        return
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old_handler)


def main() -> int:
    payload = _load_payload()
    code = str(payload.get("code", ""))
    timeout_sec = max(1, min(int(payload.get("timeout_sec", 120) or 120), 900))
    if not code.strip():
        raise ValueError("exec requires non-empty Python code")

    workspace_root = os.getenv("NATIVE_TASK_WORKSPACE", "").strip()
    if not workspace_root:
        raise RuntimeError("NATIVE_TASK_WORKSPACE is required")

    workspace = open_task_workspace(workspace_root)
    gateway = ToolGateway.from_workspace_context(workspace)
    step_counter = int(payload.get("step", 0) or 0)
    calls: list[dict[str, Any]] = []
    enable_scratchpad = scratchpad_enabled()
    enable_finish_helper = _env_enabled("NATIVE_EXEC_FINISH_HELPER", "0")
    enable_run_helper = _env_enabled("NATIVE_EXEC_RUN_HELPER", "0")
    report_gate = {"allow": not enable_scratchpad}
    tracking_path = workspace.root / "session" / "pangolin_tracking.json"
    tracking = _load_tracking(tracking_path) if enable_scratchpad else _empty_tracking()
    scratchpad_data: dict[str, Any] = {"refs": []}
    state_data: dict[str, Any] = {}
    if enable_scratchpad:
        ensure_scratchpad_files(workspace.pangolin_scratchpad_path, workspace.pangolin_state_path)
        loaded_scratchpad = load_json(workspace.pangolin_scratchpad_path, {"refs": []})
        if isinstance(loaded_scratchpad, dict):
            scratchpad_data = loaded_scratchpad
        loaded_state = load_json(workspace.pangolin_state_path, {})
        if isinstance(loaded_state, dict):
            state_data = loaded_state

    def _normalize_tool_name(tool: str) -> str:
        aliases = {
            "ls": "list",
            "dir": "list",
            "list_path": "list",
            "list_dir": "list",
            "cat": "read",
            "read_file": "read",
        }
        return aliases.get(str(tool), str(tool))

    def _path_args(path: Any = None, **kwargs: Any) -> dict[str, Any]:
        if path is not None and "path" not in kwargs:
            kwargs["path"] = path
        return kwargs

    def call_tool(tool: str, params: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        nonlocal step_counter
        tool = _normalize_tool_name(str(tool))
        merged: dict[str, Any] = {}
        if params:
            if not isinstance(params, dict):
                raise TypeError("call_tool params must be a dict when provided")
            merged.update(params)
        merged.update(kwargs)
        if tool == "report_completion" and not report_gate["allow"]:
            raise ValueError(
                "SUBMISSION BLOCKED: scratchpad is enabled; finalize with ws.answer(scratchpad, verify) "
                "instead of calling report_completion directly."
            )
        step_counter += 1
        result = gateway.call(step=step_counter, tool=tool, args=merged)
        calls.append({"step": step_counter, "tool": tool, "args": merged})

        path = merged.get("path") or merged.get("root") or merged.get("name")
        if tool in {"read", "stat"}:
            _track_path(tracking, "read_paths", path)
        elif tool == "write":
            _track_path(tracking, "write_paths", path)
        elif tool == "delete":
            _track_path(tracking, "delete_paths", path)
        if tool == "move":
            _track_path(tracking, "delete_paths", merged.get("from_name"))
            _track_path(tracking, "write_paths", merged.get("to_name"))
        if enable_scratchpad:
            _save_tracking(tracking_path, tracking)

        if tool == "report_completion":
            submission = _submission_payload(gateway.env, merged)
            workspace.write_json(workspace.submission_path, submission)
            workspace.append_jsonl(
                workspace.events_path,
                {
                    "event": "completion_reported",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "tool": "exec.call_tool.report_completion",
                    "submission": submission,
                },
            )
        return result

    class PangolinWorkspace:
        def __init__(self) -> None:
            self.env = gateway.env

        def call(self, tool: str, **kwargs: Any) -> dict[str, Any]:
            return call_tool(tool, **kwargs)

        def context(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("context", **_path_args(path, **kwargs))

        def tree(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("tree", **_path_args(path, **kwargs))

        def find(self, **kwargs: Any) -> dict[str, Any]:
            return call_tool("find", **kwargs)

        def search(self, **kwargs: Any) -> dict[str, Any]:
            return call_tool("search", **kwargs)

        def list(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("list", **_path_args(path, **kwargs))

        def ls(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return self.list(path, **kwargs)

        def list_path(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return self.list(path, **kwargs)

        def read(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("read", **_path_args(path, **kwargs))

        def cat(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return self.read(path, **kwargs)

        def stat(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("stat", **_path_args(path, **kwargs))

        def exec(self, **kwargs: Any) -> dict[str, Any]:
            return call_tool("exec", kwargs)

        def write(self, path: Any = None, content: Any = None, **kwargs: Any) -> dict[str, Any]:
            if path is not None and "path" not in kwargs:
                kwargs["path"] = path
            if content is not None and "content" not in kwargs:
                kwargs["content"] = content
            return call_tool("write", **kwargs)

        def delete(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("delete", **_path_args(path, **kwargs))

        def mkdir(self, path: Any = None, **kwargs: Any) -> dict[str, Any]:
            return call_tool("mkdir", **_path_args(path, **kwargs))

        def move(self, **kwargs: Any) -> dict[str, Any]:
            return call_tool("move", **kwargs)

        def answer(self, sp: dict[str, Any], verify: Any) -> dict[str, Any]:
            if not isinstance(sp, dict):
                raise ValueError("ws.answer requires scratchpad dict as first argument")
            if not callable(verify):
                msg = "SUBMISSION BLOCKED: define def verify(sp): ... and pass it to ws.answer(scratchpad, verify)"
                print(msg)
                raise ValueError(msg)
            try:
                verified = verify(sp)
            except Exception as exc:
                msg = f"VERIFICATION FUNCTION ERROR: {exc}. Fix your verify function and retry."
                print(msg)
                raise ValueError(msg) from exc
            if not verified:
                msg = "VERIFICATION FAILED: verify(scratchpad) returned False. Fix scratchpad and retry ws.answer()."
                print(msg)
                raise ValueError(msg)

            message = str(sp.get("message", sp.get("answer", "")))
            answer = str(sp.get("answer", message))
            outcome = str(sp.get("outcome", "OUTCOME_OK"))
            refs = sp.get("supporting_refs") or sp.get("final_candidate_refs") or sp.get("refs") or []
            if not isinstance(refs, list):
                raise ValueError("SUBMISSION BLOCKED: scratchpad refs/supporting_refs must be a list")
            refs = [str(ref).strip() for ref in refs if str(ref).strip()]

            if gateway.env == "pac1" and answer.strip():
                lines = answer.split("\n")
                non_empty = [line.strip() for line in lines if line.strip()]
                if non_empty and all(line.startswith("/") for line in non_empty):
                    answer = "\n".join(line.lstrip("/") for line in non_empty)
                    message = answer if not message or message == sp.get("answer") else message
                    sp["answer"] = answer

            missing_fields: list[str] = []
            if not answer and not message:
                missing_fields.append("answer/message")
            if "outcome" not in sp:
                missing_fields.append("outcome")
            if outcome != "OUTCOME_OK" and not refs:
                missing_fields.append("refs")
            if missing_fields:
                fields = ", ".join(missing_fields)
                raise ValueError(f"SUBMISSION BLOCKED: scratchpad missing fields: {fields}")
            if outcome not in VALID_OUTCOMES:
                raise ValueError(f"SUBMISSION BLOCKED: unknown outcome {outcome!r}")

            missing_read_refs = [p for p in tracking["read_paths"] if p not in refs]
            if missing_read_refs:
                print(f"WARNING: {len(missing_read_refs)} read/stat path(s) not in final refs: {missing_read_refs[:5]}")
            if outcome != "OUTCOME_OK" and (tracking["write_paths"] or tracking["delete_paths"]):
                print(
                    "WARNING: non-OK outcome after mutations: "
                    f"writes={tracking['write_paths'][:5]} deletes={tracking['delete_paths'][:5]}"
                )

            sp["message"] = message or answer
            sp["answer"] = answer or message
            sp["outcome"] = outcome
            sp["refs"] = refs
            sp["verification"] = {"ok": True, "submitted_via": "ws.answer", "missing_read_refs": missing_read_refs[:20]}
            report_gate["allow"] = True
            try:
                return call_tool("report_completion", message=message or answer, answer=answer or message, outcome=outcome, grounding_refs=refs)
            finally:
                report_gate["allow"] = False

    def finish(message: str, outcome: str = "OUTCOME_OK", refs: list[Any] | None = None, answer: str | None = None) -> dict[str, Any]:
        if not enable_finish_helper:
            raise ValueError("finish(...) helper is disabled; set NATIVE_EXEC_FINISH_HELPER=1 to enable it")
        if refs is None:
            refs = []
        if not isinstance(refs, list):
            raise ValueError("finish refs must be a list")
        clean_refs = [str(ref).strip() for ref in refs if str(ref).strip()]
        clean_message = str(message or answer or "")
        clean_answer = str(answer if answer is not None else clean_message)
        clean_outcome = str(outcome or "OUTCOME_OK")
        if clean_outcome not in VALID_OUTCOMES:
            raise ValueError(f"finish outcome must be one of {sorted(VALID_OUTCOMES)}, got {clean_outcome!r}")
        if not clean_message and not clean_answer:
            raise ValueError("finish requires message or answer")
        if enable_scratchpad:
            scratchpad_data["message"] = clean_message or clean_answer
            scratchpad_data["answer"] = clean_answer or clean_message
            scratchpad_data["outcome"] = clean_outcome
            scratchpad_data["refs"] = clean_refs
            scratchpad_data["supporting_refs"] = clean_refs

            def verify(sp: dict[str, Any]) -> bool:
                return bool(sp.get("message") or sp.get("answer")) and str(sp.get("outcome", "")) in VALID_OUTCOMES

            return PangolinWorkspace().answer(scratchpad_data, verify)
        report_gate["allow"] = True
        try:
            return call_tool(
                "report_completion",
                message=clean_message or clean_answer,
                answer=clean_answer or clean_message,
                outcome=clean_outcome,
                grounding_refs=clean_refs,
            )
        finally:
            report_gate["allow"] = False

    def run(command: str | None = None, args: list[Any] | tuple[Any, ...] | str | None = None, stdin: Any = "", **kwargs: Any) -> dict[str, Any]:
        if not enable_run_helper:
            raise ValueError("run(...) helper is disabled; set NATIVE_EXEC_RUN_HELPER=1 to enable it")
        if command is None and "path" in kwargs:
            command = str(kwargs.pop("path"))
        script_path = kwargs.pop("path", None)
        if not str(command or "").strip():
            raise ValueError("run requires a non-empty executable path")
        if args is None:
            argv: list[str] = []
        elif isinstance(args, str):
            argv = [args]
        else:
            argv = [str(arg) for arg in args]
        if script_path is not None:
            argv = [str(script_path), *argv]
        payload = {"path": str(command), "args": argv, "stdin": str(stdin or "")}
        payload.update(kwargs)
        return call_tool("exec", payload)

    globals_dict: dict[str, Any] = {
        "__name__": "__bitgn_exec__",
        "json": json,
        "os": os,
        "call_tool": call_tool,
        "ws": PangolinWorkspace(),
        "finish": finish,
        "run": run,
        "workspace_root": workspace_root,
    }
    if enable_scratchpad:
        globals_dict["scratchpad"] = scratchpad_data
        for key, value in state_data.items():
            if isinstance(key, str) and not key.startswith("_") and key not in globals_dict:
                globals_dict[key] = value

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    started = time.time()
    old_handler = _install_alarm(timeout_sec)
    ok = True
    error_text = ""
    output_scratchpad: dict[str, Any] | None = None
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exec(compile(code, "<bitgn-exec>", "exec"), globals_dict, globals_dict)
    except Exception:
        ok = False
        error_text = traceback.format_exc()
    finally:
        _clear_alarm(old_handler)
        if enable_scratchpad:
            current_scratchpad = globals_dict.get("scratchpad", scratchpad_data)
            if not isinstance(current_scratchpad, dict):
                current_scratchpad = scratchpad_data
            if scratchpad_mode() == "v2":
                profile = scratchpad_profile(current_scratchpad, compact_scratchpad(current_scratchpad))
                workspace.append_jsonl(
                    workspace.root / "session" / "pangolin_scratchpad_profile.jsonl",
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        **profile,
                    },
                )
                current_scratchpad = compact_scratchpad(current_scratchpad)
            output_scratchpad = current_scratchpad
            save_json(workspace.pangolin_scratchpad_path, current_scratchpad)
            save_json(workspace.pangolin_state_path, _persisted_state(globals_dict))

    result_value = globals_dict.get("result")
    out = {
        "ok": ok,
        "duration_ms": int((time.time() - started) * 1000),
        "stdout": _truncate(stdout_buf.getvalue()),
        "stderr": _truncate(stderr_buf.getvalue()),
        "error": _truncate(error_text),
        "calls": calls,
    }
    if result_value is not None:
        out["result"] = _model_result(result_value)
    if enable_scratchpad:
        out["scratchpad"] = output_scratchpad if output_scratchpad is not None else scratchpad_data
        out["scratchpad_mode"] = scratchpad_mode()

    print(json.dumps(out, ensure_ascii=True, default=_json_default))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
