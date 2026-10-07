# Skills catalog

HOST_SESSION_SNAPSHOT of skills supplied to Codex on **6 October 2026**. Count: 18. A diagnostic app-server `skills/list` separately returned 5 enabled `system` entries; that does not establish `codex exec` visibility. Skill availability is session-specific; use the active catalog before relying on an entry.

> **If a specialized skill exists for the current task, read its instructions before improvising an implementation.**

| ID / name | Objective and when to load | Flow / constraints | Related tools |
|---|---|---|---|
| `imagegen` | Create/edit bitmap images, illustrations, textures or sprites. | Read its `SKILL.md`; provide a visual brief/reference. Not for SVG, code-native graphics, or existing logo systems. | `image_gen__imagegen`, `view_image` |
| `openai-docs` | Codex/OpenAI products, SDKs, APIs, models, setup, settings, skills, auth, troubleshooting. | Read before OpenAI/Codex implementation or product questions; browse official docs as directed. Not for generic tasks merely mentioning Codex. | `web__run`, local CLI/source inspection |
| `skill-creator` | Create or update a Codex skill. | Read its instructions and supporting resources before authoring skill files. | Filesystem tools |
| `skill-installer` | Find/install curated skills or install from a GitHub repository. | Read instructions before installation; installing can change Codex configuration. | Shell/network as prescribed by skill |
| `capture-tasks-from-meeting-notes` | Extract assigned actions and create Jira tasks from notes/Confluence. | Requires source notes and assignee context; creates external Jira records. | Atlassian MCP |
| `generate-status-report` | Create project/weekly status summaries and publish to Confluence. | Queries Jira then creates a Confluence report; publishing is an external write. | Atlassian MCP |
| `jira-sprint-dashboard` | Produce a sprint, standup, delivery, WIP or planning dashboard from Jira identifiers/queries. | Needs project/sprint/board/filter/JQL/issue input; use available visual format. | Atlassian MCP |
| `search-company-knowledge` | Search internal Jira/Confluence/company docs for processes, architecture and technical concepts. | Search/synthesize with citations; depends on connected company sources. | Atlassian MCP |
| `spec-to-backlog` | Convert Confluence specs into Epics and implementation tickets. | Reads spec and creates Jira backlog records. | Atlassian MCP |
| `triage-issue` | Search duplicates/history and triage bug/error reports. | Read-only search until explicitly asked to create/comment; writes Jira if requested. | Atlassian MCP |
| `plugin-management` | Discover/suggest plugins, inspect permissions/dependencies, manage plugin connections. | Read before plugin changes; connection/removal affects configuration. | Plugin Management MCP |
| `sites-building` | Build or modify websites hosted through Sites. | Only for an explicitly Sites-hosted website request. | Sites MCP |
| `sites-hosting` | Host/publish Sites-built pages and manage hosting. | Deployment follows a Sites-building task or explicit hosting request; external publish. | Sites MCP |
| `sites-mcp` | Build/update an MCP server hosted by Sites. | Only for Site-hosted MCPs. | Sites MCP |
| `sites-preview-troubleshooting` | Diagnose supervised Sites preview failures. | Only applies to managed-linux preview sessions, not portable preview. | Sites MCP |
| `create-pet` | Create/validate/preview/upload/activate an animated ChatGPT Work pet. | Requires established ChatGPT Pets context; follow asset lifecycle and preserve Library artifacts. | Pets MCP |
| `pets` | List/inspect/select/download/delete ChatGPT Work pets. | Only use for an explicit ChatGPT pet context; destructive delete requires user request. | Pets MCP |
| `update-pet` | Inspect/validate/repair/update an existing ChatGPT pet. | Pet metadata/sprite changes; use preview/validation workflow. | Pets MCP |

## Rules for this bridge

- OpenAI/Codex behavior, the official Python SDK, app-server, CLI flags, authentication, or configuration: read `openai-docs` first.
- Jira/Confluence work: use the task-specific Jira skill when it matches; do not trigger it for local bridge implementation.
- Image assets: use `imagegen`; normal software/docs work does not need it.
- This session's skill tools and runtime child process are separate. Bridge processes do not inherit these skill tool handles. Whether Codex CLI loads skills or `AGENTS.md` from a selected cwd is not confirmed for this bridge.
