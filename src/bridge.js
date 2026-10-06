"use strict";

const { DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, query } = require("./codex_client");
const { failureResult } = require("./errors");
const { listProfiles } = require("./profiles");

const MAX_INPUT_BYTES = 2 * 1024 * 1024;

function emit(result, exitCode) {
  process.stdout.write(`${JSON.stringify(result)}\n`);
  process.exitCode = exitCode;
}

async function readStdin() {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > MAX_INPUT_BYTES) throw Object.assign(new Error("input exceeds the configured size limit"), { code: "INPUT_TOO_LARGE" });
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

function validateInput(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw Object.assign(new Error("input must be a JSON object"), { code: "INPUT_INVALID" });
  }
  if (typeof input.prompt !== "string" || !input.prompt.trim()) {
    throw Object.assign(new Error("prompt is required"), { code: "PROMPT_REQUIRED" });
  }
  if (typeof input.cwd !== "string" || !input.cwd.trim()) {
    throw Object.assign(new Error("cwd is required"), { code: "CWD_REQUIRED" });
  }
  if (typeof input.profile !== "string" || !listProfiles().includes(input.profile)) {
    throw Object.assign(new Error(`profile must be one of: ${listProfiles().join(", ")}`), { code: "PROFILE_INVALID" });
  }
  if (input.timeout_seconds !== undefined && (typeof input.timeout_seconds !== "number" || !Number.isFinite(input.timeout_seconds) || input.timeout_seconds <= 0 || input.timeout_seconds > MAX_TIMEOUT_SECONDS)) {
    throw Object.assign(new Error(`timeout_seconds must be greater than 0 and at most ${MAX_TIMEOUT_SECONDS}`), { code: "TIMEOUT_INVALID" });
  }
  if (input.model !== undefined && input.model !== null && (typeof input.model !== "string" || !/^[A-Za-z0-9._:/+-]{1,100}$/.test(input.model))) {
    throw Object.assign(new Error("model must contain only letters, numbers, '.', '_', ':', '/', '+' or '-'"), { code: "MODEL_INVALID" });
  }
  return {
    prompt: input.prompt,
    cwd: input.cwd,
    profile: input.profile,
    timeout_seconds: input.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS,
    model: input.model ?? null,
  };
}

async function main() {
  let input;
  try {
    const raw = await readStdin();
    try { input = JSON.parse(raw); }
    catch { throw Object.assign(new Error("invalid JSON input"), { code: "INPUT_INVALID_JSON" }); }
    input = validateInput(input);
  } catch (error) {
    const result = failureResult(error, input?.profile ?? null);
    emit(result, 1);
    return;
  }

  try {
    const result = await query(input);
    emit(result, result.ok ? 0 : 1);
  } catch {
    emit(failureResult(new Error("Codex bridge failed"), input.profile), 1);
  }
}

if (require.main === module) main();

module.exports = { main, validateInput, readStdin, MAX_INPUT_BYTES };
