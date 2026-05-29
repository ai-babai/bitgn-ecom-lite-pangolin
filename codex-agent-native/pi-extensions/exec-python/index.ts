import { spawn } from "node:child_process";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

function maxText(): number {
	const configured = Number(process.env.NATIVE_EXEC_TOOL_TEXT_LIMIT ?? process.env.NATIVE_EXEC_OUTPUT_LIMIT ?? 0);
	if (Number.isFinite(configured) && configured > 0) return Math.max(4_000, Math.floor(configured));
	const mode = (process.env.PANGOLIN_SCRATCHPAD_MODE ?? process.env.NATIVE_PANGOLIN_SCRATCHPAD_MODE ?? "").toLowerCase();
	return ["2", "v2", "compact", "scratchpad-v2"].includes(mode)
		? 40_000
		: 220_000;
}

function truncate(text: string): string {
	const MAX_TEXT = maxText();
	if (text.length <= MAX_TEXT) return text;
	return `${text.slice(0, MAX_TEXT)}\n... truncated ${text.length - MAX_TEXT} chars`;
}

function runPythonExec(code: string, timeoutSec: number, signal?: AbortSignal): Promise<string> {
	return new Promise((resolve, reject) => {
		const cwd = process.cwd();
		const child = spawn("uv", ["run", "python", "pi_exec_tool.py"], {
			cwd,
			env: process.env,
			stdio: ["pipe", "pipe", "pipe"],
		});

		let stdout = "";
		let stderr = "";
		let settled = false;
		const timer = setTimeout(() => {
			if (settled) return;
			child.kill("SIGKILL");
		}, Math.max(1, timeoutSec + 5) * 1000);

		const abort = () => {
			if (settled) return;
			child.kill("SIGTERM");
		};
		signal?.addEventListener("abort", abort, { once: true });

		child.stdout.on("data", (chunk) => {
			stdout += chunk.toString();
		});
		child.stderr.on("data", (chunk) => {
			stderr += chunk.toString();
		});
		child.on("error", (err) => {
			clearTimeout(timer);
			signal?.removeEventListener("abort", abort);
			settled = true;
			reject(err);
		});
		child.on("close", (codeNum, sig) => {
			clearTimeout(timer);
			signal?.removeEventListener("abort", abort);
			settled = true;
			const header = `EXEC_EXIT code=${codeNum ?? "null"} signal=${sig ?? "none"}`;
			const body = [header, truncate(stdout.trim()), stderr.trim() ? `STDERR:\n${truncate(stderr.trim())}` : ""]
				.filter(Boolean)
				.join("\n");
			resolve(body);
		});

		child.stdin.end(JSON.stringify({ code, timeout_sec: timeoutSec }));
	});
}

export default function (pi: ExtensionAPI) {
	pi.registerTool({
		name: "exec",
		label: "exec",
		description:
			"Run Python code inside the BitGN task harness. The code can call environment tools with call_tool(tool, **kwargs), for example call_tool('read', path='AGENTS.MD') and call_tool('report_completion', message='...', outcome='OUTCOME_OK', grounding_refs=['AGENTS.MD']). This is the only enabled agent tool.",
		parameters: Type.Object({
			code: Type.String({ description: "Python code to execute." }),
			timeout_sec: Type.Optional(
				Type.Number({ description: "Execution timeout in seconds, clamped to 1..900. Default: 120." }),
			),
		}),
		async execute(_toolCallId, params, signal) {
			const code = String(params.code ?? "");
			const timeoutSec = Math.max(1, Math.min(Number(params.timeout_sec ?? 120), 900));
			const text = await runPythonExec(code, timeoutSec, signal);
			return {
				content: [{ type: "text", text }],
				details: { cwd: process.cwd(), runner: join(process.cwd(), "pi_exec_tool.py") },
			};
		},
	});
}
