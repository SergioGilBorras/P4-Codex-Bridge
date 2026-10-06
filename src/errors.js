"use strict";

function makeError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function redact(value) {
  return String(value ?? "")
    .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi, "Bearer [REDACTED]")
    .replace(/\b(OPENAI_API_KEY|CODEX_API_KEY|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN|PASSWORD|SECRET)\s*[:=]\s*[^\s,;]+/gi, "$1=[REDACTED]");
}

function failureResult(error, profile = null) {
  const normalized = error?.code ? error : makeError("BRIDGE_ERROR", "Codex bridge failed");
  return {
    ok: false,
    exit_code: null,
    content: "",
    stderr: "",
    metadata: { profile, duration_ms: 0, timed_out: false },
    error: { code: normalized.code, message: redact(normalized.message) },
  };
}

module.exports = { makeError, redact, failureResult };
