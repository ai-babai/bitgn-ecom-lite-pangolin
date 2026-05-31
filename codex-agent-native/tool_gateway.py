# pyright: reportMissingImports=false

import json
import time
from datetime import datetime, timezone
from typing import Any

from bitgn.vm.ecom.ecom_connect import EcomRuntimeClientSync
from bitgn.vm.ecom.ecom_pb2 import (
    AnswerRequest as EcomAnswerRequest,
    DeleteRequest as EcomDeleteRequest,
    ExecRequest as EcomExecRequest,
    FindRequest as EcomFindRequest,
    ListRequest as EcomListRequest,
    NodeKind as EcomNodeKind,
    Outcome as EcomOutcome,
    ReadRequest as EcomReadRequest,
    SearchRequest as EcomSearchRequest,
    StatRequest as EcomStatRequest,
    TreeRequest as EcomTreeRequest,
    WriteRequest as EcomWriteRequest,
)
from bitgn.vm.mini_connect import MiniRuntimeClientSync
from bitgn.vm.mini_pb2 import (
    AnswerRequest,
    DeleteRequest,
    ListRequest,
    OutlineRequest,
    ReadRequest,
    SearchRequest,
    WriteRequest,
)
from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import (
    AnswerRequest as PcmAnswerRequest,
    ContextRequest,
    DeleteRequest as PcmDeleteRequest,
    FindRequest,
    ListRequest as PcmListRequest,
    MkDirRequest,
    MoveRequest,
    Outcome as PcmOutcome,
    ReadRequest as PcmReadRequest,
    SearchRequest as PcmSearchRequest,
    TreeRequest,
    WriteRequest as PcmWriteRequest,
)
from google.protobuf.json_format import MessageToDict
from workspace import TaskWorkspace

PCM_OUTCOMES = {
    "OUTCOME_OK": PcmOutcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": PcmOutcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": PcmOutcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": PcmOutcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": PcmOutcome.OUTCOME_ERR_INTERNAL,
}

ECOM_OUTCOMES = {
    "OUTCOME_OK": EcomOutcome.OUTCOME_OK,
    "OUTCOME_DENIED_SECURITY": EcomOutcome.OUTCOME_DENIED_SECURITY,
    "OUTCOME_NONE_CLARIFICATION": EcomOutcome.OUTCOME_NONE_CLARIFICATION,
    "OUTCOME_NONE_UNSUPPORTED": EcomOutcome.OUTCOME_NONE_UNSUPPORTED,
    "OUTCOME_ERR_INTERNAL": EcomOutcome.OUTCOME_ERR_INTERNAL,
}


def _normalize_outcome(raw: Any) -> str:
    value = str(raw or "OUTCOME_NONE_UNSUPPORTED").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "OK": "OUTCOME_OK",
        "DENIED_SECURITY": "OUTCOME_DENIED_SECURITY",
        "SECURITY": "OUTCOME_DENIED_SECURITY",
        "CLARIFICATION": "OUTCOME_NONE_CLARIFICATION",
        "NEEDS_CLARIFICATION": "OUTCOME_NONE_CLARIFICATION",
        "NONE_CLARIFICATION": "OUTCOME_NONE_CLARIFICATION",
        "UNSUPPORTED": "OUTCOME_NONE_UNSUPPORTED",
        "NONE_UNSUPPORTED": "OUTCOME_NONE_UNSUPPORTED",
        "ERROR": "OUTCOME_ERR_INTERNAL",
        "ERR_INTERNAL": "OUTCOME_ERR_INTERNAL",
    }
    return aliases.get(value, value if value.startswith("OUTCOME_") else "OUTCOME_NONE_UNSUPPORTED")


def _node_kind(raw: Any):
    value = str(raw or "all").strip().lower()
    if value in {"file", "files"}:
        return EcomNodeKind.NODE_KIND_FILE
    if value in {"dir", "dirs", "directory", "directories"}:
        return EcomNodeKind.NODE_KIND_DIR
    return EcomNodeKind.NODE_KIND_UNSPECIFIED


def _proto_has_field(message_cls: Any, name: str) -> bool:
    descriptor = getattr(message_cls, "DESCRIPTOR", None)
    fields = getattr(descriptor, "fields", [])
    return any(getattr(field, "name", "") == name for field in fields)


