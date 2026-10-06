"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { getProfile } = require("./profiles");
const { redact, makeError } = require("./errors");

const DEFAULT_TIMEOUT_SECONDS = 300;
const MAX_TIMEOUT_SECONDS = 300;
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;

function findCodexScript() {
  for (const entry of (process.env.PATH || "").split(path.delimiter)) {
    if (!entry) continue;
    const candidate = path.join(entry, "node_modules", "@openai", "codex", "bin", "codex.js");
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}

function resolveCodexCommand() {
  const override = process.env.CODEX_BIN;
  if (override) {
    if (path.extname(override).toLowerCase() === ".js") {
      return { command: process.execPath, script: path.resolve(override) };
    }
    return { command: override, script: null };
  }
  const script = findCodexScript();
  return script ? { command: process.execPath, script } : { command: "codex", script: null };
}

function safeEnvironment() {
  // Keep paths used by the official CLI to locate the ChatGPT login. Do not pass
  // API keys, arbitrary application secrets, or the complete parent environment.
  const names = ["PATH", "PATHEXT", "SystemRoot", "WINDIR", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "CODEX_HOME", "TEMP", "TMP", "HOME"];
  const env = {};
  for (const name of names) if (process.env[name] !== undefined) env[name] = process.env[name];
  return env;
}

function resolveCwd(inputCwd) {
  if (typeof inputCwd !== "string" || !inputCwd.trim() || !path.isAbsolute(inputCwd)) {
    throw makeError("CWD_INVALID", "cwd must be an absolute path to an existing directory");
  }
  let realCwd;
  try {
    realCwd = fs.realpathSync(inputCwd);
    if (!fs.statSync(realCwd).isDirectory()) throw new Error("not a directory");
  } catch {
    throw makeError("CWD_INVALID", "cwd must be an absolute path to an existing directory");
  }
  return realCwd;
}

function parseFinalMessage(stdout) {
  let content = "";
  for (const line of stdout.split(/\r?\n/)) {
    if (!line.trim()) continue;
    let event;
    try { event = JSON.parse(line); } catch { continue; }
    if (event.type === "item.completed" && event.item?.type === "agent_message") {
      content = typeof event.item.text === "string" ? event.item.text : "";
    }
  }
  return content;
}

function killProcessTree(child) {
  if (!child?.pid) return;
  if (process.platform === "win32") {
    // Stop the owned Codex child immediately so timeout completion does not
    // depend on taskkill.exe startup; taskkill still cleans any descendants.
    try { child.kill(); } catch {}
    const killer = spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
      shell: false,
      env: safeEnvironment(),
    });
    const fallback = setTimeout(() => child.kill(), 1000);
    fallback.unref();
    child.once("close", () => clearTimeout(fallback));
    killer.on("error", () => child.kill());
    return;
  }
  try { process.kill(-child.pid, "SIGKILL"); }
  catch { child.kill("SIGKILL"); }
}

function validateRequest({ prompt, cwd, timeout_seconds, model, profile }) {
  if (typeof prompt !== "string" || !prompt.trim()) throw makeError("PROMPT_REQUIRED", "prompt is required");
  if (typeof cwd !== "string" || !cwd.trim()) throw makeError("CWD_REQUIRED", "cwd is required");
  if (typeof timeout_seconds !== "number" || !Number.isFinite(timeout_seconds) || timeout_seconds <= 0 || timeout_seconds > MAX_TIMEOUT_SECONDS) {
    throw makeError("TIMEOUT_INVALID", `timeout_seconds must be greater than 0 and at most ${MAX_TIMEOUT_SECONDS}`);
  }
  if (model !== null && model !== undefined && (typeof model !== "string" || !/^[A-Za-z0-9._:/+-]{1,100}$/.test(model))) {
    throw makeError("MODEL_INVALID", "model must contain only letters, numbers, '.', '_', ':', '/', '+' or '-'");
  }
  const selectedProfile = getProfile(profile);
  if (!selectedProfile) throw makeError("PROFILE_INVALID", "profile is not implemented");
  return { cwd: resolveCwd(cwd), profile: selectedProfile };
}

