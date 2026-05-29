# pyright: reportMissingImports=false

import json
import importlib.util
import os
import re
import select
import subprocess
import sys
import time
import threading
from argparse import ArgumentParser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    GetRunRequest,
    GetTrialRequest,
    StartRunRequest,
    StartPlaygroundRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
    TRIAL_STATE_DONE,
)
from bitgn.vm.mini_pb2 import ReadRequest
from bitgn.vm.pcm_pb2 import ReadRequest as PcmReadRequest
from bitgn.vm.ecom.ecom_pb2 import ReadRequest as EcomReadRequest
from connectrpc.errors import ConnectError
from google.protobuf.json_format import MessageToDict
from urllib import error as urlerror
from urllib import request as urlrequest

from tool_gateway import ToolGateway
import harness_seed
from scratchpad import compact_scratchpad, ensure_scratchpad_files, load_json, scratchpad_enabled, scratchpad_mode
from workspace import create_task_workspace

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/sandbox"
AGENT_ENV = (os.getenv("AGENT_ENV") or "").strip().lower()
CODEX_MODEL = os.getenv("CODEX_MODEL") or "codex/gpt-5.5-high"
CODEX_PROFILE = (os.getenv("CODEX_PROFILE") or "").strip()
CODEX_BACKEND = (os.getenv("CODEX_BACKEND") or "omniroute").strip().lower()
AGENT_BACKBONE = (os.getenv("AGENT_BACKBONE") or "codex").strip().lower()
PI_MODEL = os.getenv("PI_MODEL") or "omniroute/codex/gpt-5.5-high"
PI_PROVIDER = (os.getenv("PI_PROVIDER") or "").strip()
PI_THINKING = (os.getenv("PI_THINKING") or "").strip()
PI_TOOL_MODE = (os.getenv("PI_TOOL_MODE") or "exec").strip().lower()
NATIVE_PANGOLIN_MODEL = (os.getenv("NATIVE_PANGOLIN_MODEL") or CODEX_MODEL).strip()
NATIVE_PANGOLIN_BASE_URL = (
    os.getenv("NATIVE_PANGOLIN_BASE_URL")
    or os.getenv("OPENAI_BASE_URL")
    or os.getenv("OMNIROUTE_BASE_URL")
    or "https://omni.mipopkov.com/v1"
).strip().rstrip("/")
NATIVE_PANGOLIN_MAX_ITERATIONS = max(1, int(os.getenv("NATIVE_PANGOLIN_MAX_ITERATIONS") or 20))
NATIVE_PANGOLIN_MAX_OUTPUT_TOKENS = max(512, int(os.getenv("NATIVE_PANGOLIN_MAX_OUTPUT_TOKENS") or 12000))
NATIVE_PANGOLIN_REASONING_ENABLED = (os.getenv("NATIVE_PANGOLIN_REASONING_ENABLED") or "").strip().lower()
NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS = max(
    0, int(os.getenv("NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS") or 96_000)
)
NATIVE_PANGOLIN_EMPTY_GUARD_COUNT = max(
    0, int(os.getenv("NATIVE_PANGOLIN_EMPTY_GUARD_COUNT") or 3)
)
NATIVE_PANGOLIN_SYNTAX_REPAIR = (os.getenv("NATIVE_PANGOLIN_SYNTAX_REPAIR") or "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
NATIVE_PANGOLIN_SCRATCHPAD_COMPACT_BYTES = max(
    0, int(os.getenv("NATIVE_PANGOLIN_SCRATCHPAD_COMPACT_BYTES") or 48_000)
)
BITGN_API_KEY = (os.getenv("BITGN_API_KEY") or "").strip()
AGENT_MODEL = NATIVE_PANGOLIN_MODEL if AGENT_BACKBONE in {"pangolin", "pangolin_loop"} else (PI_MODEL if AGENT_BACKBONE == "pi" else CODEX_MODEL)
BITGN_RUN_NAME = (os.getenv("BITGN_RUN_NAME") or f"{AGENT_BACKBONE}-native {AGENT_MODEL}").strip()
NATIVE_LEADERBOARD = (os.getenv("NATIVE_LEADERBOARD") or "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
NATIVE_SESSION_TIMEOUT_SEC = int(os.getenv("NATIVE_SESSION_TIMEOUT_SEC") or 1440)
NATIVE_RUNS_DIR = os.getenv("NATIVE_RUNS_DIR") or str(
    Path(__file__).resolve().parent / "runs"
)
NATIVE_LOG_LEVEL = (os.getenv("NATIVE_LOG_LEVEL") or "info").strip().lower()
NATIVE_PARALLELISM = max(1, int(os.getenv("NATIVE_PARALLELISM") or 2))
BITGN_FEEDBACK_MODE = (os.getenv("BITGN_FEEDBACK_MODE") or "strict").strip().lower()
MANIFEST_LOCK = threading.Lock()


def _env_enabled(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


NATIVE_PREFLIGHT_CONTEXT = _env_enabled("NATIVE_PREFLIGHT_CONTEXT", "0")
NATIVE_PREFLIGHT_TREE_DEPTH = max(1, min(int(os.getenv("NATIVE_PREFLIGHT_TREE_DEPTH") or 2), 4))
NATIVE_PREFLIGHT_PROMPT_LIMIT = max(2000, int(os.getenv("NATIVE_PREFLIGHT_PROMPT_LIMIT") or 16000))
NATIVE_PREFLIGHT_SCHEMA_LIMIT = max(1000, int(os.getenv("NATIVE_PREFLIGHT_SCHEMA_LIMIT") or 10000))
NATIVE_EXEC_FINISH_HELPER = _env_enabled("NATIVE_EXEC_FINISH_HELPER", "0")
NATIVE_EXEC_RUN_HELPER = _env_enabled("NATIVE_EXEC_RUN_HELPER", "0")
NATIVE_FINALIZE_RESCUE = _env_enabled("NATIVE_FINALIZE_RESCUE", "0")
NATIVE_FINALIZE_RESCUE_ATTEMPTS = max(0, min(int(os.getenv("NATIVE_FINALIZE_RESCUE_ATTEMPTS") or 1), 3))
NATIVE_ECOM_METHOD_CARDS = _env_enabled("NATIVE_ECOM_METHOD_CARDS", "0")
NATIVE_ECOM_METHOD_CARD_LIMIT = max(1, min(int(os.getenv("NATIVE_ECOM_METHOD_CARD_LIMIT") or 1), 4))
NATIVE_ECOM_METHOD_CARD_MIN_SCORE = max(1, int(os.getenv("NATIVE_ECOM_METHOD_CARD_MIN_SCORE") or 1))
NATIVE_ECOM_METHOD_CARD_SOURCE = (os.getenv("NATIVE_ECOM_METHOD_CARD_SOURCE") or "").strip()


def _feedback_optional() -> bool:
    return BITGN_FEEDBACK_MODE in {"optional", "best_effort", "soft"}


def _retry_after_seconds(text: str) -> int | None:
    patterns = [
        r"Retry-After[^0-9]*(\d+)",
        r"retry after[^0-9]*(\d+)",
        r"wait[^0-9]*(\d+)\s*seconds?",
        r"(\d+)\s*seconds?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
    return None


def _call_bitgn(label: str, func: Any, *, attempts: int = 3) -> Any:
    max_sleep = max(1, int(os.getenv("BITGN_RATE_LIMIT_MAX_SLEEP_SEC") or 900))
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return func()
        except ConnectError as exc:
            text = f"{getattr(exc, 'code', '')} {getattr(exc, 'message', '')}"
            rate_limited = "CodeResourceExhausted" in text or "ResourceExhausted" in text
            retryable = rate_limited or "Bad Gateway" in text or "Unavailable" in text
            if not retryable or attempt >= attempts:
                raise
            delay = _retry_after_seconds(text) if rate_limited else None
            if delay is None:
                delay = min(30, attempt * 5)
            delay = min(delay, max_sleep)
            _cli(f"[BITGN] {label} retry {attempt}/{attempts - 1} after {delay}s: {text}")
            time.sleep(delay)


def _prepare_leaderboard_trials(
    *, client: HarnessServiceClientSync, task_ids: list[str]
) -> tuple[dict[str, dict[str, str]], str | None]:
    if not BITGN_API_KEY:
        return {}, None
    ordered_task_ids = list(dict.fromkeys(task_ids))
    requested = set(ordered_task_ids)
    run_req = StartRunRequest(
        benchmark_id=BENCHMARK_ID,
        name=BITGN_RUN_NAME or f"{AGENT_BACKBONE}-native {AGENT_MODEL}",
    )
    if hasattr(run_req, "api_key"):
        setattr(run_req, "api_key", BITGN_API_KEY)
        run = _call_bitgn("StartRun", lambda: client.start_run(run_req), attempts=5)
        run_id = str(run.run_id)
        trial_ids = [str(tid) for tid in run.trial_ids]
    else:
        run_id, trial_ids = _start_run_via_connect_json(
            benchmark_id=BENCHMARK_ID,
            name=BITGN_RUN_NAME or f"{AGENT_BACKBONE}-native {AGENT_MODEL}",
            api_key=BITGN_API_KEY,
        )
        _cli(
            "[LEADERBOARD] Using Connect JSON fallback for StartRun "
            "(SDK has no api_key field)."
        )

    seeds: dict[str, dict[str, str]] = {}
    for trial_id in trial_ids:
        trial = _call_bitgn("StartTrial", lambda trial_id=trial_id: client.start_trial(StartTrialRequest(trial_id=trial_id)), attempts=5)
        task_id = str(trial.task_id)
        if requested and task_id not in requested:
            continue
        if task_id in seeds:
            continue
        seeds[task_id] = {
            "trial_id": str(trial.trial_id),
            "task_id": task_id,
            "instruction": str(trial.instruction),
            "harness_url": str(trial.harness_url),
            "run_id": run_id,
            "source": "leaderboard",
        }
        if len(seeds) == len(requested):
            break
    missing = [task_id for task_id in ordered_task_ids if task_id not in seeds]
    if missing:
        _cli(
            "[LEADERBOARD] Could not prepare trials for tasks: "
            + ", ".join(missing)
            + ". Falling back to playground mode."
        )
        try:
            _call_bitgn("SubmitRun", lambda: client.submit_run(SubmitRunRequest(run_id=run_id, force=True)), attempts=5)
        except ConnectError:
            pass
        return {}, None
    _cli(f"[LEADERBOARD] Prepared run_id={run_id} tasks={len(seeds)}")
    return seeds, run_id



def _read_optional_api_key() -> str:
    for raw in [
        os.getenv("BITGN_ECOM_API_KEY"),
        os.getenv("BITGN_API_KEY"),
    ]:
        value = (raw or "").strip()
        if value:
            return value
    for candidate in [
        os.getenv("BITGN_ECOM_API_KEY_FILE"),
        os.getenv("BITGN_API_KEY_FILE"),
        str(Path.home() / ".bitgn" / "bitgn-api-key"),
    ]:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists() and path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return ""


def _prepare_normal_trials(*, client: HarnessServiceClientSync, task_ids: list[str]) -> dict[str, dict[str, str]]:
    ordered_task_ids = list(dict.fromkeys(task_ids))
    if not ordered_task_ids:
        return {}
    api_key = _read_optional_api_key()
    if not api_key:
        raise RuntimeError("Normal StartRun/StartTrial requires a BitGN API key; set BITGN_API_KEY or keep ~/.bitgn/bitgn-api-key available.")
    _cli(f"[NORMAL] Preparing trial seeds serially for {len(ordered_task_ids)} task(s)")
    _cli(f"[NORMAL] Connecting to BitGN {_call_bitgn('Status', lambda: client.status(StatusRequest()), attempts=5)}")
    benchmark = _call_bitgn("GetBenchmark", lambda: client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID)), attempts=5)
    _cli(f"[NORMAL] {EvalPolicy.Name(benchmark.policy)} benchmark: {benchmark.benchmark_id}")
    run = _call_bitgn(
        "StartRun",
        lambda: client.start_run(
            StartRunRequest(
                benchmark_id=BENCHMARK_ID,
                name=f"cli-native-prep-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                api_key=api_key,
            )
        ),
        attempts=5,
    )
    run_id = str(run.run_id)
    requested = set(ordered_task_ids)
    seeds: dict[str, dict[str, str]] = {}
    for trial_id_raw in run.trial_ids:
        trial = _call_bitgn(
            "StartTrial",
            lambda trial_id_raw=trial_id_raw: client.start_trial(StartTrialRequest(trial_id=str(trial_id_raw))),
            attempts=5,
        )
        task_id = str(trial.task_id)
        if task_id not in requested or task_id in seeds:
            continue
        seeds[task_id] = {
            "trial_id": str(trial.trial_id),
            "task_id": task_id,
            "instruction": str(trial.instruction),
            "harness_url": str(trial.harness_url),
            "run_id": run_id,
            "source": "normal-run",
        }
        _cli(f"[NORMAL] Prepared trial seed task={task_id} trial_id={trial.trial_id}")
        if len(seeds) == len(requested):
            break
    missing = [task_id for task_id in ordered_task_ids if task_id not in seeds]
    if missing:
        raise RuntimeError(f"Normal run {run_id} did not include requested task(s): {', '.join(missing)}")
    _cli(f"[NORMAL] Prepared run_id={run_id} tasks={len(seeds)}")
    return seeds


def _prepare_ecom_trials(*, client: HarnessServiceClientSync, task_ids: list[str]) -> dict[str, dict[str, str]]:
    return _prepare_normal_trials(client=client, task_ids=task_ids)


def _start_run_via_connect_json(
    *, benchmark_id: str, name: str, api_key: str
) -> tuple[str, list[str]]:
    endpoint = f"{BITGN_URL.rstrip('/')}/bitgn.harness.HarnessService/StartRun"
    payload = {
        "benchmarkId": benchmark_id,
        "name": name,
        "apiKey": api_key,
    }
    req = urlrequest.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        raise RuntimeError(f"StartRun fallback failed: HTTP {exc.code}") from exc
    data = json.loads(body)
    run_id = str(data.get("runId", "")).strip()
    trial_ids = [str(x).strip() for x in data.get("trialIds", []) if str(x).strip()]
    if not run_id or not trial_ids:
        raise RuntimeError("StartRun fallback returned empty runId/trialIds")
    return run_id, trial_ids


def _cli(msg: str) -> None:
    print(msg, flush=True)


def _stage(name: str, detail: str = "", task_id: str = "") -> None:
    prefix = f"[{task_id}] " if task_id else ""
    if detail:
        _cli(f"{prefix}[STAGE] {name}: {detail}")
    else:
        _cli(f"{prefix}[STAGE] {name}")


def _extract_tool_name(command: str) -> str:
    m = re.search(r"runtime_tools\.py\s+([a-z_]+)", command)
    if not m:
        return ""
    return str(m.group(1) or "").strip()


def _render_codex_event(evt: dict[str, Any]) -> str | None:
    t = str(evt.get("type", ""))
    if t == "turn.started":
        return "[CODEX] turn started"
    if t == "turn.completed":
        usage = evt.get("usage")
        if isinstance(usage, dict):
            inp = int(usage.get("input_tokens", 0) or 0)
            out = int(usage.get("output_tokens", 0) or 0)
            return (
                f"[CODEX] turn completed tokens: in={inp} out={out} total={inp + out}"
            )
        return "[CODEX] turn completed"
    if t == "item.started":
        item = evt.get("item")
        if isinstance(item, dict) and str(item.get("type", "")) == "command_execution":
            tool = _extract_tool_name(str(item.get("command", "")))
            if tool:
                return f"[CODEX] tool start: {tool}"
            return "[CODEX] command start"
    if t == "item.completed":
        item = evt.get("item")
        if isinstance(item, dict) and str(item.get("type", "")) == "command_execution":
            tool = _extract_tool_name(str(item.get("command", "")))
            code = item.get("exit_code")
            status = str(item.get("status", ""))
            if tool:
                return f"[CODEX] tool done: {tool} status={status} code={code}"
            return f"[CODEX] command done status={status} code={code}"
        if (
            isinstance(item, dict)
            and str(item.get("type", "")) == "agent_message"
            and NATIVE_LOG_LEVEL == "debug"
        ):
            text = str(item.get("text", "")).strip().replace("\n", " ")
            if text:
                if len(text) > 240:
                    text = text[:240] + "..."
                return f"[CODEX] {text}"
    if NATIVE_LOG_LEVEL == "debug":
        return f"[CODEX RAW] {json.dumps(evt, ensure_ascii=True)}"
    return None


def _render_pi_event(evt: dict[str, Any]) -> str | None:
    t = str(evt.get("type", ""))
    if t == "turn_start":
        return "[PI] turn started"
    if t == "turn_end":
        message = evt.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            inp = int(usage.get("input", 0) or 0)
            out = int(usage.get("output", 0) or 0)
            total = int(usage.get("totalTokens", inp + out) or 0)
            return f"[PI] turn completed tokens: in={inp} out={out} total={total}"
        return "[PI] turn completed"
    if t in {"tool_start", "tool_execution_start"}:
        tool = str(evt.get("tool") or evt.get("toolName") or evt.get("name") or "").strip()
        return f"[PI] tool start: {tool}" if tool else "[PI] tool start"
    if t in {"tool_end", "tool_execution_end"}:
        tool = str(evt.get("tool") or evt.get("toolName") or evt.get("name") or "").strip()
        status = str(evt.get("status") or "completed")
        return f"[PI] tool done: {tool} status={status}" if tool else f"[PI] tool done status={status}"
    if t == "agent_start":
        return "[PI] agent started"
    if t == "agent_end":
        return "[PI] agent finished"
    if NATIVE_LOG_LEVEL == "debug":
        return f"[PI RAW] {json.dumps(evt, ensure_ascii=True)}"
    return None


def _usage_from_pi_message(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    if str(message.get("role", "")) != "assistant":
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    inp = int(usage.get("input", 0) or 0)
    out = int(usage.get("output", 0) or 0)
    total = int(usage.get("totalTokens", inp + out) or 0)
    return {
        "tokens_prompt": inp,
        "tokens_completion": out,
        "tokens_total": total,
        "llm_calls": 1,
        "cost": usage.get("cost") if isinstance(usage.get("cost"), dict) else None,
    }


PANGOLIN_TOOL_DEF = {
    "type": "function",
    "name": "execute_code",
    "description": (
        "Execute Python code against the BitGN task workspace. Preloaded objects: "
        "ws, call_tool, run, finish, scratchpad, and JSON-serializable variables "
        "from previous calls. Use finish(...) or ws.answer(scratchpad, verify) to submit."
    ),
    "parameters": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python code to execute."}},
        "required": ["code"],
        "additionalProperties": False,
    },
}


def _pangolin_api_key() -> str:
    for raw in [
        os.getenv("NATIVE_PANGOLIN_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OMNIROUTE_API_KEY"),
        os.getenv("OPENROUTER_API_KEY"),
    ]:
        value = (raw or "").strip()
        if value:
            return value
    for raw_path in [
        os.getenv("NATIVE_PANGOLIN_API_KEY_FILE"),
        os.getenv("OPENAI_API_KEY_FILE"),
        os.getenv("BITGN_OMNIROUTE_KEY_FILE"),
        str(Path.home() / ".codex" / "omniroute-api-key"),
        str(Path.home() / ".codex" / "openai-api-key"),
        str(Path.home() / ".codex" / "openrouter-api-key"),
    ]:
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if path.exists() and path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return ""


def _parse_response_payload(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    if not text.startswith("event:") and not text.startswith("data:"):
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    last: dict[str, Any] = {}
    for event in text.split("\n\n"):
        lines = [line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")]
        data_text = "\n".join(lines).strip()
        if not data_text or data_text == "[DONE]":
            continue
        parsed = json.loads(data_text)
        if isinstance(parsed, dict):
            if parsed.get("type") == "response.completed" and isinstance(parsed.get("response"), dict):
                return parsed["response"]
            last = parsed.get("response") if isinstance(parsed.get("response"), dict) else parsed
    return last


def _extract_response_output(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    blocks: list[dict[str, Any]] = []
    output = data.get("output") if isinstance(data.get("output"), list) else []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            raw_args = item.get("arguments")
            args: dict[str, Any] = {}
            if isinstance(raw_args, str) and raw_args.strip():
                try:
                    parsed = json.loads(raw_args)
                    args = parsed if isinstance(parsed, dict) else {"value": parsed}
                except Exception:
                    args = {"code": raw_args}
            elif isinstance(raw_args, dict):
                args = raw_args
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(item.get("call_id") or item.get("id") or f"call_{len(blocks)}"),
                    "name": str(item.get("name") or ""),
                    "input": args,
                }
            )
            continue
        if item.get("type") in {"message", "output_text", "text"}:
            parts: list[str] = []
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("output_text") or part.get("content")
                        if isinstance(text, str) and text:
                            parts.append(text)
            elif isinstance(item.get("text"), str):
                parts.append(str(item.get("text")))
            text = "\n".join(parts).strip()
            if text:
                blocks.append({"type": "text", "text": text})
    usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    input_details = usage_raw.get("input_tokens_details") if isinstance(usage_raw.get("input_tokens_details"), dict) else {}
    usage = {
        "input_tokens": int(usage_raw.get("input_tokens") or usage_raw.get("prompt_tokens") or 0),
        "output_tokens": int(usage_raw.get("output_tokens") or usage_raw.get("completion_tokens") or 0),
        "cache_read_input_tokens": int(input_details.get("cached_tokens") or 0),
    }
    return blocks, usage


def _pangolin_reasoning_payload() -> dict[str, Any] | None:
    if NATIVE_PANGOLIN_REASONING_ENABLED:
        enabled = NATIVE_PANGOLIN_REASONING_ENABLED in {"1", "true", "yes", "on"}
        return {"enabled": enabled}
    if "openrouter.ai" in NATIVE_PANGOLIN_BASE_URL and NATIVE_PANGOLIN_MODEL.startswith("qwen/"):
        return {"enabled": False}
    return None


def _api_retry_delay(raw: str, attempt: int) -> float:
    fallback = float(attempt)
    try:
        payload = json.loads(raw or "{}")
        retry_after = payload.get("retry_after") if isinstance(payload, dict) else None
        delay = float(retry_after)
    except Exception:
        delay = fallback
    return min(max(delay, fallback), 60.0)


def _post_pangolin_response(*, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    url = NATIVE_PANGOLIN_BASE_URL.rstrip("/") + "/responses"
    data = json.dumps(body, ensure_ascii=True).encode("utf-8")
    max_attempts = max(1, int(os.getenv("NATIVE_PANGOLIN_API_RETRIES") or 5))
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        req = urlrequest.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "bitgn-native-pangolin-loop/0.1",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=180) as resp:
                return _parse_response_payload(resp.read().decode("utf-8", errors="replace"))
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"Pangolin API error {exc.code}: {raw[:1000]}")
            if attempt < max_attempts and exc.code in {429, 500, 502, 503, 504}:
                time.sleep(_api_retry_delay(raw, attempt))
                continue
            raise last_error
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(float(attempt))
                continue
            raise
    raise last_error or RuntimeError("Pangolin API request failed")


_ECOM_METHOD_CARDS_CACHE: list[dict[str, Any]] | None = None


def _method_card_source_candidates() -> list[Path]:
    candidates: list[Path] = []
    if NATIVE_ECOM_METHOD_CARD_SOURCE:
        candidates.append(Path(NATIVE_ECOM_METHOD_CARD_SOURCE).expanduser())
    code_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            code_root / "ecom-operation-overfit" / "hybrid" / "method_cards.py",
            code_root / "bitgn-ecom-pac-overfit-test" / "hybrid" / "method_cards.py",
        ]
    )
    return candidates


