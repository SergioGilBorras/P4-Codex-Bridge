"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { resolveCodexCommand, safeEnvironment } = require("../src/codex_client");
const { redact } = require("../src/errors");

const root = path.resolve(__dirname, "..");
const bridgePath = path.join(root, "bin", "p4-codex-bridge.js");
const tempRoot = fs.mkdtempSync(path.join(root, ".test-tmp-"));
let checks = 0;

function check(name, fn) {
  fn();
  checks += 1;
  process.stdout.write(`ok ${checks} - ${name}\n`);
}

function invoke(input, env = {}, timeout = null) {
  return spawnSync(process.execPath, [bridgePath], {
    input,
    encoding: "utf8",
    ...(timeout === null ? {} : { timeout }),
    env: { ...process.env, ...env },
    windowsHide: true,
  });
}

function body(overrides = {}) {
  return {
    prompt: "Say hello",
    cwd: root,
    profile: "analysis",
    timeout_seconds: 5,
    model: null,
    ...overrides,
  };
}

function resultOf(result) {
  assert.equal(result.stderr, "", "bridge process stderr must not contain application output");
  const lines = result.stdout.trim().split(/\r?\n/);
  assert.equal(lines.length, 1, "stdout must contain only one JSON response");
  return JSON.parse(lines[0]);
}

function fakeCli(source) {
  const filename = path.join(tempRoot, `fake-${Date.now()}-${Math.random().toString(16).slice(2)}.js`);
  fs.writeFileSync(filename, source, "utf8");
  return filename;
}

function event(text) {
  return `${JSON.stringify({ type: "item.completed", item: { type: "agent_message", text } })}\n`;
}

function invokeFake(input, script, env = {}, timeout = null) {
  return invoke(JSON.stringify(input), { ...env, CODEX_BIN: script }, timeout);
}

function validEventCli(text, afterEnd = "") {
  return `let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{process.stdout.write(${JSON.stringify(event(text))});${afterEnd}});`;
}

