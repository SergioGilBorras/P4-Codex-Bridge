# Skills discovery and child behavior

## Sources and observed state

OpenAI's [Codex customization documentation](https://learn.chatgpt.com/docs/customization/overview#skills) documents global skills under `~/.agents/skills` and repository skills under `.agents/skills`. Codex uses progressive disclosure: skill metadata is available for discovery, the `SKILL.md` body is loaded when the skill is selected, and references/scripts are loaded only when needed.

The development host supplied 18 skills in this session. This is `SESSION_VISIBLE`; those skills are not automatically inherited by a CLI subprocess. In this checkout no `.agents/skills` directory was found. A diagnostic app-server `skills/list` call for the smoke fixture returned five enabled entries with `scope=system`: `imagegen`, `openai-docs`, `review-agent`, `skill-creator`, `skill-installer`. That confirms visibility only to that diagnostic child. It does not prove a `codex exec` run can select or load those skills.

| Capability | State | Evidence |
|---|---|---|
| Host skills | `SESSION_VISIBLE` | 18 skill instructions supplied to this agent. |
| CLI skill configuration | `NOT_CONFIRMED` | CLI help and `codex mcp list` do not enumerate skills. |
| Project skill files | `NOT_AVAILABLE` in this checkout | No `.agents/skills` directory. |
| Diagnostic app-server skill list | `CHILD_VISIBLE` | Five `system` entries returned by `skills/list`, all marked enabled. |
| Skill invocation by a bridge `exec` run | `NOT_CONFIRMED` | No skill invocation receipt or matching real run. |
| MCP-provided skill resources | `NOT_CONFIRMED` | No MCP resource count/list was obtained; don't equate MCP tools with skills. |

No real skill smoke was run. There is no trivial local skill whose invocation can be proved without a model turn and without filesystem/network effects. Use `list_effective_skills()` as a diagnostic listing only; do not describe its output as effective for a different run.