def _load_ecom_method_cards() -> list[dict[str, Any]]:
    global _ECOM_METHOD_CARDS_CACHE
    if _ECOM_METHOD_CARDS_CACHE is not None:
        return _ECOM_METHOD_CARDS_CACHE
    for source in _method_card_source_candidates():
        if not source.exists():
            continue
        spec = importlib.util.spec_from_file_location("ecom_method_cards_external", source)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            _cli(f"[METHOD_CARDS] Failed to load {source}: {exc}")
            continue
        cards = getattr(module, "METHOD_CARDS", None)
        if isinstance(cards, list):
            _ECOM_METHOD_CARDS_CACHE = [card for card in cards if isinstance(card, dict)]
            return _ECOM_METHOD_CARDS_CACHE
    _ECOM_METHOD_CARDS_CACHE = []
    return _ECOM_METHOD_CARDS_CACHE


def _score_method_card(instruction: str, card: dict[str, Any]) -> int:
    text = instruction.lower()
    score = 0
    for pattern in card.get("triggers", []):
        try:
            if re.search(str(pattern), text, re.I):
                score += 3
        except re.error:
            continue
    for term in card.get("terms", []):
        if str(term).lower() in text:
            score += 1
    return score


def _compact_method_card(card: dict[str, Any], score: int) -> dict[str, Any]:
    keep_keys = [
        "family",
        "when_to_use",
        "preferred_pipeline",
        "legacy_algorithm",
        "refs_policy",
        "common_failures",
        "source_method",
    ]
    compacted = {key: card.get(key) for key in keep_keys if card.get(key)}
    compacted["match_score"] = score
    return compacted