try {
  check("invalid JSON is structured", () => {
    const result = invoke("{");
    assert.equal(result.status, 1);
    assert.equal(resultOf(result).error.code, "INPUT_INVALID_JSON");
  });

  check("non-object input is rejected", () => {
    const result = invoke(JSON.stringify(["prompt"]));
    assert.equal(result.status, 1);
    assert.equal(resultOf(result).error.code, "INPUT_INVALID");
  });

  check("missing prompt and cwd are rejected", () => {
    const noPrompt = invoke(JSON.stringify({ cwd: root, profile: "analysis" }));
    assert.equal(noPrompt.status, 1);
    assert.equal(resultOf(noPrompt).error.code, "PROMPT_REQUIRED");
    const noCwd = invoke(JSON.stringify({ prompt: "hello", profile: "analysis" }));
    assert.equal(resultOf(noCwd).error.code, "CWD_REQUIRED");
  });

  check("invalid profile is rejected before invoking Codex", () => {
    const result = invoke(JSON.stringify(body({ profile: "implementation" })), { CODEX_BIN: path.join(tempRoot, "not-run.js") });
    assert.equal(result.status, 1);
    assert.equal(resultOf(result).error.code, "PROFILE_INVALID");
  });

  check("invalid cwd is rejected", () => {
    const missing = invokeFake(body({ cwd: path.join(root, "does-not-exist") }), fakeCli(validEventCli("no")));
    assert.equal(missing.status, 1);
    assert.equal(resultOf(missing).error.code, "CWD_INVALID");
    const file = path.join(tempRoot, "not-a-directory");
    fs.writeFileSync(file, "x");
    const notDir = invokeFake(body({ cwd: file }), fakeCli(validEventCli("no")));
    assert.equal(resultOf(notDir).error.code, "CWD_INVALID");
  });

  check("valid request and Unicode response preserve UTF-8", () => {
    const answer = "Sí: π, 東京, 🚀";
    const result = invokeFake(body({ prompt: "¿Qué?" }), fakeCli(validEventCli(answer)));
    assert.equal(result.status, 0, result.stdout + result.stderr);
    const response = resultOf(result);
    assert.equal(response.ok, true);
    assert.equal(response.content, answer);
    assert.equal(response.error, null);
  });

  check("analysis profile uses read-only CLI flags and text-only prompt", () => {
    const answer = "analysis ok";
    const script = fakeCli(`const args=process.argv.slice(2);let input='';process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{process.stdout.write(${JSON.stringify(event(answer))});process.stderr.write(JSON.stringify({args,input}));});`);
    const response = resultOf(invokeFake(body({ cwd: root, model: "gpt-5-codex" }), script));
    assert.equal(response.metadata.profile, "analysis");
    assert.equal(response.ok, true);
    const diagnostic = JSON.parse(response.stderr);
    assert.ok(diagnostic.args.includes("read-only"));
    assert.ok(diagnostic.args.includes("never"));
    assert.ok(diagnostic.args.includes("--ignore-user-config"));
    assert.ok(diagnostic.args.includes("--ephemeral"));
    assert.equal(diagnostic.args.at(-1), "-");
    assert.match(diagnostic.input, /Do not use Jira or other external services/);
    assert.match(diagnostic.input, /Do not intentionally edit, create, or delete files/);
    assert.doesNotMatch(diagnostic.args.join(" "), /--search|OPENAI_API_KEY/);
  });

  check("model is passed as one argument", () => {
    const script = fakeCli(`process.stdout.write(${JSON.stringify(event("ok"))});process.stderr.write(JSON.stringify(process.argv.slice(2)));`);
    const response = resultOf(invokeFake(body({ model: "gpt-5-codex" }), script));
    const args = JSON.parse(response.stderr);
    assert.equal(args[args.indexOf("--model") + 1], "gpt-5-codex");
  });

  check("timeout kills the child and reports a normalized error", () => {
    const script = fakeCli("setInterval(()=>{},1000);");
    // No synchronous harness deadline here: its deadline used to kill the
    // bridge while Windows was still reaping the child tree. The fake has no
    // descendants and the bridge's own timeout is the behavior under test.
    const result = invokeFake(body({ timeout_seconds: 0.15 }), script, {}, null);
    // The bridge resolves this request only after its owned child emits `close`.
    // Assert the behavior and that the outer harness itself did not time out;
    // elapsed wall-clock time is affected by parallel Python/Node startup load.
    assert.equal(result.error?.code, undefined, "the test harness must finish normally");
    assert.equal(result.status, 1);
    const response = resultOf(result);
    assert.equal(response.error.code, "CODEX_TIMEOUT");
    assert.equal(response.metadata.timed_out, true);
    assert.equal(response.exit_code, null);
  });

  check("missing executable returns a structured failure", () => {
    const result = invoke(JSON.stringify(body()), { CODEX_BIN: path.join(tempRoot, "missing-codex.exe") });
    assert.equal(result.status, 1);
    assert.equal(resultOf(result).error.code, "CODEX_NOT_FOUND");
  });

  check("non-zero exit preserves exit code and sanitized stderr", () => {
    const script = fakeCli("process.stderr.write('diagnostic');process.exit(7);");
    const result = invokeFake(body(), script);
    assert.equal(result.status, 1);
    const response = resultOf(result);
    assert.equal(response.exit_code, 7);
    assert.equal(response.stderr, "diagnostic");
    assert.equal(response.error.code, "CODEX_EXIT_NONZERO");
  });

  check("empty final response fails even with exit code zero", () => {
    const script = fakeCli("process.stdout.write(JSON.stringify({type:'turn.completed'})+'\\n');");
    const result = invokeFake(body(), script);
    assert.equal(result.status, 1);
    assert.equal(resultOf(result).error.code, "CODEX_EMPTY_RESPONSE");
  });

  check("environment is allowlisted and OPENAI_API_KEY is not forwarded", () => {
    const script = fakeCli(`process.stdout.write(${JSON.stringify(event("ok"))});process.stderr.write(process.env.OPENAI_API_KEY||'not-forwarded');`);
    const result = invokeFake(body(), script, { OPENAI_API_KEY: "sk-test-12345678901234567890" });
    assert.equal(resultOf(result).stderr, "not-forwarded");
    assert.equal(safeEnvironment().OPENAI_API_KEY, undefined);
  });

  check("secret patterns are redacted from returned content and diagnostics", () => {
    const secret = "sk-test-12345678901234567890";
    const script = fakeCli(`process.stdout.write(${JSON.stringify(event(secret))});process.stderr.write('Authorization: Bearer abcdefghijklmnop');`);
    const response = resultOf(invokeFake(body(), script));
    assert.equal(response.content, "[REDACTED]");
    assert.equal(response.stderr, "Authorization: Bearer [REDACTED]");
    assert.equal(redact("OPENAI_API_KEY=hidden-value"), "OPENAI_API_KEY=[REDACTED]");
  });

  check("prompt is sent over stdin and cannot become a shell command", () => {
    const marker = path.join(tempRoot, "injected.txt");
    const prompt = `hello & echo injected > ${marker}`;
    const script = fakeCli(validEventCli(prompt));
    const response = resultOf(invokeFake(body({ prompt }), script));
    assert.equal(response.content, prompt);
    assert.equal(fs.existsSync(marker), false);
  });

  check("bridge invocation creates no result temp files", () => {
    const script = fakeCli(validEventCli("ok"));
    const before = fs.readdirSync(tempRoot).sort();
    const response = resultOf(invokeFake(body(), script));
    assert.equal(response.ok, true);
    assert.equal(fs.readdirSync(tempRoot).sort().join("\n"), before.join("\n"));
  });

  check("metadata contains profile and elapsed time only", () => {
    const response = resultOf(invokeFake(body(), fakeCli(validEventCli("ok"))));
    assert.equal(response.metadata.profile, "analysis");
    assert.equal(typeof response.metadata.duration_ms, "number");
    assert.equal(response.metadata.outputPath, undefined);
    assert.equal(response.metadata.cwd, undefined);
  });

  check("CODEX_BIN JavaScript override resolves through Node", () => {
    const script = fakeCli("");
    const previous = process.env.CODEX_BIN;
    process.env.CODEX_BIN = script;
    try {
      const resolved = resolveCodexCommand();
      assert.equal(resolved.command, process.execPath);
      assert.equal(resolved.script, script);
    } finally {
      if (previous === undefined) delete process.env.CODEX_BIN;
      else process.env.CODEX_BIN = previous;
    }
  });

  process.stdout.write(`1..${checks}\n`);
} finally {
  if (!tempRoot.startsWith(`${root}${path.sep}`)) throw new Error("refusing to clean a test directory outside the repository");
  fs.rmSync(tempRoot, { recursive: true, force: true });
}