class ToolGateway:
    def __init__(self, *, env: str, harness_url: str, workspace: TaskWorkspace, task_id: str) -> None:
        self.env = env
        self.task_id = task_id
        self.workspace = workspace
        if env == "ecom":
            self.vm: Any = EcomRuntimeClientSync(harness_url)
        elif env == "pac1":
            self.vm = PcmRuntimeClientSync(harness_url)
        else:
            self.vm = MiniRuntimeClientSync(harness_url)

    @staticmethod
    def from_workspace_context(workspace: TaskWorkspace) -> "ToolGateway":
        ctx = json.loads(workspace.context_path.read_text(encoding="utf-8"))
        return ToolGateway(
            env=str(ctx.get("env", "sandbox")),
            harness_url=str(ctx.get("harness_url", "")),
            workspace=workspace,
            task_id=str(ctx.get("task_id", "")),
        )

    def _append_tool_call(self, *, step: int, tool: str, args: dict[str, Any], ts_start: float, result: dict[str, Any] | None, error: str | None) -> None:
        ts_end = time.time()
        self.workspace.append_jsonl(
            self.workspace.tool_calls_path,
            {
                "ts_start": datetime.fromtimestamp(ts_start, timezone.utc).isoformat(),
                "ts_end": datetime.fromtimestamp(ts_end, timezone.utc).isoformat(),
                "duration_ms": int((ts_end - ts_start) * 1000),
                "task_id": self.task_id,
                "step": step,
                "tool": tool,
                "args": args,
                "result": result,
                "error": error,
            },
        )

    def call(self, *, step: int, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        ts = time.time()
        try:
            out = self._dispatch(tool=tool, args=args)
            out_dict = out if isinstance(out, dict) else MessageToDict(out)
            self._append_tool_call(step=step, tool=tool, args=args, ts_start=ts, result=out_dict, error=None)
            return out_dict
        except Exception as exc:
            self._append_tool_call(step=step, tool=tool, args=args, ts_start=ts, result=None, error=str(exc))
            raise

    def _dispatch(self, *, tool: str, args: dict[str, Any]):
        if self.env == "ecom":
            return self._dispatch_ecom(tool=tool, args=args)
        if self.env == "pac1":
            return self._dispatch_pac1(tool=tool, args=args)
        return self._dispatch_sandbox(tool=tool, args=args)

    def _dispatch_sandbox(self, *, tool: str, args: dict[str, Any]):
        if tool == "tree":
            return self.vm.outline(OutlineRequest(path=str(args.get("path", "/"))))
        if tool == "search":
            return self.vm.search(SearchRequest(path=str(args.get("path", "/")), pattern=str(args.get("pattern", "")), count=max(1, min(int(args.get("count", 5) or 5), 10))))
        if tool == "list":
            return self.vm.list(ListRequest(path=str(args.get("path", "/"))))
        if tool == "read":
            return self.vm.read(ReadRequest(path=str(args.get("path", "AGENTS.MD"))))
        if tool == "write":
            self.vm.write(WriteRequest(path=str(args.get("path", "")), content=str(args.get("content", ""))))
            return {}
        if tool == "delete":
            self.vm.delete(DeleteRequest(path=str(args.get("path", ""))))
            return {}
        if tool == "report_completion":
            refs = [str(r) for r in args.get("grounding_refs", []) if str(r).strip()] if isinstance(args.get("grounding_refs"), list) else []
            self.vm.answer(AnswerRequest(answer=str(args.get("answer", args.get("message", ""))), refs=refs))
            return {}
        raise ValueError(f"Unknown sandbox tool: {tool}")

    def _dispatch_pac1(self, *, tool: str, args: dict[str, Any]):
        if tool == "context":
            return self.vm.context(ContextRequest())
        if tool == "tree":
            return self.vm.tree(TreeRequest(root=str(args.get("root") or args.get("path") or "/"), level=int(args.get("level") or args.get("max_depth") or 2)))
        if tool == "find":
            kind = str(args.get("kind", "all")).lower()
            kind_map = {"all": "TYPE_ALL", "files": "TYPE_FILES", "file": "TYPE_FILES", "dirs": "TYPE_DIRS", "dir": "TYPE_DIRS"}
            return self.vm.find(FindRequest(root=str(args.get("root") or args.get("path") or "/"), name=str(args.get("name") or args.get("pattern") or ""), type=kind_map.get(kind, "TYPE_ALL"), limit=int(args.get("limit", 10) or 10)))
        if tool == "search":
            return self.vm.search(PcmSearchRequest(root=str(args.get("root", "/")), pattern=str(args.get("pattern", "")), limit=int(args.get("limit", 10) or 10)))
        if tool == "list":
            return self.vm.list(PcmListRequest(name=str(args.get("path", "/"))))
        if tool == "read":
            return self.vm.read(PcmReadRequest(path=str(args.get("path", "AGENTS.MD")), number=bool(args.get("number", False)), start_line=int(args.get("start_line", 0) or 0), end_line=int(args.get("end_line", 0) or 0)))
        if tool == "write":
            self.vm.write(PcmWriteRequest(path=str(args.get("path", "")).lstrip("/"), content=str(args.get("content", "")), start_line=int(args.get("start_line", 0) or 0), end_line=int(args.get("end_line", 0) or 0)))
            return {}
        if tool == "delete":
            self.vm.delete(PcmDeleteRequest(path=str(args.get("path", "")).lstrip("/")))
            return {}
        if tool == "mkdir":
            self.vm.mk_dir(MkDirRequest(path=str(args.get("path", "")).lstrip("/")))
            return {}
        if tool == "move":
            self.vm.move(MoveRequest(from_name=str(args.get("from_name", "")).lstrip("/"), to_name=str(args.get("to_name", "")).lstrip("/")))
            return {}
        if tool == "report_completion":
            refs = [str(r).strip().lstrip("/") for r in args.get("grounding_refs", []) if str(r).strip()] if isinstance(args.get("grounding_refs"), list) else []
            outcome = _normalize_outcome(args.get("outcome"))
            self.vm.answer(PcmAnswerRequest(message=str(args.get("message", args.get("answer", ""))), outcome=PCM_OUTCOMES.get(outcome, PcmOutcome.OUTCOME_NONE_UNSUPPORTED), refs=refs))
            return {}
        raise ValueError(f"Unknown pac1 tool: {tool}")

    def _dispatch_ecom(self, *, tool: str, args: dict[str, Any]):
        if tool == "context":
            return {"env": "ecom", "available_tools": ["tree", "find", "search", "list", "read", "stat", "exec", "write", "delete", "report_completion"]}
        if tool == "tree":
            return self.vm.tree(EcomTreeRequest(root=self._ecom_path(args.get("root") or args.get("path") or "/"), level=int(args.get("level") or args.get("max_depth") or 2)))
        if tool == "find":
            return self.vm.find(EcomFindRequest(root=self._ecom_path(args.get("root") or args.get("path") or "/"), name=str(args.get("name") or args.get("pattern") or ""), kind=_node_kind(args.get("kind")), limit=int(args.get("limit", 10) or 10)))
        if tool == "search":
            return self.vm.search(EcomSearchRequest(root=self._ecom_path(args.get("root") or args.get("path") or "/"), pattern=str(args.get("pattern") or args.get("query") or ""), limit=int(args.get("limit", 10) or 10)))
        if tool == "list":
            return self.vm.list(EcomListRequest(path=self._ecom_path(args.get("path", "/"))))
        if tool == "read":
            return self.vm.read(EcomReadRequest(path=self._ecom_path(args.get("path", "/AGENTS.MD")), number=bool(args.get("number", False)), start_line=int(args.get("start_line", 0) or 0), end_line=int(args.get("end_line", 0) or 0)))
        if tool == "stat":
            return self.vm.stat(EcomStatRequest(path=self._ecom_path(args.get("path", "/"))))
        if tool == "exec":
            raw = args.get("args", [])
            exec_args = raw if isinstance(raw, list) else []
            return self.vm.exec(EcomExecRequest(path=self._ecom_path(args.get("path", "")), args=[str(x) for x in exec_args], stdin=str(args.get("stdin", ""))))
        if tool == "write":
            request_args: dict[str, Any] = {
                "path": self._ecom_path(args.get("path", "")),
                "content": str(args.get("content", "")),
            }
            if _proto_has_field(EcomWriteRequest, "start_line"):
                request_args["start_line"] = int(args.get("start_line", 0) or 0)
            if _proto_has_field(EcomWriteRequest, "end_line"):
                request_args["end_line"] = int(args.get("end_line", 0) or 0)
            if _proto_has_field(EcomWriteRequest, "if_match_sha256") and args.get("if_match_sha256"):
                request_args["if_match_sha256"] = str(args.get("if_match_sha256"))
            self.vm.write(EcomWriteRequest(**request_args))
            return {}
        if tool == "delete":
            self.vm.delete(EcomDeleteRequest(path=self._ecom_path(args.get("path", ""))))
            return {}
        if tool == "report_completion":
            refs = [self._ecom_path(r) for r in args.get("grounding_refs", []) if str(r).strip()] if isinstance(args.get("grounding_refs"), list) else []
            outcome = _normalize_outcome(args.get("outcome"))
            self.vm.answer(EcomAnswerRequest(message=str(args.get("message", args.get("answer", ""))), outcome=ECOM_OUTCOMES.get(outcome, EcomOutcome.OUTCOME_NONE_UNSUPPORTED), refs=refs))
            return {}
        raise ValueError(f"Unknown ecom tool: {tool}")

    @staticmethod
    def _ecom_path(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return "/"
        return text if text.startswith("/") else "/" + text.lstrip("/")


def summarize_tool_result(payload: dict[str, Any], limit: int = 1200) -> str:
    text = json.dumps(payload, ensure_ascii=True)
    return text if len(text) <= limit else text[:limit] + "..."


def print_tool_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))