def _ecom_method_cards_block(instruction: str) -> str:
    if not NATIVE_ECOM_METHOD_CARDS:
        return ""
    cards = _load_ecom_method_cards()
    if not cards:
        return ""
    scored = sorted(
        ((_score_method_card(instruction, card), card) for card in cards),
        key=lambda item: (-item[0], str(item[1].get("family") or "")),
    )
    picked = [
        _compact_method_card(card, score)
        for score, card in scored
        if score >= NATIVE_ECOM_METHOD_CARD_MIN_SCORE
    ][:NATIVE_ECOM_METHOD_CARD_LIMIT]
    if not picked:
        return ""
    text = json.dumps(picked, ensure_ascii=True, indent=2)
    return (
        "Nearest ECOM method-card hints from the legacy deterministic solver. "
        "Use these only as strategy/playbook guidance. Do not copy old values, do not invent refs, "
        "and validate all facts in the current VM with runtime tools before finishing. If a card conflicts "
        "with the task instruction or VM docs, ignore the card.\n"
        "```json\n"
        f"{text}\n"
        "```\n\n"
    )


def _pangolin_instruction(env: str, instruction: str, workspace_root: str) -> str:
    local_rules = harness_seed.render_local_rules_prompt(env=env)
    preflight_context = _load_preflight_context(workspace_root)
    preflight_block = ""
    if preflight_context:
        preflight_block = (
            "Preflight context collected before this agent session:\n"
            "```text\n"
            f"{preflight_context}\n"
            "```\n"
            "Use it as navigation help only; validate task-specific facts with runtime tools.\n\n"
        )
    method_cards_block = _ecom_method_cards_block(instruction) if env == "ecom" else ""
    return (
        "You are an autonomous BitGN task agent running the experimental pangolin_loop backbone.\n"
        "You have exactly one model tool: execute_code. Your first response must call execute_code.\n"
        "Never answer with only planning or ordinary text; perform the next read/search/list/verify action in Python.\n"
        "Inside execute_code, use ws or call_tool for BitGN environment tools. Do not use direct network clients.\n"
        "Helpers available inside Python: ws, call_tool(tool, **kwargs), run(path, args=[], stdin=''), finish(message, outcome='OUTCOME_OK', refs=[], answer=None), scratchpad.\n"
        "Scratchpad and JSON-serializable Python globals persist across execute_code calls. Keep scratchpad compact.\n"
        "For final submission, prefer finish(...). If using ws.answer(scratchpad, verify), define verify(sp) and make it return True only after checking required fields and exact refs.\n"
        "Grounding refs must be exact workspace paths from runtime evidence, never session/, scratchpad/, agent_code/, workbook/, evidence/, mutation/, or local-rules/.\n"
        "BitGN runtime rules must be read from root AGENTS.MD and process/docs files when relevant. If local rules conflict with VM policy/docs, follow VM policy/docs.\n"
        "Do not ask for confirmation. Stop after successful report_completion/finish.\n"
        f"Environment: {env}. Workspace root: {workspace_root}.\n\n"
        f"{preflight_block}"
        f"{method_cards_block}"
        "Local rules:\n"
        "```text\n"
        f"{local_rules}\n"
        "```\n\n"
        "Task instruction:\n"
        f"{instruction}\n"
    )


def _execute_pangolin_code(*, code: str, workspace_root: str, workspace: Any, iteration: int) -> tuple[str, bool]:
    code_dir = Path(workspace.root) / "session" / "pangolin_exec"
    code_dir.mkdir(parents=True, exist_ok=True)
    code_path = code_dir / f"iter_{iteration:03d}.py"
    code_path.write_text(code, encoding="utf-8")
    env_map = os.environ.copy()
    env_map["NATIVE_TASK_WORKSPACE"] = workspace_root
    env_map.setdefault("PANGOLIN_SCRATCHPAD", "1")
    env_map.setdefault("PANGOLIN_SCRATCHPAD_MODE", "v2")
    env_map.setdefault("NATIVE_EXEC_FINISH_HELPER", "1")
    env_map.setdefault("NATIVE_EXEC_RUN_HELPER", "1")
    payload = {"code": code, "step": iteration * 1000, "timeout_sec": 240}
    started = time.time()
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "pi_exec_tool.py")],
        input=json.dumps(payload, ensure_ascii=True),
        cwd=workspace_root,
        env=env_map,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=300,
    )
    output = "\n".join(x for x in [(proc.stdout or "").strip(), (proc.stderr or "").strip()] if x).strip()
    workspace.append_jsonl(
        workspace.agent_session_path,
        {
            "event": "pangolin_execute_code_finished",
            "ts": datetime.now(timezone.utc).isoformat(),
            "iteration": iteration,
            "returncode": proc.returncode,
            "duration_ms": int((time.time() - started) * 1000),
            "code_path": str(code_path),
            "output_tail": output[-4000:],
        },
    )
    return (_truncate_text(output or "ok", 12000), proc.returncode != 0)


def _message_text(message: dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    if isinstance(message.get("content"), str):
        return str(message.get("content") or "")
    if isinstance(message.get("output"), str):
        return str(message.get("output") or "")
    if isinstance(message.get("arguments"), str):
        return str(message.get("arguments") or "")
    return ""


def _compact_ids(text: str, *, limit: int = 80) -> list[str]:
    found = re.findall(r"\b(?:pay|basket|cust|emp|ret)_[A-Za-z0-9]+\b|/[A-Za-z0-9_./-]+(?:#row=[A-Za-z0-9_-]+)?", text)
    out: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _compact_messages(
    messages: list[dict[str, Any]], *, reason: str, events_path: Path, keep_tail: int = 4
) -> list[dict[str, Any]]:
    if len(messages) <= keep_tail + 2:
        return messages
    head = messages[:1]
    old = messages[1:-keep_tail]
    tail = messages[-keep_tail:]
    tool_names: list[str] = []
    errors: list[str] = []
    snippets: list[str] = []
    ids: list[str] = []
    for msg in old:
        if msg.get("type") == "function_call":
            name = str(msg.get("name") or "")
            if name:
                tool_names.append(name)
        text = _message_text(msg)
        lower = text.lower()
        if "traceback" in lower or "syntaxerror" in lower or "error" in lower:
            errors.append(_truncate_text(" ".join(text.split()), 360))
        ids.extend(_compact_ids(text, limit=120))
        if msg.get("type") == "function_call_output" or msg.get("role") == "assistant":
            compact = _truncate_text(" ".join(text.split()), 280)
            if compact:
                snippets.append(compact)

    seen_ids: list[str] = []
    seen: set[str] = set()
    for item in ids:
        if item not in seen:
            seen.add(item)
            seen_ids.append(item)
        if len(seen_ids) >= 80:
            break

    summary = {
        "reason": reason,
        "omitted_message_count": len(old),
        "tools_seen": sorted(set(tool_names)),
        "notable_errors": errors[-6:],
        "candidate_ids_or_refs": seen_ids,
        "recent_omitted_summaries": snippets[-8:],
        "instruction": "Do not rely on omitted raw output; rerun a targeted query if exact evidence is needed.",
    }
    compacted = head + [
        {
            "role": "user",
            "content": "Compacted previous Pangolin history:\n```json\n"
            + json.dumps(summary, ensure_ascii=True, indent=2)
            + "\n```",
        }
    ] + tail
    try:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "messages_compacted",
                "ts": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "before_count": len(messages),
                "after_count": len(compacted),
                "summary": summary,
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass
    return compacted


def _scratchpad_size(payload: Any) -> int:
    try:
        return len(json.dumps(payload, ensure_ascii=True, default=str))
    except Exception:
        return 0


def _summarize_heavy_value(value: Any, *, artifact_path: str) -> dict[str, Any]:
    if isinstance(value, list):
        return {
            "artifact_path": artifact_path,
            "type": "list",
            "count": len(value),
            "first_sample": value[:2],
            "last_sample": value[-2:] if len(value) > 2 else [],
        }
    if isinstance(value, dict):
        keys = list(value.keys())
        return {
            "artifact_path": artifact_path,
            "type": "dict",
            "count": len(keys),
            "keys_sample": [str(k) for k in keys[:24]],
        }
    return {"artifact_path": artifact_path, "summary": _truncate_text(str(value), 300)}


def _emergency_compact_scratchpad(workspace: Any, *, reason: str, iteration: int, events_path: Path) -> None:
    if NATIVE_PANGOLIN_SCRATCHPAD_COMPACT_BYTES <= 0:
        return
    current = load_json(workspace.pangolin_scratchpad_path, {"refs": []})
    if not isinstance(current, dict):
        return
    if _scratchpad_size(current) <= NATIVE_PANGOLIN_SCRATCHPAD_COMPACT_BYTES:
        return

    artifact_dir = Path(workspace.root) / "session" / "scratchpad_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"scratchpad_raw_iter_{iteration:03d}.json"
    artifact_path.write_text(json.dumps(current, ensure_ascii=True, indent=2, default=str) + "\n", encoding="utf-8")

    keep_names = {
        "refs",
        "candidate_refs",
        "selected_refs",
        "final_refs",
        "final_candidate_refs",
        "supporting_refs",
        "message",
        "answer",
        "outcome",
        "boundary_hypotheses",
        "verification",
    }
    compacted: dict[str, Any] = {}
    for key, value in current.items():
        name = str(key)
        if name in keep_names or "ref" in name.lower():
            compacted[name] = value
            continue
        if _scratchpad_size(value) > 4000:
            compacted[name] = _summarize_heavy_value(value, artifact_path=str(artifact_path))
        else:
            compacted[name] = value
    compacted.setdefault("refs", [])
    compacted["_compacted_raw_artifact"] = str(artifact_path)
    compacted["_compaction_reason"] = reason
    workspace.pangolin_scratchpad_path.write_text(
        json.dumps(compact_scratchpad(compacted), ensure_ascii=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    try:
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "scratchpad_emergency_compacted",
                "ts": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "iteration": iteration,
                "artifact_path": str(artifact_path),
            }, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _pangolin_repair_prompt(reason: str) -> str:
    return (
        f"Repair/finalize mode triggered: {reason}. Keep the next step short. "
        "If the previous code had a syntax/runtime error, fix only that code. "
        "If scratchpad already has enough evidence, finalize now with finish(...) or ws.answer(...). "
        "Do not re-run broad exploration; gather only one targeted missing fact if required."
    )


def _add_usage(acc: dict[str, Any], item: dict[str, Any] | None) -> None:
    if not item:
        return
    acc["llm_calls"] += int(item.get("llm_calls", 0) or 0)
    acc["tokens_prompt"] += int(item.get("tokens_prompt", 0) or 0)
    acc["tokens_completion"] += int(item.get("tokens_completion", 0) or 0)
    acc["tokens_total"] += int(item.get("tokens_total", 0) or 0)


def _copy_bitgn_rules_snapshot_to_root(*, workspace_root: str) -> None:
    files_root = Path(workspace_root) / "initial_files" / "bitgn-rules"
    if not files_root.exists():
        return
    for path in files_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(files_root)
        target = Path(workspace_root) / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _tree_lines(node: dict[str, Any], *, prefix: str = "", max_lines: int = 180) -> list[str]:
    name = str(node.get("name") or "/").strip() or "/"
    kind = str(node.get("kind") or node.get("type") or "").lower()
    is_dir = bool(node.get("isDir", False)) or "dir" in kind or "directory" in kind
    children = node.get("children") if isinstance(node.get("children"), list) else []
    label = name if prefix else name.rstrip("/") or "/"
    if is_dir and label != "/" and not label.endswith("/"):
        label += "/"
    lines = [f"{prefix}{label}"]
    next_prefix = prefix + "  "
    for child in children:
        if len(lines) >= max_lines:
            lines.append(f"{next_prefix}... truncated ...")
            break
        if isinstance(child, dict):
            child_lines = _tree_lines(child, prefix=next_prefix, max_lines=max_lines - len(lines))
            lines.extend(child_lines)
    return lines[:max_lines]


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... truncated to {limit} chars ..."


def _schema_summary(schema_csv: str) -> str:
    lines = [line for line in schema_csv.splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines)


def _load_preflight_context(workspace_root: str) -> str:
    path = Path(workspace_root) / "session" / "preflight_context.md"
    if not path.exists():
        return ""
    try:
        return _truncate_text(path.read_text(encoding="utf-8"), NATIVE_PREFLIGHT_PROMPT_LIMIT)
    except Exception:
        return ""


def _write_preflight_context(*, gateway: ToolGateway, env: str, workspace: Any) -> None:
    if not NATIVE_PREFLIGHT_CONTEXT:
        return
    session_dir = Path(workspace.root) / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = session_dir / "preflight_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    sections: list[str] = [
        "# Preflight context",
        "",
        "This context was collected before the agent started. Use it as navigation and schema help only.",
        "Do not cite files under session/ or preflight_raw/ as grounding refs; cite real VM paths you read or acted on.",
        "",
    ]

    def save_json(name: str, payload: dict[str, Any]) -> None:
        (raw_dir / name).write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def save_text(name: str, text: str) -> None:
        (raw_dir / name).write_text(text, encoding="utf-8")

    try:
        tree = gateway.call(step=-12, tool="tree", args={"path": "/", "max_depth": NATIVE_PREFLIGHT_TREE_DEPTH})
        save_json("tree_root.json", tree)
        root = tree.get("root") if isinstance(tree, dict) else None
        sections.extend(["## Environment tree", ""])
        if isinstance(root, dict):
            sections.extend(["```text", *(_tree_lines(root)), "```", ""])
        else:
            sections.extend(["```json", _truncate_text(json.dumps(tree, ensure_ascii=True), 5000), "```", ""])
    except Exception as exc:
        sections.extend(["## Environment tree", "", f"Preflight tree failed: {exc}", ""])

    if env == "pac1":
        try:
            ctx = gateway.call(step=-12, tool="context", args={})
            save_json("context.json", ctx)
            sections.extend(["## Runtime context", "", "```json", _truncate_text(json.dumps(ctx, ensure_ascii=True, indent=2), 6000), "```", ""])
        except Exception as exc:
            sections.extend(["## Runtime context", "", f"Preflight context failed: {exc}", ""])

    if env == "ecom":
        schema_query = (
            "select m.name as table_name, group_concat(p.name || ' ' || coalesce(p.type, ''), ', ') as columns "
            "from sqlite_schema m join pragma_table_info(m.name) p "
            "where m.type='table' group by m.name order by m.name;"
        )
        try:
            schema = gateway.call(step=-12, tool="exec", args={"path": "/bin/sql", "stdin": schema_query})
            schema_stdout = str(schema.get("stdout", "")) if isinstance(schema, dict) else ""
            save_text("sqlite_schema_columns.csv", schema_stdout)
            sections.extend([
                "## SQLite schema",
                "",
                "Collected with `/bin/sql` before the agent started.",
                "```csv",
                _truncate_text(_schema_summary(schema_stdout), NATIVE_PREFLIGHT_SCHEMA_LIMIT),
                "```",
                "",
            ])
        except Exception as exc:
            sections.extend(["## SQLite schema", "", f"Preflight schema failed: {exc}", ""])

    text = _truncate_text("\n".join(sections).rstrip() + "\n", NATIVE_PREFLIGHT_PROMPT_LIMIT)
    (session_dir / "preflight_context.md").write_text(text, encoding="utf-8")
    workspace.append_jsonl(
        workspace.events_path,
        {
            "event": "preflight_context_written",
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": str(session_dir / "preflight_context.md"),
            "enabled": True,
            "prompt_chars": len(text),
        },
    )


def _resolve_tasks(argv: list[str]) -> list[str]:
    items = [str(x).strip() for x in argv if str(x).strip()]
    if not items:
        return []
    out: list[str] = []
    for item in items:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        for p in parts:
            out.append(p)
    return list(dict.fromkeys(out))


def _resolve_local_run_id() -> str:
    value = (os.getenv("LOCAL_RUN_ID") or "").strip()
    if value:
        clean = "".join(
            ch for ch in value if ch.isalnum() or ch in {"-", "_", "."}
        ).strip("._-")
        if clean.startswith("local_run_"):
            return clean
        return (
            f"local_run_{clean}"
            if clean
            else f"local_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}"
        )
    return f"local_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}"


def _append_run_manifest(
    *, base_dir: str, local_run_id: str, row: dict[str, Any]
) -> None:
    manifest_dir = Path(base_dir) / local_run_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "run_manifest.jsonl"
    line = json.dumps(row, ensure_ascii=True, default=str) + "\n"
    with MANIFEST_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)


