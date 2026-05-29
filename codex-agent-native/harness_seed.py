from pathlib import Path
import os
import re
from typing import Any

from tool_gateway import ToolGateway


def local_rules_dir() -> Path:
    return Path(__file__).resolve().parent / "local-rules"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {name}: {raw}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}")
    return value


MAX_AGENTS_LINES = _int_env("LOCAL_RULES_MAX_AGENTS_LINES", 100)
MAX_AGENTS_LINE_LENGTH = 320
MAX_INCLUDE_FILES = 8
MAX_INCLUDE_FILE_LINES = 80
MAX_INCLUDE_TOTAL_LINES = 220
MAX_INCLUDE_LINE_LENGTH = 320
_INCLUDE_RE = re.compile(r"^\s*!include\s+([A-Za-z0-9_./-]+)\s*$")
ENV_RULE_FILES = {
    "pac1": "AGENTS.pac1.md",
    "ecom": "AGENTS.ecom.md",
}


def _normalize_include_path(raw: str) -> str:
    value = str(raw or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if not value:
        raise ValueError("Empty include path")
    if value.startswith("/"):
        raise ValueError(f"Include path must be relative: {value}")

    p = Path(value)
    if any(part in {"", ".", ".."} for part in p.parts):
        raise ValueError(f"Invalid include path segments: {value}")
    if not p.parts or p.parts[0] != "includes":
        raise ValueError(f"Include path must stay under includes/: {value}")
    if p.suffix.lower() != ".md":
        raise ValueError(f"Include path must target .md file: {value}")
    if any(part.startswith("._") for part in p.parts):
        raise ValueError(f"Include path cannot use macOS metadata files: {value}")
    return p.as_posix()


def _extract_include_paths(agents_text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in agents_text.splitlines():
        m = _INCLUDE_RE.match(line)
        if not m:
            continue
        rel = _normalize_include_path(m.group(1))
        if rel in seen:
            continue
        seen.add(rel)
        out.append(rel)
    return out


def _load_include_entries(
    base: Path, include_paths: list[str]
) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for rel in include_paths:
        path = base / rel
        if not path.exists() or not path.is_file():
            raise ValueError(f"Missing include file: {rel}")
        text = path.read_text(encoding="utf-8")
        entries.append((rel, text))
    return entries


def _normalize_env(value: str | None) -> str:
    env = str(value or "").strip().lower()
    if "ecom" in env:
        return "ecom"
    if "pac1" in env:
        return "pac1"
    return env


def render_local_rules_prompt(env: str | None = None) -> str:
    base = local_rules_dir()
    agents_path = base / "AGENTS.md"
    if not agents_path.exists():
        raise ValueError("Missing local-rules AGENTS.md")

    agents_text = agents_path.read_text(encoding="utf-8")
    include_paths = _extract_include_paths(agents_text)
    include_entries = _load_include_entries(base, include_paths)

    parts: list[str] = ["[AGENTS.md]", agents_text.strip()]
    for rel, content in include_entries:
        parts.append("")
        parts.append(f"[{rel}]")
        parts.append(content.strip())
    env_file = ENV_RULE_FILES.get(_normalize_env(env))
    if env_file:
        path = base / env_file
        if not path.exists() or not path.is_file():
            raise ValueError(f"Missing environment local-rules file: {env_file}")
        parts.append("")
        parts.append(f"[{env_file}]")
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n".join(parts).strip() + "\n"


def _read_local_harness_files() -> list[tuple[str, str]]:
    base = local_rules_dir()
    if not base.exists():
        return []
    out: list[tuple[str, str]] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("._"):
            continue
        rel = p.relative_to(base).as_posix()
        out.append((rel, p.read_text(encoding="utf-8")))
    return out


def copy_local_harness_into_workspace(*, target_dir: Path) -> list[str]:
    """Copy local rules into workspace artifacts for easy inspection."""
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for rel, content in _read_local_harness_files():
        out_path = target_dir / "local-rules" / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        copied.append(str(out_path))
    return copied


def validate_local_harness() -> None:
    agents = local_rules_dir() / "AGENTS.md"
    if not agents.exists():
        raise ValueError("Missing local-rules AGENTS.md")
    agents_text = agents.read_text(encoding="utf-8")
    line_count = len(agents_text.splitlines())
    if line_count > MAX_AGENTS_LINES:
        raise ValueError(
            f"local-rules/AGENTS.md exceeds {MAX_AGENTS_LINES} lines: {line_count}"
        )
    for idx, line in enumerate(agents_text.splitlines(), start=1):
        if len(line) > MAX_AGENTS_LINE_LENGTH:
            raise ValueError(
                "local-rules/AGENTS.md line exceeds "
                f"{MAX_AGENTS_LINE_LENGTH} chars at line {idx}"
            )

    include_paths = _extract_include_paths(agents_text)
    if len(include_paths) > MAX_INCLUDE_FILES:
        raise ValueError(
            f"local-rules includes exceed limit {MAX_INCLUDE_FILES}: {len(include_paths)}"
        )

    include_entries = _load_include_entries(local_rules_dir(), include_paths)
    for env_file in ENV_RULE_FILES.values():
        path = local_rules_dir() / env_file
        if not path.exists() or not path.is_file():
            raise ValueError(f"Missing environment local-rules file: {env_file}")
        env_lines = path.read_text(encoding="utf-8").splitlines()
        if len(env_lines) > 100:
            raise ValueError(
                f"environment local-rules file exceeds 100 lines: {env_file} ({len(env_lines)})"
            )
        for idx, line in enumerate(env_lines, start=1):
            if len(line) > MAX_INCLUDE_LINE_LENGTH:
                raise ValueError(
                    "environment local-rules line exceeds "
                    f"{MAX_INCLUDE_LINE_LENGTH} chars: {env_file}:{idx}"
                )
    total_lines = 0
    for rel, text in include_entries:
        include_lines = len(text.splitlines())
        if include_lines > MAX_INCLUDE_FILE_LINES:
            raise ValueError(
                f"local-rules include file exceeds {MAX_INCLUDE_FILE_LINES} lines: {rel} ({include_lines})"
            )
        for idx, line in enumerate(text.splitlines(), start=1):
            if len(line) > MAX_INCLUDE_LINE_LENGTH:
                raise ValueError(
                    "local-rules include line exceeds "
                    f"{MAX_INCLUDE_LINE_LENGTH} chars: {rel}:{idx}"
                )
        total_lines += include_lines
        if total_lines > MAX_INCLUDE_TOTAL_LINES:
            raise ValueError(
                f"local-rules include files exceed {MAX_INCLUDE_TOTAL_LINES} lines total: {total_lines}"
            )
        for line in text.splitlines():
            if _INCLUDE_RE.match(line):
                raise ValueError(f"Nested include directive is not allowed in {rel}")
