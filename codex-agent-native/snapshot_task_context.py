# pyright: reportMissingImports=false

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import EndTrialRequest, StartPlaygroundRequest, StatusRequest
from bitgn.vm.mini_connect import MiniRuntimeClientSync
from bitgn.vm.mini_pb2 import ListRequest, OutlineRequest, ReadRequest
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import ContextRequest, ListRequest as PcmListRequest, ReadRequest as PcmReadRequest, TreeRequest
from google.protobuf.json_format import MessageToDict


BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def detect_env(value: str) -> str:
    if value:
        return value
    bench = os.getenv("BENCHMARK_ID", "")
    if "pac1" in bench:
        return "pac1"
    return "sandbox"


def benchmark_for_env(env: str) -> str:
    if env == "pac1":
        return os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
    return os.getenv("BENCHMARK_ID") or "bitgn/sandbox"


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def normalize_rel_path(path: str) -> str:
    rel = path.strip().replace("\\", "/").lstrip("/")
    rel = rel.replace("..", "")
    return rel


def extract_paths_from_instruction(instruction: str) -> list[str]:
    pattern = re.compile(r"([A-Za-z0-9._/-]+\.(?:md|MD|json|txt))")
    out: list[str] = []
    for m in pattern.findall(instruction):
        cleaned = m.strip("'\".,;:()[]{}")
        if "/" in cleaned:
            out.append(cleaned)
    return list(dict.fromkeys(out))


def write_summary(
    *,
    out_dir: Path,
    env: str,
    benchmark_id: str,
    task_id: str,
    instruction: str,
    discovered_paths: list[str],
    read_ok_paths: list[str],
) -> None:
    if env == "pac1":
        completion_shape = "report_completion(message, outcome, grounding_refs)"
    else:
        completion_shape = "report_completion(answer, grounding_refs)"

    lines = [
        f"# Task context snapshot: {task_id}",
        "",
        f"- env: {env}",
        f"- benchmark_id: {benchmark_id}",
        f"- created_at_utc: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Task instruction",
        "```text",
        instruction.strip(),
        "```",
        "",
        "## Как агент понимает цель задачи",
        "- Из `instruction` (что нужно сделать).",
        "- Из `files/AGENTS.MD` и process/docs файлов (правила и workflow).",
        "- Из структуры файлов (`raw/tree.json` или `raw/outline.json`).",
        "",
        "## Как должен выглядеть completion",
        f"- Контракт: `{completion_shape}`",
        "- `grounding_refs` должны указывать на реально использованные файлы.",
        "",
        "## Что было автоматически обнаружено",
        "- Пути из instruction:",
    ]
    if discovered_paths:
        lines.extend([f"  - `{p}`" for p in discovered_paths])
    else:
        lines.append("  - (нет явных путей)")
    lines.extend([
        "",
        "- Успешно прочитанные файлы:",
    ])
    if read_ok_paths:
        lines.extend([f"  - `{p}`" for p in read_ok_paths])
    else:
        lines.append("  - (нет)")

    save_text(out_dir / "SUMMARY.md", "\n".join(lines).strip() + "\n")


def snapshot_sandbox(vm: MiniRuntimeClientSync, out_dir: Path, instruction: str) -> tuple[list[str], list[str]]:
    raw_dir = out_dir / "raw"
    files_dir = out_dir / "files"

    listed = MessageToDict(vm.list(ListRequest(path="/")))
    save_json(raw_dir / "list_root.json", listed)

    outline = MessageToDict(vm.outline(OutlineRequest(path="/")))
    save_json(raw_dir / "outline.json", outline)

    candidates = ["AGENTS.MD"]
    files = listed.get("files", []) if isinstance(listed, dict) else []
    if isinstance(files, list):
        for f in files:
            if isinstance(f, str):
                candidates.append(f)
    candidates.extend(extract_paths_from_instruction(instruction))
    candidates = list(dict.fromkeys(candidates))

    read_ok: list[str] = []
    read_errors: dict[str, str] = {}
    for p in candidates:
        rel = normalize_rel_path(p)
        if not rel:
            continue
        try:
            out = MessageToDict(vm.read(ReadRequest(path=rel)))
            content = str(out.get("content", ""))
            if content:
                save_text(files_dir / rel, content)
                read_ok.append(rel)
        except Exception as exc:
            read_errors[rel] = str(exc)

    save_json(raw_dir / "read_errors.json", {"errors": read_errors})
    return candidates, read_ok