def _parse_cli(argv: list[str]) -> tuple[list[str], int, bool]:
    parser = ArgumentParser(description="Run codex-native on selected tasks")
    parser.add_argument("tasks", nargs="+", help="Task ids (space or comma separated)")
    parser.add_argument(
        "-p",
        "--parallelism",
        type=int,
        default=NATIVE_PARALLELISM,
        help="Task parallelism (default: 2)",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop scheduling new tasks after first failure",
    )
    ns = parser.parse_args(argv)
    return (
        _resolve_tasks(list(ns.tasks)),
        max(1, int(ns.parallelism or 1)),
        bool(ns.fail_fast),
    )


def detect_env() -> str:
    if AGENT_ENV:
        return AGENT_ENV
    if "ecom" in BENCHMARK_ID:
        return "ecom"
    if "pac1" in BENCHMARK_ID:
        return "pac1"
    return "sandbox"


def _score_payload(
    score: float | None,
    detail: list[str],
    submission: dict[str, Any],
    usage: dict[str, Any],
    steps: int,
    feedback_status: str = "scored",
    feedback_error: str = "",
) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "passed": (None if score is None else bool(score == 1)),
        "score_detail": detail,
        "submission": submission,
        "usage": usage,
        "steps": steps,
        "feedback_status": feedback_status,
        "feedback_error": feedback_error,
    }


def _session_instruction(env: str, instruction: str, workspace_root: str) -> str:
    if env == "ecom":
        tool_help = "context/tree/find/search/list/read/stat/exec/write/delete/report_completion"
    elif env == "pac1":
        tool_help = "context/tree/find/search/list/read/write/delete/mkdir/move/report_completion"
    else:
        tool_help = "tree/search/list/read/write/delete/report_completion"
    local_rules_agents = harness_seed.render_local_rules_prompt(env=env)
    preflight_context = _load_preflight_context(workspace_root)
    preflight_block = ""
    if preflight_context:
        preflight_block = (
            "Preflight context collected before this agent session:\n"
            "```text\n"
            f"{preflight_context}\n"
            "```\n"
            "Use this to avoid redundant initial exploration. Validate task-specific facts with runtime tools before final actions or grounding refs.\n\n"
        )
    if AGENT_BACKBONE in {"pi", "p-agent", "p_agent"} and PI_TOOL_MODE == "exec":
        finish_guidance = ""
        if NATIVE_EXEC_FINISH_HELPER:
            finish_guidance = (
                "A simplified `finish(message, outcome='OUTCOME_OK', refs=[], answer=None)` helper is available inside Python. "
                "It fills the scratchpad and submits through the same verification/report_completion path. "
                "For finalization, prefer calling `finish(...)` exactly once from inside `exec`, then stop. "
            )
        run_guidance = ""
        if NATIVE_EXEC_RUN_HELPER:
            run_guidance = (
                "A simplified `run(path, args=[], stdin='')` helper is available inside Python for environment exec calls. "
                "Prefer `run('/bin/tool', ['arg1'])` over hand-building call_tool exec arguments. "
            )
        scratchpad_guidance = ""
        if scratchpad_enabled():
            scratchpad_path = Path(workspace_root) / "session" / "pangolin_scratchpad.json"
            current_scratchpad = load_json(scratchpad_path, {"refs": []})
            if not isinstance(current_scratchpad, dict):
                current_scratchpad = {"refs": []}
            current_scratchpad = compact_scratchpad(current_scratchpad)
            scratchpad_text = json.dumps(current_scratchpad, ensure_ascii=True, indent=2)
            compact_note = ""
            if scratchpad_mode() == "v2":
                compact_note = (
                    "Scratchpad mode is v2 compact: do not store raw trees, long query results, full tool outputs, "
                    "large evidence dumps, or duplicate refs/message fields. Store concise decisions and exact final refs only. "
                    "Do heavy scans inside Python and return only concise aggregates; avoid printing raw rows or full JSON dumps. "
                )
            scratchpad_guidance = (
                "Optional Pangolin scratchpad is enabled. Inside each `exec` call, `scratchpad` is a persistent JSON dict, "
                "and JSON-serializable Python globals also persist across later `exec` calls for this task. "
                "The current scratchpad is shown below in this prompt, and each `exec` result returns the updated scratchpad "
                "so it is visible to you on the next model iteration. "
                f"{compact_note}"
                "Keep it compact: goal, target_scope, must_not_touch, mutation_plan, identity_chain, key evidence, refs, "
                "chosen outcome/message, validation status, pre_submit_checks, and remaining risks. "
                "Before finishing, set scratchpad['outcome'], scratchpad['message'] or scratchpad['answer'], and "
                "scratchpad['supporting_refs'] or scratchpad['final_candidate_refs'] or scratchpad['refs']; then define "
                "def verify(sp): ... and call ws.answer(scratchpad, verify). ws.answer runs verify before submitting, "
                "blocks failed verification, checks required fields/outcome/refs, and then calls report_completion for you. "
                f"{finish_guidance}"
                "Direct report_completion is blocked while scratchpad is enabled. "
                "Use checked_refs/private_checked_refs in scratchpad for files you inspected but should not submit as final grounding_refs. "
                "Grounding refs must be exact workspace paths and must never point at runner artifacts such as session/, "
                "scratchpad/, agent_code/, evidence/, mutation/, workbook/, or local-rules/.\n"
                "Current scratchpad:\n"
                "```json\n"
                f"{scratchpad_text}\n"
                "```\n"
            )
        return (
            "You are an autonomous BitGN task agent.\n"
            "Default rules are from local-rules AGENTS content embedded below.\n"
            "BitGN runtime rules must be read from root `AGENTS.MD` and process docs.\n"
            "You may re-read local policy files from `local-rules/` during the session if needed.\n"
            "Treat `local-rules/` as read-only policy memory, not as task facts source.\n"
            "When local-rules guidance conflicts with BitGN VM policy/docs, follow BitGN VM policy/docs.\n"
            "Do not mutate `local-rules/` and do not use `local-rules/*` in grounding_refs.\n"
            "The only agent tool available to you is `exec`. Use it to run Python code.\n"
            "Your first response must include an `exec` tool call. Never respond with only planning, thinking, or ordinary text.\n"
            "Whenever you know the next search/read/list/count/verify step, perform it inside `exec` in the same response.\n"
            "Inside that Python code, call BitGN environment tools through `call_tool(tool, **kwargs)`.\n"
            "A Pangolin-style helper `ws` is also available inside Python; it wraps the same call_tool interface and `ws.answer(scratchpad, verify)` runs your verify function before final submission.\n"
            f"{finish_guidance}"
            f"{run_guidance}"
            "Example: `call_tool('read', path='AGENTS.MD')`.\n"
            "For environment exec tools, use `run('/bin/tool', ['arg'])` when available, `ws.exec(path='/bin/tool', args=['arg'])`, or `call_tool('exec', {'path': '/bin/tool', 'args': ['arg']})`.\n"
            "For list fields, pass Python lists, for example `grounding_refs=['AGENTS.MD']`.\n"
            "When scratchpad is enabled, you MUST finalize with `ws.answer(scratchpad, verify)`; otherwise call `call_tool('report_completion', ...)` exactly once.\n"
            "After the first successful report_completion, stop immediately and do not call more tools.\n"
            "External evaluator feedback may be unavailable; still finish via report_completion once.\n"
            f"{scratchpad_guidance}"
            "Do not ask for confirmation. Keep actions minimal and task-focused.\n"
            f"Environment: {env}. Environment tools reachable from Python: {tool_help}.\n"
            f"Workspace root for artifacts: {workspace_root}.\n\n"
            f"{preflight_block}"
            "Local rules (default):\n"
            "```text\n"
            f"{local_rules_agents}\n"
            "```\n\n"
            "Task instruction:\n"
            f"{instruction}\n"
        )

    return (
        "You are an autonomous BitGN task agent.\n"
        "Default rules are from local-rules AGENTS content embedded below.\n"
        "BitGN runtime rules must be read from root `AGENTS.MD` and process docs.\n"
        "You may re-read local policy files from `local-rules/` during the session if needed.\n"
        "Treat `local-rules/` as read-only policy memory, not as task facts source.\n"
        "When local-rules guidance conflicts with BitGN VM policy/docs, follow BitGN VM policy/docs.\n"
        "Do not mutate `local-rules/` and do not use `local-rules/*` in grounding_refs.\n"
        "Solve the task by calling runtime tools yourself via shell command:\n"
        "python runtime_tools.py <tool> key=value ...\n"
        "For list fields, pass comma-separated values (example: grounding_refs=AGENTS.MD,notes.md).\n"
        "When task is complete, you MUST call report_completion exactly once.\n"
        "After first successful report_completion, stop immediately and do not call more tools.\n"
        "External evaluator feedback may be unavailable; still finish via report_completion once.\n"
        "Do not ask for confirmation. Keep actions minimal and task-focused.\n"
        f"Environment: {env}. Allowed tools: {tool_help}.\n"
        f"Workspace root for artifacts: {workspace_root}.\n\n"
        f"{preflight_block}"
        "Local rules (default):\n"
        "```text\n"
        f"{local_rules_agents}\n"
        "```\n\n"
        "Task instruction:\n"
        f"{instruction}\n"
    )


