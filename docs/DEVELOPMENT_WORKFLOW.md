# Development workflow

`UNDERSTAND -> DISCOVER TOOLS/SKILLS -> LOCATE -> INSPECT CONTRACTS -> PLAN -> IMPLEMENT MINIMAL CHANGE -> STATIC INSPECTION -> UNIT TESTS -> SPECIALIZED VERIFIER -> GIT DIFF -> REPORT`

## Small change

1. Check `git status` and relevant instructions; do not read the whole repository.
2. Check the live tool/skill catalog. Read a specialized skill before implementing its domain.
3. Use Serena/PyCharm only if their project context points to this checkout; otherwise use `rg`, focused file reads and `apply_patch`.
4. Edit the smallest Python API or compatibility Node surface that satisfies the change; run a focused test, then broaden only when risk requires it.
5. Inspect `git diff`; do not include consumer repositories.

## Codex/API, config or lifecycle change

1. Read the `openai-docs` skill and inspect `codex --version`, the relevant local `--help`, and current official docs/schema. Follow the **OPENAI / CODEX SOURCE OF TRUTH** order: installed CLI/schema (when version-specific) -> OpenAI Developer Docs MCP -> installed official source/docs -> official OpenAI web docs if needed.
2. Separate CLI support, official SDK support and what Bridge actually implements. Never advertise CLI feature support as a Bridge method until implemented and tested.
3. Check caller/API references, cwd, child process, configuration and compatibility with the legacy JS contract.
4. Prefer the official Python Codex SDK when installed and operationally suitable. If unavailable, use only protocol methods/fields verified from the installed app-server schema; keep the raw transport narrow, fake-tested and fail-closed. For exec work use Python argument arrays with `shell=False`, prompt on stdin, timeout and bounded output.
5. Verify offline Python + JS tests, including fake app-server lifecycle/approval paths. Real smoke scripts remain outside the suite; streaming smoke is one read-only turn, approval smoke is manual only.

## Commands

```powershell
python -m compileall -q p4_codex_bridge tests_py
python -m unittest discover -s tests_py -v
npm test
python tests_real/smoke_streaming.py
```

The checkout has no `.venv`; document use of the installed Python rather than silently using another project interpreter. Never run Jira real or E2E real tests. Neither real Codex smoke is included in normal tests; do not run `tests_real/smoke_approval_reject.py` automatically.

## Context and tools

- Use the cheapest reliable source of truth: symbol search before full dumps, app-server schema before guessing RPC shapes, test-specific checks before global analysis.
- Never invent flags, fields, methods or capabilities. If official documentation differs from the installed version, record the difference, prefer behavior verified locally and leave the capability unimplemented until local verification.
- Treat `openaideveloperdocs` as a Codex development/verifier tool only; P4-Codex-Bridge runtime must not depend on it.
- Keep CLI and API discovery separate from session MCP tools. A subprocess does not inherit the Codex conversation's MCP handles.
- Respect allowed roots and do not administer any process outside the bridge registry.
- Review `git status` and `git diff` before commit; no push/remotes, and no commit without explicit request.
