"use strict";

const PROFILES = Object.freeze({
  analysis: Object.freeze({
    name: "analysis",
    sandbox: "read-only",
    instruction: [
      "P4-Codex-Bridge profile: analysis.",
      "Provide text analysis only. Do not intentionally edit, create, or delete files.",
      "Do not use Jira or other external services. Do not invoke external MCP actions.",
      "Treat the following as the user's request:",
    ].join("\n"),
  }),
});

function getProfile(name) {
  return typeof name === "string" ? PROFILES[name] || null : null;
}

function listProfiles() {
  return Object.keys(PROFILES);
}

module.exports = { PROFILES, getProfile, listProfiles };