def _run_codex_session(
    *, env: str, instruction: str, workspace_root: str, workspace: Any, task_id: str
) -> dict[str, Any]:
    prompt = _session_instruction(env, instruction, workspace_root)
    workspace.codex_prompt_path.write_text(prompt + "\n", encoding="utf-8")
    out_path = workspace.codex_last_message_path
    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "--output-last-message",
        str(out_path),
        "--model",
        CODEX_MODEL,
    ]
    if CODEX_PROFILE:
        cmd.extend(["--profile", CODEX_PROFILE])
    elif CODEX_BACKEND == "spark":
        cmd.extend(["-c", "model_provider=openai"])
    cmd.extend(
        [
            "--cd",
            str(Path(__file__).resolve().parent),
            prompt,
        ]
    )

    env_map = os.environ.copy()
    env_map["NATIVE_TASK_WORKSPACE"] = workspace_root

    started_at = datetime.now(timezone.utc)
    _stage(
        "CODEX_SESSION_START",
        f"model={CODEX_MODEL} timeout={max(60, NATIVE_SESSION_TIMEOUT_SEC)}s",
        task_id=task_id,
    )
    proc = subprocess.Popen(
        cmd,
        env=env_map,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("codex session stdout pipe is unavailable")

    deadline = time.monotonic() + float(max(60, NATIVE_SESSION_TIMEOUT_SEC))
    stdout_tail: deque[str] = deque(maxlen=200)
    usage = {
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "tokens_total": 0,
        "llm_calls": 0,
    }
    while True:
        if time.monotonic() > deadline:
            proc.kill()
            raise TimeoutError(
                f"codex session timeout after {max(60, NATIVE_SESSION_TIMEOUT_SEC)}s"
            )

        ready, _, _ = select.select([proc.stdout], [], [], 0.25)
        if ready:
            raw_line = proc.stdout.readline()
            if raw_line:
                line = raw_line.rstrip("\n")
                stdout_tail.append(line)
                workspace.append_jsonl(
                    workspace.codex_session_raw_path,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "line": line,
                    },
                )
                if not line.strip():
                    continue
                try:
                    evt: dict[str, Any] = json.loads(line)
                    workspace.append_jsonl(
                        workspace.codex_session_parsed_path,
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "type": evt.get("type"),
                            "item_type": (evt.get("item") or {}).get("type")
                            if isinstance(evt.get("item"), dict)
                            else None,
                            "item_id": (evt.get("item") or {}).get("id")
                            if isinstance(evt.get("item"), dict)
                            else None,
                            "status": (evt.get("item") or {}).get("status")
                            if isinstance(evt.get("item"), dict)
                            else None,
                            "exit_code": (evt.get("item") or {}).get("exit_code")
                            if isinstance(evt.get("item"), dict)
                            else None,
                            "tool": _extract_tool_name(
                                str((evt.get("item") or {}).get("command", ""))
                            )
                            if isinstance(evt.get("item"), dict)
                            else "",
                            "usage": evt.get("usage")
                            if isinstance(evt.get("usage"), dict)
                            else None,
                        },
                    )
                    rendered = _render_codex_event(evt)
                    if rendered:
                        _cli(f"[{task_id}] {rendered}")
                    if evt.get("type") == "turn.completed" and isinstance(
                        evt.get("usage"), dict
                    ):
                        u = evt["usage"]
                        inp = int(u.get("input_tokens", 0) or 0)
                        out = int(u.get("output_tokens", 0) or 0)
                        usage["llm_calls"] += 1
                        usage["tokens_prompt"] += inp
                        usage["tokens_completion"] += out
                        usage["tokens_total"] += inp + out
                except Exception:
                    if NATIVE_LOG_LEVEL == "debug":
                        _cli(f"[{task_id}] [CODEX TEXT] {line}")
            elif proc.poll() is not None:
                break
        elif proc.poll() is not None:
            break

    returncode = int(proc.wait())
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    _stage("CODEX_SESSION_END", f"returncode={returncode}", task_id=task_id)
    stdout = "\n".join(stdout_tail)

    workspace.write_json(
        workspace.codex_session_meta_path,
        {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "model": CODEX_MODEL,
            "profile": CODEX_PROFILE,
            "backend": CODEX_BACKEND,
            "env": env,
            "returncode": returncode,
            "usage": usage,
        },
    )

    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": "",
        "usage": usage,
    }


def _run_pi_session(
    *, env: str, instruction: str, workspace_root: str, workspace: Any, task_id: str
) -> dict[str, Any]:
    if PI_TOOL_MODE == "exec" and scratchpad_enabled():
        ensure_scratchpad_files(workspace.pangolin_scratchpad_path, workspace.pangolin_state_path)
    prompt = _session_instruction(env, instruction, workspace_root)
    workspace.codex_prompt_path.write_text(prompt + "\n", encoding="utf-8")
    cmd = [
        "pi",
        "--mode",
        "json",
        "--print",
        "--no-session",
        "--no-context-files",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--model",
        PI_MODEL,
    ]
    if PI_TOOL_MODE == "exec":
        cmd.extend(
            [
                "--no-builtin-tools",
                "--extension",
                str(Path(__file__).resolve().parent / "pi-extensions" / "exec-python" / "index.ts"),
                "--tools",
                "exec",
            ]
        )
    else:
        cmd.extend(["--tools", "bash"])
    if PI_PROVIDER:
        cmd.extend(["--provider", PI_PROVIDER])
    if PI_THINKING:
        cmd.extend(["--thinking", PI_THINKING])
    cmd.append(prompt)

    env_map = os.environ.copy()
    env_map["NATIVE_TASK_WORKSPACE"] = workspace_root
    env_map.setdefault("PI_OFFLINE", "1")
    env_map["NATIVE_LOG_LEVEL"] = os.getenv("PI_RUNTIME_TOOL_LOG_LEVEL") or "debug"

    started_at = datetime.now(timezone.utc)
    _stage(
        "PI_SESSION_START",
        f"model={PI_MODEL} timeout={max(60, NATIVE_SESSION_TIMEOUT_SEC)}s",
        task_id=task_id,
    )
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).resolve().parent),
        env=env_map,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("pi session stdout pipe is unavailable")

    deadline = time.monotonic() + float(max(60, NATIVE_SESSION_TIMEOUT_SEC))
    stdout_tail: deque[str] = deque(maxlen=200)
    final_text = ""
    usage = {
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "tokens_total": 0,
        "llm_calls": 0,
    }
    while True:
        if time.monotonic() > deadline:
            proc.kill()
            raise TimeoutError(
                f"pi session timeout after {max(60, NATIVE_SESSION_TIMEOUT_SEC)}s"
            )

        ready, _, _ = select.select([proc.stdout], [], [], 0.25)
        if ready:
            raw_line = proc.stdout.readline()
            if raw_line:
                line = raw_line.rstrip("\n")
                stdout_tail.append(line)
                workspace.append_jsonl(
                    workspace.codex_session_raw_path,
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "line": line,
                    },
                )
                if not line.strip():
                    continue
                try:
                    evt: dict[str, Any] = json.loads(line)
                    message = evt.get("message") if isinstance(evt.get("message"), dict) else None
                    workspace.append_jsonl(
                        workspace.codex_session_parsed_path,
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "type": evt.get("type"),
                            "role": message.get("role") if isinstance(message, dict) else None,
                            "tool": evt.get("tool") or evt.get("toolName") or evt.get("name") or "",
                            "usage": message.get("usage") if isinstance(message, dict) else None,
                        },
                    )
                    rendered = _render_pi_event(evt)
                    if rendered:
                        _cli(f"[{task_id}] {rendered}")
                    if evt.get("type") == "message_end" and isinstance(message, dict):
                        item_usage = _usage_from_pi_message(message)
                        _add_usage(usage, item_usage)
                        if str(message.get("role", "")) == "assistant":
                            parts = []
                            for part in message.get("content", []) or []:
                                if isinstance(part, dict) and part.get("type") == "text":
                                    parts.append(str(part.get("text", "")))
                            if parts:
                                final_text = "\n".join(parts)
                except Exception:
                    if NATIVE_LOG_LEVEL == "debug":
                        _cli(f"[{task_id}] [PI TEXT] {line}")
            elif proc.poll() is not None:
                break
        elif proc.poll() is not None:
            break

    returncode = int(proc.wait())
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    _stage("PI_SESSION_END", f"returncode={returncode}", task_id=task_id)
    stdout = "\n".join(stdout_tail)

    workspace.write_json(
        workspace.codex_session_meta_path,
        {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "backbone": "pi",
            "model": PI_MODEL,
            "provider": PI_PROVIDER,
            "thinking": PI_THINKING,
            "tool_mode": PI_TOOL_MODE,
            "pangolin_scratchpad": bool(PI_TOOL_MODE == "exec" and scratchpad_enabled()),
            "env": env,
            "returncode": returncode,
            "usage": usage,
        },
    )
    workspace.codex_last_message_path.write_text(final_text + "\n", encoding="utf-8")

    return {
        "returncode": returncode,
        "stdout": stdout,
        "stderr": "",
        "usage": usage,
    }