def _walk_tree_markdown(node: dict[str, Any], prefix: str = "") -> list[str]:
    name = str(node.get("name", "")).strip()
    is_dir = bool(node.get("isDir", False))
    path = f"{prefix}/{name}" if prefix else name
    out: list[str] = []
    if is_dir:
        children = node.get("children", [])
        if isinstance(children, list):
            for ch in children:
                if isinstance(ch, dict):
                    out.extend(_walk_tree_markdown(ch, path))
        return out
    if name.lower().endswith((".md", ".txt", ".json")):
        out.append(path.lstrip("/"))
    return out


def snapshot_pac1(vm: PcmRuntimeClientSync, out_dir: Path, instruction: str) -> tuple[list[str], list[str]]:
    raw_dir = out_dir / "raw"
    files_dir = out_dir / "files"

    ctx = MessageToDict(vm.context(ContextRequest()))
    save_json(raw_dir / "context.json", ctx)

    tree = MessageToDict(vm.tree(TreeRequest(root="/", level=3)))
    save_json(raw_dir / "tree.json", tree)

    listed = MessageToDict(vm.list(PcmListRequest(name="/")))
    save_json(raw_dir / "list_root.json", listed)

    core_candidates = [
        "AGENTS.MD",
        "README.md",
        "99_process/process_tasks.md",
        "99_process/document_capture.md",
        "99_process/document_cleanup.md",
        "02_distill/AGENTS.md",
        "02_distill/cards/_card-template.md",
        "02_distill/threads/_thread-template.md",
    ]
    instruction_candidates = extract_paths_from_instruction(instruction)

    tree_candidates: list[str] = []
    root = tree.get("root") if isinstance(tree, dict) else None
    if isinstance(root, dict):
        tree_candidates = _walk_tree_markdown(root)

    candidates = list(dict.fromkeys(core_candidates + instruction_candidates + tree_candidates))

    read_ok: list[str] = []
    read_errors: dict[str, str] = {}
    for p in candidates:
        rel = normalize_rel_path(p)
        if not rel:
            continue
        try:
            out = MessageToDict(vm.read(PcmReadRequest(path=rel, number=False, start_line=0, end_line=0)))
            content = str(out.get("content", ""))
            if content:
                save_text(files_dir / rel, content)
                read_ok.append(rel)
        except Exception as exc:
            read_errors[rel] = str(exc)

    save_json(raw_dir / "read_errors.json", {"errors": read_errors})
    return candidates, read_ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot task context and files without running Codex")
    parser.add_argument("task_id", help="Task id (e.g. t03)")
    parser.add_argument("--env", choices=["sandbox", "pac1"], default="", help="Environment override")
    parser.add_argument("--out", default="", help="Optional output directory")
    args = parser.parse_args()

    env = detect_env(args.env)
    benchmark_id = benchmark_for_env(env)

    base_out = Path(args.out) if args.out else (Path(__file__).resolve().parent / "task-context-snapshots")
    out_dir = base_out / f"{now_stamp()}-{env}-{args.task_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    client = HarnessServiceClientSync(BITGN_URL)
    print("Connecting to BitGN", client.status(StatusRequest()))

    trial = client.start_playground(StartPlaygroundRequest(benchmark_id=benchmark_id, task_id=args.task_id))
    instruction = str(trial.instruction)
    save_text(out_dir / "instruction.txt", instruction.strip() + "\n")
    save_json(
        out_dir / "meta.json",
        {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "env": env,
            "benchmark_id": benchmark_id,
            "task_id": args.task_id,
            "trial_id": trial.trial_id,
            "harness_url": trial.harness_url,
            "output_dir": str(out_dir),
        },
    )

    discovered: list[str] = []
    read_ok: list[str] = []
    try:
        if env == "pac1":
            vm = PcmRuntimeClientSync(trial.harness_url)
            discovered, read_ok = snapshot_pac1(vm, out_dir, instruction)
        else:
            vm = MiniRuntimeClientSync(trial.harness_url)
            discovered, read_ok = snapshot_sandbox(vm, out_dir, instruction)
    finally:
        try:
            client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
        except Exception:
            pass

    write_summary(
        out_dir=out_dir,
        env=env,
        benchmark_id=benchmark_id,
        task_id=args.task_id,
        instruction=instruction,
        discovered_paths=discovered,
        read_ok_paths=read_ok,
    )

    print(f"Snapshot saved: {out_dir}")


if __name__ == "__main__":
    main()
