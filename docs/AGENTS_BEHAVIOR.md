# AGENTS.md behavior

## Documented behavior

OpenAI's [Codex customization documentation](https://learn.chatgpt.com/docs/customization/overview#agents-guidance) says guidance can come from the global Codex home and repository-specific `AGENTS.md` files, and files closer to the working directory take precedence. The [config reference](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml) says project `.codex/config.toml` files load only when the project is trusted. Trust for a `.codex` config layer is not itself proof that a particular instruction file was loaded in a particular run.

## This checkout and fixture

- The repository root has `AGENTS.md`.
- `tests_real/context_workspace/AGENTS.md` contains the harmless marker instruction `P4_AGENTS_OK`.
- The fixture has no project `.codex/config.toml` and no `.agents/skills` directory.
- `config/read` for that cwd reported `user` and `system` layers, with no project config layer. Returned source metadata includes user-level project trust keys, but this filtered query did not reveal trust values; none were changed.
- `codex exec --ignore-user-config` is the installed flag used by the Bridge's `isolated` policy. Its name establishes user-config suppression; it does not establish that project guidance, project config, skills, or all MCPs are suppressed.

## Effective state

| Policy / behavior | CHILD_VISIBLE | EFFECTIVE_FOR_RUN | Evidence |
|---|---|---|---|
| Host session root instructions | Confirmed to the current host | Not applicable to another process | Current agent received repository instructions. |
| Root/nested AGENTS discovery by Codex | Documented behavior | Not confirmed for this bridge child | No run-level loaded-file receipt is exposed. |
| `isolated` | `--ignore-user-config` is passed by the exec backend | `NOT_CONFIRMED` for AGENTS | No marker smoke was run. |
| `project` | Normal Codex config resolution is selected | `NOT_CONFIRMED` for AGENTS and project trust in this fixture | No marker smoke; app-server config query found no project config layer. |
| `explicit` | Native layers plus allowlisted `-c` settings | `NOT_CONFIRMED` for AGENTS | No marker smoke; config overrides do not establish instruction loading. |
| Parent/child precedence and nested override | Documented nearest-file precedence | `NOT_CONFIRMED` in a live Bridge run | No real model turn was run. |

The existing manual marker script is `tests_real/smoke_agents_context.py`. It is not part of automatic tests. Do not run it under an unfiltered MCP configuration: the diagnostic app-server in this environment advertised external write/deploy/destructive tools, while the Bridge cannot prove per-run filtering. Run a future marker check only after the safety gate can constrain the child's tools. Until then, classify loaded/effective AGENTS behavior as `NOT_CONFIRMED` rather than inferring from cwd or config source metadata.