def _run_pangolin_session(
    *, env: str, instruction: str, workspace_root: str, workspace: Any, task_id: str
) -> dict[str, Any]:
    api_key = _pangolin_api_key()
    if not api_key:
        raise RuntimeError(
            "AGENT_BACKBONE=pangolin requires NATIVE_PANGOLIN_API_KEY, OPENAI_API_KEY, "
            "OMNIROUTE_API_KEY, OPENROUTER_API_KEY, or a configured key file"
        )
    ensure_scratchpad_files(workspace.pangolin_scratchpad_path, workspace.pangolin_state_path)
    prompt = _pangolin_instruction(env, instruction, workspace_root)
    workspace.codex_prompt_path.write_text(prompt + "\n", encoding="utf-8")

    session_dir = Path(workspace.root) / "session"
    events_path = session_dir / "pangolin_events.jsonl"
    messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]
    stdout_tail: deque[str] = deque(maxlen=80)
    usage = {
        "tokens_prompt": 0,
        "tokens_completion": 0,
        "tokens_total": 0,
        "llm_calls": 0,
        "cache_read_input_tokens": 0,
    }

    started_at = datetime.now(timezone.utc)
    _stage(
        "PANGOLIN_SESSION_START",
        f"model={NATIVE_PANGOLIN_MODEL} iterations={NATIVE_PANGOLIN_MAX_ITERATIONS} timeout={max(60, NATIVE_SESSION_TIMEOUT_SEC)}s",
        task_id=task_id,
    )
    deadline = time.monotonic() + float(max(60, NATIVE_SESSION_TIMEOUT_SEC))
    returncode = 0
    empty_no_tool_calls = 0
    high_context_repeats = 0

    try:
        for iteration in range(1, NATIVE_PANGOLIN_MAX_ITERATIONS + 1):
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"pangolin session timeout after {max(60, NATIVE_SESSION_TIMEOUT_SEC)}s"
                )
            current_sp = load_json(workspace.pangolin_scratchpad_path, {"refs": []})
            if not isinstance(current_sp, dict):
                current_sp = {"refs": []}
            instructions = _pangolin_instruction(env, instruction, workspace_root)
            instructions += (
                "\nCurrent scratchpad:\n```json\n"
                + json.dumps(compact_scratchpad(current_sp), ensure_ascii=True, indent=2)
                + "\n```\n"
            )
            body = {
                "model": NATIVE_PANGOLIN_MODEL,
                "instructions": instructions,
                "input": messages,
                "tools": [PANGOLIN_TOOL_DEF],
                "max_output_tokens": NATIVE_PANGOLIN_MAX_OUTPUT_TOKENS,
            }
            reasoning_payload = _pangolin_reasoning_payload()
            if reasoning_payload is not None:
                body["reasoning"] = reasoning_payload
            call_started = time.time()
            response = _post_pangolin_response(api_key=api_key, body=body)
            blocks, call_usage = _extract_response_output(response)
            usage["llm_calls"] += 1
            usage["tokens_prompt"] += int(call_usage.get("input_tokens", 0) or 0)
            usage["tokens_completion"] += int(call_usage.get("output_tokens", 0) or 0)
            usage["tokens_total"] = usage["tokens_prompt"] + usage["tokens_completion"]
            usage["cache_read_input_tokens"] += int(call_usage.get("cache_read_input_tokens", 0) or 0)
            workspace.append_jsonl(
                events_path,
                {
                    "event": "api_call",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "iteration": iteration,
                    "duration_ms": int((time.time() - call_started) * 1000),
                    "usage": call_usage,
                    "blocks": [{"type": block.get("type"), "name": block.get("name")} for block in blocks],
                },
            )
            _cli(
                f"[{task_id}] [PANGOLIN] iteration={iteration} "
                f"in={call_usage.get('input_tokens', 0)} out={call_usage.get('output_tokens', 0)}"
            )
            input_tokens = int(call_usage.get("input_tokens", 0) or 0)
            output_tokens = int(call_usage.get("output_tokens", 0) or 0)

            tool_calls: list[dict[str, Any]] = []
            text_parts: list[str] = []
            for block in blocks:
                if block.get("type") == "text":
                    text = str(block.get("text") or "")
                    if text:
                        text_parts.append(text)
                        stdout_tail.append(text)
                        workspace.append_jsonl(
                            events_path,
                            {
                                "event": "model_text",
                                "ts": datetime.now(timezone.utc).isoformat(),
                                "iteration": iteration,
                                "text": text,
                            },
                        )
                elif block.get("type") == "tool_use":
                    tool_calls.append(block)

            if text_parts:
                messages.append({"role": "assistant", "content": "\n".join(text_parts)})
            for call in tool_calls:
                messages.append(
                    {
                        "type": "function_call",
                        "call_id": str(call.get("id")),
                        "name": str(call.get("name")),
                        "arguments": json.dumps(call.get("input") or {}, ensure_ascii=True),
                    }
                )

            if not tool_calls:
                if output_tokens <= 2:
                    empty_no_tool_calls += 1
                else:
                    empty_no_tool_calls = 0
                if (
                    NATIVE_PANGOLIN_EMPTY_GUARD_COUNT > 0
                    and empty_no_tool_calls >= NATIVE_PANGOLIN_EMPTY_GUARD_COUNT
                ):
                    messages = _compact_messages(
                        messages,
                        reason=f"empty_output_guard_after_{empty_no_tool_calls}_calls",
                        events_path=events_path,
                        keep_tail=2,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": _pangolin_repair_prompt(
                                f"{empty_no_tool_calls} consecutive empty model calls without execute_code"
                            ),
                        }
                    )
                    workspace.append_jsonl(
                        events_path,
                        {
                            "event": "empty_output_guard_triggered",
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "iteration": iteration,
                            "empty_no_tool_calls": empty_no_tool_calls,
                        },
                    )
                    empty_no_tool_calls = 0
                    continue
                messages.append(
                    {
                        "role": "user",
                        "content": "No execute_code call was made. Continue by calling execute_code now, or finish inside execute_code if ready.",
                    }
                )
                if NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS > 0 and input_tokens > NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS:
                    messages = _compact_messages(
                        messages,
                        reason=f"input_tokens_over_{NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS}_no_tool",
                        events_path=events_path,
                        keep_tail=4,
                    )
                continue
            empty_no_tool_calls = 0

            for call in tool_calls:
                name = str(call.get("name") or "")
                inp = call.get("input") if isinstance(call.get("input"), dict) else {}
                workspace.append_jsonl(
                    events_path,
                    {
                        "event": "tool_call",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "iteration": iteration,
                        "name": name,
                    },
                )
                if name != "execute_code":
                    result_text, is_error = f"Unknown tool: {name}", True
                else:
                    result_text, is_error = _execute_pangolin_code(
                        code=str(inp.get("code") or ""),
                        workspace_root=workspace_root,
                        workspace=workspace,
                        iteration=iteration,
                    )
                stdout_tail.append(result_text)
                messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": str(call.get("id")),
                        "output": result_text,
                    }
                )
                workspace.append_jsonl(
                    events_path,
                    {
                        "event": "tool_result",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "iteration": iteration,
                        "name": name,
                        "is_error": is_error,
                        "output_tail": result_text[-4000:],
                    },
                )
                if (
                    is_error
                    and NATIVE_PANGOLIN_SYNTAX_REPAIR
                    and re.search(r"\bSyntaxError\b", result_text)
                    and not workspace.submission_path.exists()
                ):
                    messages = _compact_messages(
                        messages,
                        reason="syntax_error_repair",
                        events_path=events_path,
                        keep_tail=2,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": _pangolin_repair_prompt("execute_code returned SyntaxError"),
                        }
                    )
                    workspace.append_jsonl(
                        events_path,
                        {
                            "event": "syntax_error_repair_prompted",
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "iteration": iteration,
                        },
                    )
                if workspace.submission_path.exists():
                    _stage("PANGOLIN_SESSION_END", f"submitted iteration={iteration}", task_id=task_id)
                    break
            if workspace.submission_path.exists():
                break
            if NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS > 0 and input_tokens > NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS:
                high_context_repeats += 1
                if high_context_repeats >= 2:
                    _emergency_compact_scratchpad(
                        workspace,
                        reason=f"input_tokens_still_over_{NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS}",
                        iteration=iteration,
                        events_path=events_path,
                    )
                messages = _compact_messages(
                    messages,
                    reason=f"input_tokens_over_{NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS}",
                    events_path=events_path,
                    keep_tail=4,
                )
            else:
                high_context_repeats = 0
        else:
            returncode = 1
    except Exception:
        returncode = 1
        raise
    finally:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        meta = {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": duration_ms,
            "backbone": "pangolin_loop",
            "model": NATIVE_PANGOLIN_MODEL,
            "provider_base_url": NATIVE_PANGOLIN_BASE_URL,
            "env": env,
            "returncode": returncode,
            "usage": usage,
            "iterations": usage["llm_calls"],
            "scratchpad_path": str(workspace.pangolin_scratchpad_path),
            "state_path": str(workspace.pangolin_state_path),
            "empty_guard_count": NATIVE_PANGOLIN_EMPTY_GUARD_COUNT,
            "syntax_repair": NATIVE_PANGOLIN_SYNTAX_REPAIR,
            "context_compact_tokens": NATIVE_PANGOLIN_CONTEXT_COMPACT_TOKENS,
            "scratchpad_compact_bytes": NATIVE_PANGOLIN_SCRATCHPAD_COMPACT_BYTES,
            "ecom_method_cards": NATIVE_ECOM_METHOD_CARDS,
            "ecom_method_card_limit": NATIVE_ECOM_METHOD_CARD_LIMIT,
            "ecom_method_card_min_score": NATIVE_ECOM_METHOD_CARD_MIN_SCORE,
        }
        workspace.write_json(workspace.codex_session_meta_path, meta)
        workspace.write_json(session_dir / "pangolin_session_meta.json", meta)
        workspace.codex_last_message_path.write_text("\n".join(stdout_tail) + "\n", encoding="utf-8")

    if not workspace.submission_path.exists():
        raise RuntimeError("pangolin_loop finished without explicit finish/ws.answer/report_completion (submission.json missing)")
    return {
        "returncode": returncode,
        "stdout": "\n".join(stdout_tail),
        "stderr": "",
        "usage": usage,
    }


def _run_agent_session(
    *, env: str, instruction: str, workspace_root: str, workspace: Any, task_id: str
) -> dict[str, Any]:
    if AGENT_BACKBONE == "codex":
        return _run_codex_session(
            env=env,
            instruction=instruction,
            workspace_root=workspace_root,
            workspace=workspace,
            task_id=task_id,
        )
    if AGENT_BACKBONE in {"pi", "p-agent", "p_agent"}:
        return _run_pi_session(
            env=env,
            instruction=instruction,
            workspace_root=workspace_root,
            workspace=workspace,
            task_id=task_id,
        )
    if AGENT_BACKBONE in {"pangolin", "pangolin_loop"}:
        return _run_pangolin_session(
            env=env,
            instruction=instruction,
            workspace_root=workspace_root,
            workspace=workspace,
            task_id=task_id,
        )
    raise ValueError(f"Unsupported AGENT_BACKBONE={AGENT_BACKBONE!r}")


def _hydrate_initial_workspace_files(
    *, gateway: ToolGateway, env: str, workspace_root: str
) -> None:
    files_root = Path(workspace_root) / "initial_files"
    files_root.mkdir(parents=True, exist_ok=True)
    harness_seed.copy_local_harness_into_workspace(target_dir=files_root)

    def save_text(rel_path: str, content: str) -> None:
        clean = rel_path.strip().replace("\\", "/").lstrip("/")
        if not clean:
            return
        if clean.lower().endswith(".md"):
            pass
        target = files_root / "bitgn-rules" / clean
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    if env == "pac1":
        core_candidates = [
            "AGENTS.MD",
            "README.md",
            "99_process/process_tasks.md",
            "99_process/document_capture.md",
            "99_process/document_cleanup.md",
        ]
        for rel in core_candidates:
            try:
                ts = time.time()
                read_pb = gateway.vm.read(PcmReadRequest(path=rel, number=False, start_line=0, end_line=0))
                read_out = MessageToDict(read_pb)
                content = str(read_out.get("content", ""))
                gateway._append_tool_call(step=-11, tool="read", args={"path": rel, "number": False, "start_line": 0, "end_line": 0}, ts_start=ts, result=read_out, error=None)
                save_text(rel, content)
            except Exception:
                continue
    elif env == "ecom":
        for rel in ["/AGENTS.MD", "/docs/README.md", "/docs/security.md"]:
            try:
                ts = time.time()
                read_pb = gateway.vm.read(EcomReadRequest(path=rel, number=False, start_line=0, end_line=0))
                read_out = MessageToDict(read_pb)
                content = str(read_out.get("content", ""))
                gateway._append_tool_call(step=-11, tool="read", args={"path": rel, "number": False, "start_line": 0, "end_line": 0}, ts_start=ts, result=read_out, error=None)
                save_text(rel, content)
            except Exception:
                continue
    else:
        # sandbox mini runtime: keep deterministic minimal snapshot
        try:
            ts = time.time()
            read_pb = gateway.vm.read(ReadRequest(path="AGENTS.MD"))
            read_out = MessageToDict(read_pb)
            content = str(read_out.get("content", ""))
            gateway._append_tool_call(
                step=-11,
                tool="read",
                args={"path": "AGENTS.MD"},
                ts_start=ts,
                result=read_out,
                error=None,
            )
            save_text("AGENTS.MD", content)
        except Exception:
            pass