function query(request) {
  const started = Date.now();
  let validated;
  try { validated = validateRequest(request); }
  catch (error) {
    const profileName = typeof request?.profile === "string" ? request.profile : null;
    const normalized = error.code ? error : makeError("REQUEST_INVALID", "request is invalid");
    return Promise.resolve({
      ok: false,
      exit_code: null,
      content: "",
      stderr: "",
      metadata: { profile: profileName, duration_ms: Date.now() - started, timed_out: false },
      error: { code: normalized.code, message: normalized.message },
    });
  }

  const { cwd, profile } = validated;
  const selectedModel = request.model ?? null;
  const resolved = resolveCodexCommand();
  const args = [];
  if (resolved.script && resolved.command === process.execPath) args.push(resolved.script);
  args.push("--ask-for-approval", "never", "exec", "--json", "--ephemeral", "--ignore-user-config", "--sandbox", profile.sandbox, "-C", cwd);
  if (selectedModel) args.push("--model", selectedModel);
  args.push("-");

  const metadata = { profile: profile.name, duration_ms: 0, timed_out: false };
  let stdout = "";
  let stderr = "";
  let outputBytes = 0;
  let timedOut = false;
  let outputExceeded = false;
  let settled = false;
  let child;
  let timer;

  return new Promise((resolve) => {
    const finish = (exitCode, failure) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      metadata.duration_ms = Date.now() - started;
      metadata.timed_out = timedOut;
      const code = Number.isInteger(exitCode) ? exitCode : null;
      const content = parseFinalMessage(stdout);
      let error = failure || null;
      if (timedOut) error = makeError("CODEX_TIMEOUT", "Codex CLI timed out");
      else if (outputExceeded) error = makeError("CODEX_OUTPUT_LIMIT", "Codex CLI output exceeded the configured limit");
      else if (!error && code !== 0) error = makeError("CODEX_EXIT_NONZERO", "Codex CLI exited with a non-zero status");
      else if (!error && !content.trim()) error = makeError("CODEX_EMPTY_RESPONSE", "Codex CLI returned no final message");

      const ok = error === null && code === 0 && content.trim().length > 0;
      const childText = redact(stderr.trim());
      resolve({
        ok,
        exit_code: code,
        content: redact(content),
        stderr: childText,
        metadata,
        error: error ? { code: error.code || "CODEX_SPAWN_ERROR", message: redact(error.message) } : null,
      });
    };

    try {
      child = spawn(resolved.command, args, {
        cwd,
        env: safeEnvironment(),
        shell: false,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
        detached: process.platform !== "win32",
      });
    } catch {
      finish(null, makeError("CODEX_SPAWN_ERROR", "Codex CLI could not be started"));
      return;
    }

    timer = setTimeout(() => {
      timedOut = true;
      killProcessTree(child);
    }, request.timeout_seconds * 1000);

    child.stdout.on("data", (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        outputExceeded = true;
        killProcessTree(child);
      } else stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        outputExceeded = true;
        killProcessTree(child);
      } else stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      const code = error.code === "ENOENT" ? "CODEX_NOT_FOUND" : "CODEX_SPAWN_ERROR";
      const message = code === "CODEX_NOT_FOUND" ? "Codex executable not found" : "Codex CLI could not be started";
      finish(null, makeError(code, message));
    });
    child.on("close", (code) => finish(code, null));
    child.stdin.on("error", () => {});
    child.stdin.end(`${profile.instruction}\n\n${request.prompt}`, "utf8");
  });
}

module.exports = {
  DEFAULT_TIMEOUT_SECONDS,
  MAX_TIMEOUT_SECONDS,
  MAX_OUTPUT_BYTES,
  query,
  resolveCodexCommand,
  resolveCwd,
  safeEnvironment,
  validateRequest,
};
