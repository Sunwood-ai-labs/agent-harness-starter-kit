// agent-harness-starter-kit: OpenCode plugin.
// Before every tool call, ask agent-guard (Python) whether the call is safe.
// "deny" and "ask" both stop the call: a plugin cannot open OpenCode's approval
// prompt, so the reason tells the agent to explain and let the person decide.
// If the check itself fails, the call is stopped too (fail closed).
import { spawnSync } from "node:child_process";

const PYTHON = {{PYTHON_JSON}};
const GUARD = {{GUARD_PATH_JSON}};

export const AgentGuard = async ({ directory }) => ({
  "tool.execute.before": async (input, output) => {
    const event = { tool: input.tool, args: output.args ?? {}, directory };
    const res = spawnSync(PYTHON, [GUARD, "--tool", "opencode"], {
      input: JSON.stringify(event),
      encoding: "utf8",
      timeout: 30000,
    });
    if (res.error || res.status !== 0) {
      throw new Error(`agent-guard: 安全チェックを実行できなかったため止めました (${res.error?.message ?? res.stderr})`);
    }
    let verdict;
    try {
      verdict = JSON.parse(res.stdout || "{}");
    } catch {
      throw new Error("agent-guard: 安全チェックの結果を読めなかったため止めました");
    }
    if (verdict.decision === "deny" || verdict.decision === "ask") {
      throw new Error(verdict.reason || "agent-guard: この操作は止めました");
    }
  },
});