def _run_single_task(
    *,
    env: str,
    task_id: str,
    local_run_id: str,
    trial_seed: dict[str, str] | None = None,
    leaderboard_run_id: str | None = None,
) -> dict[str, Any]:

    _stage(
        "TASK_START",
        f"env={env} benchmark={BENCHMARK_ID} task={task_id} local_run_id={local_run_id}",
        task_id=task_id,
    )
    client = HarnessServiceClientSync(BITGN_URL)
    if trial_seed is None:
        _cli(f"[{task_id}] Connecting to BitGN {client.status(StatusRequest())}")
        benchmark = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
        _cli(
            f"[{task_id}] {EvalPolicy.Name(benchmark.policy)} benchmark: {benchmark.benchmark_id}"
        )
        trial = client.start_playground(
            StartPlaygroundRequest(benchmark_id=BENCHMARK_ID, task_id=task_id)
        )
        trial_id = str(trial.trial_id)
        harness_url = str(trial.harness_url)
        instruction = str(trial.instruction)
    else:
        trial_id = str(trial_seed.get("trial_id", ""))
        harness_url = str(trial_seed.get("harness_url", ""))
        instruction = str(trial_seed.get("instruction", ""))
        if not trial_id or not harness_url:
            raise RuntimeError(
                f"Prepared trial seed is invalid for task {task_id}: {trial_seed}"
            )
        seed_source = str(trial_seed.get("source", "prepared"))
        _cli(f"[{task_id}] Using prepared {seed_source} trial {trial_id}")

    _cli(f"[{task_id}] Task {task_id}: {instruction}")

    workspace = create_task_workspace(
        base_dir=NATIVE_RUNS_DIR,
        benchmark_id=BENCHMARK_ID,
        task_id=task_id,
        env=env,
        model=AGENT_MODEL,
        local_run_id=local_run_id,
    )
    workspace.instruction_path.write_text(instruction + "\n", encoding="utf-8")
    _stage("WORKSPACE_READY", str(workspace.root), task_id=task_id)
    workspace.append_jsonl(
        workspace.events_path,
        {
            "event": "task_started",
            "ts": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id,
            "local_run_id": local_run_id,
            "benchmark_id": BENCHMARK_ID,
            "env": env,
            "workspace": str(workspace.root),
        },
    )

    gateway = ToolGateway(
        env=env, harness_url=harness_url, workspace=workspace, task_id=task_id
    )
    workspace.write_json(
        workspace.context_path,
        {
            "env": env,
            "task_id": task_id,
            "local_run_id": local_run_id,
            "benchmark_id": BENCHMARK_ID,
            "harness_url": harness_url,
            "workspace_root": str(workspace.root),
        },
    )
    files_root = Path(workspace.root) / "initial_files"
    _stage("LOCAL_RULES_SNAPSHOT", task_id=task_id)
    copied = harness_seed.copy_local_harness_into_workspace(target_dir=files_root)
    workspace.append_jsonl(
        workspace.events_path,
        {
            "event": "local_rules_snapshot",
            "ts": datetime.now(timezone.utc).isoformat(),
            "copied_files": copied,
        },
    )
    try:
        _stage("BITGN_RULES_HYDRATION", task_id=task_id)
        _hydrate_initial_workspace_files(
            gateway=gateway, env=env, workspace_root=str(workspace.root)
        )
        _copy_bitgn_rules_snapshot_to_root(workspace_root=str(workspace.root))
        snapshot_root = Path(workspace.root) / "initial_files"
        has_snapshot = snapshot_root.exists() and any(
            p.is_file() for p in snapshot_root.rglob("*")
        )
        if not has_snapshot:
            snapshot_root.mkdir(parents=True, exist_ok=True)
            (snapshot_root / "TASK_INSTRUCTION.md").write_text(
                instruction.strip() + "\n", encoding="utf-8"
            )
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "initial_files_hydrated",
                "ts": datetime.now(timezone.utc).isoformat(),
                "target": str(Path(workspace.root) / "initial_files"),
                "fallback_used": not has_snapshot,
            },
        )
    except Exception as exc:
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "initial_files_hydration_error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )

    try:
        if NATIVE_PREFLIGHT_CONTEXT:
            _stage("PREFLIGHT_CONTEXT", task_id=task_id)
            _write_preflight_context(gateway=gateway, env=env, workspace=workspace)
        else:
            workspace.append_jsonl(
                workspace.events_path,
                {
                    "event": "preflight_context_skipped",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "enabled": False,
                },
            )
    except Exception as exc:
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "preflight_context_error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )

    try:
        session_result = _run_agent_session(
            env=env,
            instruction=instruction,
            workspace_root=str(workspace.root),
            workspace=workspace,
            task_id=task_id,
        )
        workspace.write_json(
            workspace.codex_last_message_path,
            {
                "returncode": session_result.get("returncode"),
                "stderr": session_result.get("stderr", "")[:4000],
            },
        )
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": f"{AGENT_BACKBONE}_session_finished",
                "ts": datetime.now(timezone.utc).isoformat(),
                "returncode": session_result.get("returncode"),
            },
        )
        if session_result.get("stdout"):
            session_stdout = str(session_result.get("stdout", ""))
            tail = session_stdout[-4000:]
            workspace.append_jsonl(
                workspace.events_path,
                {
                    "event": f"{AGENT_BACKBONE}_session_stdout_tail",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "text": tail,
                },
            )

        rescue_usage = {
            "tokens_prompt": 0,
            "tokens_completion": 0,
            "tokens_total": 0,
            "llm_calls": 0,
        }
        if not workspace.submission_path.exists() and AGENT_BACKBONE in {"pi", "p-agent", "p_agent"} and NATIVE_FINALIZE_RESCUE:
            for attempt in range(1, NATIVE_FINALIZE_RESCUE_ATTEMPTS + 1):
                workspace.append_jsonl(
                    workspace.events_path,
                    {
                        "event": "finalize_rescue_start",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "attempt": attempt,
                    },
                )
                _stage("FINALIZE_RESCUE", f"attempt={attempt}", task_id=task_id)
                rescue_instruction = (
                    f"{instruction}\n\n"
                    "FINALIZATION RESCUE: the previous agent session ended without a submission. "
                    "Your response must include exactly one `exec` tool call, not ordinary text. "
                    "Use that exec call to solve and finalize the task now. "
                    "If scratchpad already contains enough evidence, submit from it immediately; otherwise gather only the missing evidence inside the same exec call. "
                    "For environment exec calls, prefer `run(path, args)` when available or `ws.exec(path=..., args=[...])`. "
                    "Call `finish(message, outcome, refs, answer=...)` if available; otherwise call `ws.answer(scratchpad, verify)`. "
                    "Use exact final grounding refs from runtime evidence. After finalizing, stop immediately."
                )
                rescue_result = _run_pi_session(
                    env=env,
                    instruction=rescue_instruction,
                    workspace_root=str(workspace.root),
                    workspace=workspace,
                    task_id=task_id,
                )
                _add_usage(rescue_usage, rescue_result.get("usage", {}))
                workspace.append_jsonl(
                    workspace.events_path,
                    {
                        "event": "finalize_rescue_finished",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "attempt": attempt,
                        "returncode": rescue_result.get("returncode"),
                        "submission_exists": workspace.submission_path.exists(),
                    },
                )
                if workspace.submission_path.exists():
                    break

        if workspace.submission_path.exists():
            submission = json.loads(
                workspace.submission_path.read_text(encoding="utf-8")
            )
        else:
            raise RuntimeError(
                f"{AGENT_BACKBONE} session finished without explicit report_completion (submission.json missing)"
            )

        tool_calls = 0
        if workspace.tool_calls_path.exists():
            tool_calls = sum(
                1
                for _ in workspace.tool_calls_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if _.strip()
            )
        agent_result = {
            "submission": submission,
            "usage": session_result.get("usage", {}),
            "steps": tool_calls,
        }
        for key in ("tokens_prompt", "tokens_completion", "tokens_total", "llm_calls"):
            agent_result["usage"][key] = int(agent_result["usage"].get(key, 0) or 0) + int(rescue_usage.get(key, 0) or 0)
    except Exception as exc:
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "agent_error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )
        _append_run_manifest(
            base_dir=NATIVE_RUNS_DIR,
            local_run_id=local_run_id,
            row={
                "ts": datetime.now(timezone.utc).isoformat(),
                "local_run_id": local_run_id,
                "benchmark_id": BENCHMARK_ID,
                "backbone": AGENT_BACKBONE,
                "model": AGENT_MODEL,
                "task_id": task_id,
                "trial_id": trial_id,
                "workspace": str(workspace.root),
                "error": str(exc),
                "leaderboard_run_id": leaderboard_run_id,
            },
        )
        return {
            "task_id": task_id,
            "trial_id": trial_id,
            "ok": False,
            "error": str(exc),
            "workspace": str(workspace.root),
        }

    try:
        _stage("TRIAL_FINISH", task_id=task_id)
        result = _call_bitgn(
            "EndTrial",
            lambda: client.end_trial(EndTrialRequest(trial_id=trial_id)),
            attempts=5,
        )
        score_available = bool(getattr(result, "score_available", True))
        if not score_available:
            score_payload = _score_payload(
                score=None,
                detail=["score pending until run submit or sealed by benchmark policy"],
                submission=agent_result.get("submission", {})
                if isinstance(agent_result, dict)
                else {},
                usage=agent_result.get("usage", {})
                if isinstance(agent_result, dict)
                else {},
                steps=int(agent_result.get("steps", 0) or 0)
                if isinstance(agent_result, dict)
                else 0,
                feedback_status="pending_run_score",
            )
            workspace.write_json(workspace.score_path, score_payload)
            workspace.append_jsonl(
                workspace.events_path,
                {
                    "event": "trial_finished_pending_run_score",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "feedback_status": "pending_run_score",
                },
            )
            _append_run_manifest(
                base_dir=NATIVE_RUNS_DIR,
                local_run_id=local_run_id,
                row={
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "local_run_id": local_run_id,
                    "benchmark_id": BENCHMARK_ID,
                    "backbone": AGENT_BACKBONE,
                    "model": AGENT_MODEL,
                    "task_id": task_id,
                    "trial_id": trial_id,
                    "workspace": str(workspace.root),
                    "score": None,
                    "passed": None,
                    "feedback_status": "pending_run_score",
                    "completion_status": "submitted",
                    "leaderboard_run_id": leaderboard_run_id,
                },
            )
            print(json.dumps(score_payload, ensure_ascii=True, indent=2))
            print(f"[{task_id}] Workspace: {workspace.root}")
            return {
                "task_id": task_id,
                "trial_id": trial_id,
                "ok": True,
                "passed": None,
                "score": None,
                "feedback_status": "pending_run_score",
                "workspace": str(workspace.root),
            }

        score_detail = list(result.score_detail)
        score_payload = _score_payload(
            score=float(result.score),
            detail=score_detail,
            submission=agent_result.get("submission", {})
            if isinstance(agent_result, dict)
            else {},
            usage=agent_result.get("usage", {})
            if isinstance(agent_result, dict)
            else {},
            steps=int(agent_result.get("steps", 0) or 0)
            if isinstance(agent_result, dict)
            else 0,
            feedback_status="scored",
        )
        workspace.write_json(workspace.score_path, score_payload)
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "trial_finished",
                "ts": datetime.now(timezone.utc).isoformat(),
                "score": float(result.score),
                "score_detail": score_detail,
                "feedback_status": "scored",
            },
        )
        _append_run_manifest(
            base_dir=NATIVE_RUNS_DIR,
            local_run_id=local_run_id,
            row={
                "ts": datetime.now(timezone.utc).isoformat(),
                "local_run_id": local_run_id,
                "benchmark_id": BENCHMARK_ID,
                "backbone": AGENT_BACKBONE,
                "model": AGENT_MODEL,
                "task_id": task_id,
                "trial_id": trial_id,
                "workspace": str(workspace.root),
                "score": float(result.score),
                "passed": bool(result.score == 1),
                "feedback_status": "scored",
                "leaderboard_run_id": leaderboard_run_id,
            },
        )
        print(json.dumps(score_payload, ensure_ascii=True, indent=2))
        print(f"[{task_id}] Workspace: {workspace.root}")
        return {
            "task_id": task_id,
            "trial_id": trial_id,
            "ok": bool(result.score == 1),
            "passed": bool(result.score == 1),
            "score": float(result.score),
            "workspace": str(workspace.root),
        }
    except ConnectError as exc:
        submission = (
            agent_result.get("submission", {}) if isinstance(agent_result, dict) else {}
        )
        usage = agent_result.get("usage", {}) if isinstance(agent_result, dict) else {}
        steps = (
            int(agent_result.get("steps", 0) or 0)
            if isinstance(agent_result, dict)
            else 0
        )
        feedback_error = str(exc.message)
        workspace.append_jsonl(
            workspace.events_path,
            {
                "event": "end_trial_error",
                "ts": datetime.now(timezone.utc).isoformat(),
                "error": feedback_error,
            },
        )

        if _feedback_optional():
            score_payload = _score_payload(
                score=None,
                detail=[f"feedback unavailable: {feedback_error}"],
                submission=submission,
                usage=usage,
                steps=steps,
                feedback_status="unavailable",
                feedback_error=feedback_error,
            )
            workspace.write_json(workspace.score_path, score_payload)
            workspace.append_jsonl(
                workspace.events_path,
                {
                    "event": "trial_finished_without_feedback",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "feedback_error": feedback_error,
                },
            )
            _append_run_manifest(
                base_dir=NATIVE_RUNS_DIR,
                local_run_id=local_run_id,
                row={
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "local_run_id": local_run_id,
                    "benchmark_id": BENCHMARK_ID,
                    "backbone": AGENT_BACKBONE,
                    "model": AGENT_MODEL,
                    "task_id": task_id,
                    "trial_id": trial_id,
                    "workspace": str(workspace.root),
                    "score": None,
                    "passed": None,
                    "feedback_status": "unavailable",
                    "feedback_error": feedback_error,
                    "completion_status": "submitted",
                    "leaderboard_run_id": leaderboard_run_id,
                },
            )
            print(
                f"[{task_id}] EndTrial feedback unavailable (optional mode): {exc.code} {feedback_error}"
            )
            print(f"[{task_id}] Workspace: {workspace.root}")
            return {
                "task_id": task_id,
                "trial_id": trial_id,
                "ok": True,
                "passed": None,
                "score": None,
                "feedback_status": "unavailable",
                "workspace": str(workspace.root),
            }

        _append_run_manifest(
            base_dir=NATIVE_RUNS_DIR,
            local_run_id=local_run_id,
            row={
                "ts": datetime.now(timezone.utc).isoformat(),
                "local_run_id": local_run_id,
                "benchmark_id": BENCHMARK_ID,
                "backbone": AGENT_BACKBONE,
                "model": AGENT_MODEL,
                "task_id": task_id,
                "trial_id": trial_id,
                "workspace": str(workspace.root),
                "error": feedback_error,
                "feedback_status": "failed",
                "leaderboard_run_id": leaderboard_run_id,
            },
        )
        print(f"[{task_id}] EndTrial failed: {exc.code} {feedback_error}")
        print(f"[{task_id}] Workspace: {workspace.root}")
        return {
            "task_id": task_id,
            "trial_id": trial_id,
            "ok": False,
            "error": feedback_error,
            "workspace": str(workspace.root),
        }


