"use strict";

const { spawnSync } = require("node:child_process");
const { query, resolveCodexCommand, safeEnvironment } = require("../src/codex_client");
const { redact } = require("../src/errors");
const path = require("node:path");

function commandParts(args) {
  const resolved = resolveCodexCommand();
  const argv = resolved.script && resolved.command === process.execPath ? [resolved.script, ...args] : args;
  return { command: resolved.command, args: argv };
}

function runInspection(args) {
  const { command, args: argv } = commandParts(args);
  return spawnSync(command, argv, {
    encoding: "utf8",
    timeout: 15000,
    shell: false,
    windowsHide: true,
    env: safeEnvironment(),
  });
}

async function main() {
  const versionResult = runInspection(["--version"]);
  const version = versionResult.status === 0 ? versionResult.stdout.trim() : "unavailable";
  const authResult = versionResult.status === 0 ? runInspection(["login", "status"]) : null;
  const authText = `${authResult?.stdout || ""}\n${authResult?.stderr || ""}`;
  const authAvailable = authResult?.status === 0 && /Logged in using ChatGPT/i.test(authText);

  let result;
  if (authAvailable) {
    result = await query({
      prompt: "Reply exactly with:\nP4_CODEX_BRIDGE_OK",
      cwd: path.resolve(__dirname, "smoke_workspace"),
      profile: "analysis",
      timeout_seconds: 300,
      model: null,
    });
  } else {
    result = {
      ok: false,
      exit_code: authResult?.status ?? versionResult.status ?? null,
      content: "",
      stderr: "Codex CLI is not confirmed as logged in with ChatGPT",
      metadata: { profile: "analysis", duration_ms: 0, timed_out: false },
      error: { code: "CODEX_AUTH_UNAVAILABLE", message: "Codex CLI is not confirmed as logged in with ChatGPT" },
    };
  }

  const report = {
    codex_version: version,
    auth_chatgpt: authAvailable,
    exit_code: result.exit_code,
    content: result.content,
    latency_ms: result.metadata.duration_ms,
    stderr: redact(result.stderr),
    error: result.error,
  };
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  if (!result.ok || result.content !== "P4_CODEX_BRIDGE_OK") process.exitCode = 1;
}

main().catch(() => {
  process.stdout.write(`${JSON.stringify({
    codex_version: "unavailable",
    auth_chatgpt: false,
    exit_code: null,
    content: "",
    latency_ms: 0,
    stderr: "Codex smoke test failed",
    error: { code: "SMOKE_FAILED", message: "Codex smoke test failed" },
  }, null, 2)}\n`);
  process.exitCode = 1;
});
