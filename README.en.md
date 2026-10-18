# Modou · 墨斗 (Ink Line)

> "Wood straightened by the line" — the ink line is where carpentry begins. The line is
> snapped before construction, the mark stays on the timber: the craftsman builds along
> it, the foreman inspects against it, and the mark itself is the record. Database
> change and tuning lack exactly this line. **Draw the line. Keep the proof.**

English | [简体中文](README.md)

Modou is the local layer for database engineering: **change verification · SQL
optimization · rule review · drift insight**. It does not change your release process,
deploy a platform, or take over your database — it draws the line with proof at the
handoff between development and operations, so every conclusion (is the schema
consistent? does the index actually help?) comes from database replay evidence,
not from eyeballing or guessing.

**v1.0 is stable**: all four lanes shipped, conclusions are tiered (deterministic
evidence + AI opinions listed separately), zero platform, data never leaves your
machine (AI analysis is BYOK; with no key configured it makes zero network requests).

## Why Modou

Two real pain points:

1. **Missed statements at handoff**: ops executes SQL on behalf of developers. A single
   change may contain dozens of small statements; merging them for convenience invites
   silent misses — and nothing ever checks.
2. **Advice without evidence**: SQL tuning advice (indexes, rewrites) comes from
   experience and blog posts; nobody verifies it against real data volume.

Modou answers both with one methodology: **derive the expected state by replaying on a
shadow database, and let the database produce the evidence**. Once that infrastructure
exists, the review and insight lanes reuse the same kernel at marginal cost.

## Four lanes

| Lane | Commands | What it solves |
|---|---|---|
| Change verification | `pack` / `verify` | Bundle change sets to prevent misses → before/after snapshots → three-way diff (missed / wrong / historical drift) |
| SQL optimization | `optimize` | Collect plans → build indexes on a shadow database → every suggestion tagged "measured improvement X%" or explicitly "unverified" |
| Rule review | `lint` | 26 static SQL anti-pattern rules (SOAR subset; no database, no network), for pre-commit / mapper batch scans |
| Drift insight | `patrol` | Drift diff, unused-index tiering, slow-log fingerprint aggregation, DDL lock risk with gh-ost/pt-osc advice |

Two end-to-end cases with real command output: [missed-statement verification](
examples/changeset-demo/) · [index optimization evidence](examples/optimize-demo/).

## Install

```bash
# From PyPI (recommended, requires Python 3.12+)
uv tool install modou

# Or try without installing
uvx modou --help

# Or from source
git clone <repo> && cd modou && uv sync && uv run modou --help
```

The MCP surface (for Claude Code / Cursor and other agent hosts) and AI delegation
workflows: [docs/demo-agent.md](docs/demo-agent.md). BYOK triple (`MOUDO_AI_BASE_URL` /
`MOUDO_AI_API_KEY` / `MOUDO_AI_MODEL`) unset means zero network requests.

## Quick start

```bash
# Before ops executes: read-only snapshot
modou snapshot capture --dsn mysql://user:pass@host:3306 -d mydb -o before.json

# Developer side: bundle the change set with destructive-DDL warnings
modou pack examples/changeset-demo -o packed.sql

# …… ops executes packed.sql ……

# After execution: read-only snapshot
modou snapshot capture --dsn mysql://user:pass@host:3306 -d mydb -o after.json

# Verify: three-way diff; exit code 0=identical / 1=differs / 2=environment or input error
modou verify examples/changeset-demo --baseline before.json --after after.json \
    --default-database mydb --report-json report.json

# Read the report in a local browser (localhost only, no login, no deployment)
modou ui --report report.json
```

Full walkthrough: [docs/quickstart.md](docs/quickstart.md).

## Three forms, one kernel

- **CLI is the body**: CI gates, audit trails (deterministic exit codes), handoff flows
  in the ops terminal;
- **MCP is the native surface**: every MCP tool maps 1:1 to a CLI subcommand
  (guarded by parity tests), callable from any agent host; evidence-primitive tools in
  [docs/demo-agent.md](docs/demo-agent.md);
- **Local web is the thin report layer**: `modou ui` serves reports on loopback — no
  login, no deployment (the lazygit model).

Explicitly rejected: a hosted web platform (that is Bytebase/DBdoctor's fight), a
pure MCP tool (no CI or audit story), cloud SaaS (schemas and real SQL are highly
sensitive; the trust dividend is local).

## Design principles (non-negotiable)

1. **Deterministic code is the referee; AI is the analyst**: whether the schema matches
   and whether advice works is decided by code and database evidence; AI handles
   semantic judgment rules cannot express, its opinions are listed separately and never
   touch exit codes, and unverified suggestions may not claim effectiveness.
2. **Replay, don't parse**: the expected state comes from replaying the change set on a
   real MySQL; DDL parsing only warns, never concludes.
3. **Multi-instance, multi-database by default**: multiple databases/schemas are the
   norm, not the exception.
4. **Data never leaves the machine**: the shadow database is a same-version local
   container (podman/docker); snapshots and samples never leave the host.

## Docs

| Doc | Contents |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | Quick start: minimal flow of all four lanes |
| [docs/changeset-spec.md](docs/changeset-spec.md) | Change set spec: layout, manifest, DELIMITER, multi-database conventions |
| [docs/rules.md](docs/rules.md) | Review rule catalog (26 rules, configurable via `modou.toml`) |
| [docs/demo-agent.md](docs/demo-agent.md) | MCP integration and AI delegation workflows |
| [docs/formats.md](docs/formats.md) | Data format contracts (snapshot / report / exit-code semantics) |
| [docs/architecture.md](docs/architecture.md) | Architecture north star: kernel trio, module map, risks |
| [docs/goals.md](docs/goals.md) | Goals and milestone acceptance criteria |
| [docs/adr/](docs/adr/) | Architecture decision records (ADR-0001~0009) |

## License

[Apache-2.0](LICENSE)