def _load_score_context(workspace_path: str) -> tuple[dict[str, Any], dict[str, Any], int]:
    workspace_root = Path(workspace_path)
    score_path = workspace_root / "score.json"
    if score_path.exists():
        try:
            payload = json.loads(score_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                submission = payload.get("submission") if isinstance(payload.get("submission"), dict) else {}
                usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                steps = int(payload.get("steps", 0) or 0)
                return submission, usage, steps
        except Exception:
            pass
    submission_path = workspace_root / "submission.json"
    submission: dict[str, Any] = {}
    if submission_path.exists():
        try:
            loaded = json.loads(submission_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                submission = loaded
        except Exception:
            pass
    return submission, {}, 0


def _write_score_result(
    *,
    local_run_id: str,
    result: dict[str, Any],
    score: float | None,
    detail: list[str],
    feedback_status: str,
    feedback_error: str = "",
) -> None:
    workspace_path = str(result.get("workspace", ""))
    if not workspace_path:
        return
    submission, usage, steps = _load_score_context(workspace_path)
    score_payload = _score_payload(
        score=score,
        detail=detail,
        submission=submission,
        usage=usage,
        steps=steps,
        feedback_status=feedback_status,
        feedback_error=feedback_error,
    )
    workspace_root = Path(workspace_path)
    workspace_root.joinpath("score.json").write_text(
        json.dumps(score_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    result["score"] = score
    result["passed"] = None if score is None else bool(score == 1)
    result["ok"] = bool(result.get("ok", True)) if score is None else bool(score == 1)
    result["feedback_status"] = feedback_status
    _append_run_manifest(
        base_dir=NATIVE_RUNS_DIR,
        local_run_id=local_run_id,
        row={
            "ts": datetime.now(timezone.utc).isoformat(),
            "local_run_id": local_run_id,
            "benchmark_id": BENCHMARK_ID,
            "backbone": AGENT_BACKBONE,
            "model": AGENT_MODEL,
            "task_id": result.get("task_id"),
            "trial_id": result.get("trial_id"),
            "workspace": workspace_path,
            "score": score,
            "passed": result.get("passed"),
            "feedback_status": feedback_status,
            "feedback_error": feedback_error,
            "run_score_backfill": True,
        },
    )


def _submit_and_backfill_run_scores(
    *,
    run_id: str,
    local_run_id: str,
    results: list[dict[str, Any]],
) -> None:
    if not run_id:
        return
    _stage("RUN_SUBMIT", f"run_id={run_id}")
    client = HarnessServiceClientSync(BITGN_URL)
    _call_bitgn(
        "SubmitRun",
        lambda: client.submit_run(SubmitRunRequest(run_id=run_id, force=True)),
        attempts=5,
    )
    run = _call_bitgn("GetRun", lambda: client.get_run(GetRunRequest(run_id=run_id)), attempts=5)
    score_available = bool(getattr(run, "score_available", False))
    result_by_task = {str(r.get("task_id")): r for r in results if r.get("task_id")}
    if not score_available:
        _stage("RUN_SCORE_UNAVAILABLE", f"run_id={run_id}")
        for result in result_by_task.values():
            if result.get("score") is None and bool(result.get("ok", False)):
                _write_score_result(
                    local_run_id=local_run_id,
                    result=result,
                    score=None,
                    detail=["run closed; score is sealed or unavailable for this benchmark policy"],
                    feedback_status="unavailable",
                )
        return

    _stage("RUN_SCORE_AVAILABLE", f"run_id={run_id} score={float(getattr(run, 'score', 0.0) or 0.0):0.3f}")
    for trial in getattr(run, "trials", []):
        task_id = str(getattr(trial, "task_id", ""))
        result = result_by_task.get(task_id)
        if not result:
            continue
        if int(getattr(trial, "state", 0) or 0) != TRIAL_STATE_DONE:
            continue
        if not bool(getattr(trial, "score_available", False)):
            _write_score_result(
                local_run_id=local_run_id,
                result=result,
                score=None,
                detail=["trial score is unavailable after run close"],
                feedback_status="unavailable",
            )
            continue
        detail = list(getattr(trial, "score_detail", []))
        score = float(getattr(trial, "score", 0.0) or 0.0)
        if not detail:
            try:
                full_trial = _call_bitgn(
                    "GetTrial",
                    lambda trial=trial: client.get_trial(GetTrialRequest(trial_id=str(getattr(trial, "trial_id", "")))),
                    attempts=3,
                )
                if bool(getattr(full_trial, "score_available", False)):
                    detail = list(getattr(full_trial, "score_detail", []))
                    score = float(getattr(full_trial, "score", score) or score)
            except ConnectError:
                pass
        _write_score_result(
            local_run_id=local_run_id,
            result=result,
            score=score,
            detail=detail,
            feedback_status="scored",
        )


def main() -> None:
    task_filter, parallelism, fail_fast = _parse_cli(sys.argv[1:])
    env = detect_env()
    harness_seed.validate_local_harness()

    leaderboard_trials: dict[str, dict[str, str]] = {}
    leaderboard_run_id: str | None = None
    prepared_run_id: str | None = None
    if NATIVE_LEADERBOARD and BITGN_API_KEY:
        try:
            prep_client = HarnessServiceClientSync(BITGN_URL)
            _cli(f"[LEADERBOARD] Preparing run against {BITGN_URL}")
            leaderboard_trials, leaderboard_run_id = _prepare_leaderboard_trials(
                client=prep_client,
                task_ids=task_filter,
            )
            prepared_run_id = leaderboard_run_id
        except ConnectError as exc:
            _cli(
                f"[LEADERBOARD] Failed to start leaderboard run ({exc.code}: {exc.message}). "
                "Falling back to playground mode."
            )
        except Exception as exc:
            _cli(
                "[LEADERBOARD] Failed to prepare leaderboard run "
                f"({exc}). Falling back to playground mode."
            )
    elif NATIVE_LEADERBOARD and not BITGN_API_KEY:
        _cli("[LEADERBOARD] Requested but BITGN_API_KEY is empty; using non-leaderboard mode.")

    if env in {"ecom", "pac1"} and not leaderboard_trials:
        prep_client = HarnessServiceClientSync(BITGN_URL)
        leaderboard_trials = _prepare_normal_trials(client=prep_client, task_ids=task_filter)
        prepared_run_id = next(
            (str(seed.get("run_id", "")) for seed in leaderboard_trials.values() if seed.get("run_id")),
            None,
        )

    local_run_id = _resolve_local_run_id()
    _stage(
        "LOCAL_RUN_START",
        f"local_run_id={local_run_id} tasks={task_filter} parallelism={parallelism} fail_fast={fail_fast}",
    )

    results: list[dict[str, Any]] = []
    fail_fast_stop = False
    stop_task_id = ""
    if parallelism <= 1 or len(task_filter) <= 1:
        for task_id in task_filter:
            result = _run_single_task(
                env=env,
                task_id=task_id,
                local_run_id=local_run_id,
                trial_seed=leaderboard_trials.get(task_id),
                leaderboard_run_id=leaderboard_run_id,
            )
            results.append(result)
            if fail_fast and not bool(result.get("ok", False)):
                fail_fast_stop = True
                stop_task_id = task_id
                break
    else:
        max_workers = min(parallelism, len(task_filter))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            pending_task_ids = list(task_filter)
            inflight: dict[Any, str] = {}

            def _submit_next() -> bool:
                if not pending_task_ids:
                    return False
                task_id = pending_task_ids.pop(0)
                fut = pool.submit(
                    _run_single_task,
                    env=env,
                    task_id=task_id,
                    local_run_id=local_run_id,
                    trial_seed=leaderboard_trials.get(task_id),
                    leaderboard_run_id=leaderboard_run_id,
                )
                inflight[fut] = task_id
                return True

            for _ in range(max_workers):
                if not _submit_next():
                    break

            while inflight:
                fut = next(as_completed(list(inflight.keys())))
                task_id = inflight.pop(fut)
                result = fut.result()
                results.append(result)

                if fail_fast and not bool(result.get("ok", False)):
                    fail_fast_stop = True
                    stop_task_id = task_id

                if not fail_fast_stop:
                    _submit_next()

    if prepared_run_id:
        try:
            _submit_and_backfill_run_scores(
                run_id=prepared_run_id,
                local_run_id=local_run_id,
                results=results,
            )
        except ConnectError as exc:
            _cli(f"[RUN] Submit/GetRun failed for run {prepared_run_id}: {exc.code} {exc.message}")
            if leaderboard_run_id:
                raise SystemExit(2) from exc

    if fail_fast and fail_fast_stop:
        _stage(
            "FAIL_FAST_STOP",
            f"local_run_id={local_run_id} stop_task={stop_task_id} completed={len(results)} planned={len(task_filter)}",
        )

    total = len(results)
    passed = sum(1 for r in results if bool(r.get("passed", False)))
    failed = sum(1 for r in results if not bool(r.get("ok", False)))
    _stage(
        "LOCAL_RUN_FINISH",
        f"local_run_id={local_run_id} total={total} passed={passed} failed={failed}",
    )
    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
