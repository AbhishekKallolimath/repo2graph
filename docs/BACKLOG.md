# Backlog — deferred audit findings

Route back to the work the 2026-09 whole-repo audit found but did not fix in the
first batch. Full detail lives in `docs/BUILD_STATE.graphrag-2026-09.md`, the
archived state file from that run (`## Plan` MASTER ISSUE TABLE = all 53
findings; `## Improve` = the grouped backlog and loop retro). `BUILD_STATE.md` at
the repo root always holds the *current* build-app run, not that one.

**Epic:** [#31 — Epic: post-audit backlog](https://github.com/Srinivasan-78/repo2graph/issues/31)

| Issue | Scope | Covers | Priority |
|-------|-------|--------|----------|
| [#26](https://github.com/Srinivasan-78/repo2graph/issues/26) | fetch.py hardening round 2 | ISS-21, SH-2, SH-3, NC-4, NC-5 | P1 |
| [#21](https://github.com/Srinivasan-78/repo2graph/issues/21) | parse.py & cross-module string/correctness one-liners | ISS-03/04/05/09/11/12/41/42, NC-6 | P2 |
| [#23](https://github.com/Srinivasan-78/repo2graph/issues/23) | export.py correctness & GraphML hardening round 2 | ISS-28/29/30/31, SH-4 | P2 |
| [#24](https://github.com/Srinivasan-78/repo2graph/issues/24) | viz.py UX + safety | ISS-33/34/35/36 | P2 |
| [#25](https://github.com/Srinivasan-78/repo2graph/issues/25) | query.py retrieval budget + scoring hygiene | ISS-37/38/39 | P2 |
| [#27](https://github.com/Srinivasan-78/repo2graph/issues/27) | walker.py discovery hygiene | ISS-14/15, SH-5 | P2 |
| [#28](https://github.com/Srinivasan-78/repo2graph/issues/28) | Test coverage round 2 | ISS-52/53, SH-6, NC-1/2/3 | P2 |
| [#29](https://github.com/Srinivasan-78/repo2graph/issues/29) | CI, supply-chain & workflow/doc hygiene | ISS-43/46/47/48/49 | P2 |
| [#30](https://github.com/Srinivasan-78/repo2graph/issues/30) | authormark: refresh stale Fingerprint lines on batch-1 files (not merge-blocking — CI checks presence only) | AC-16, SH-7 | P2 |
| [#22](https://github.com/Srinivasan-78/repo2graph/issues/22) | chunks.py line-span accuracy, id scheme & tidy | ISS-23/24/25/26 | P3 |

All child issues carry the `backlog` label. To work one, run a `/build-app`
refactor loop scoped to a single issue (or a single module group).

## Deferred by the MCP / vectors run (2026-09)

Ranked by the IMPROVE phase of that run. Size is rough effort, not risk.

| # | Item | Size | Why this rank |
|---|------|------|---------------|
| 1 | **CI job that installs the `[mcp]` extra and does one stdio round trip** *(Shipped)* | S | **Shipped in PR #54:** CI installs `[dev,mcp]` and runs `test_ac34_stdio_server_roundtrip`, exercising `serve()` end-to-end over stdio JSON-RPC. (Previously `serve()` had no automated test coverage). |
| 2 | **Say so when fusion silently switches itself off** (detail below) | S | Same failure class the whole run was built to avoid: a feature reporting success while doing nothing. |
| 3 | **Port the MCP server to the 2.x SDK API** (detail below) | M | Deliberate deferral, not debt — but the `<2` pin ages, and 1.x will stop getting fixes. |
| 4 | **Graph-level incremental rebuild** (detail below) | L | Cut at PLAN with reasoning; a run of its own. Nothing depends on it — `index.state.json` already ships the substrate. |
| 5 | **A real `sentence-transformers` smoke test, opt-in and network-gated** | S | Every embedder in the suite is `StubEmbedder`. `default_embedder()` is tested only for its *failure* message, so nothing proves the real wrapper's `model_id`/`dim` agree with what `vectors.meta.json` records — the exact pair `fuse_ok` compares. |
| 6 | **`docs/BACKLOG.md` has no `@authormark` header** | XS | Pre-existing at baseline `ff0e3ca`; not introduced by this run, and deliberately not fixed here (the stamper is not vendored). Fold into the next watermark sweep, with issue #30. |
| 7 | **No coverage measurement anywhere in the repo** | S | ~130 tests were added this run on judgement alone. Nobody can currently answer "which branch of `embed.py` never runs". |

**Graph-level incremental rebuild — `build(..., previous: Graph)`.** Deliberately cut, not
forgotten. Edge invalidation is the obvious hard part, but the real blocker is one level up:
`build()` resolves `CALLS` through a *global* name index and sets
`confidence = 1/len(candidates)`. Adding or deleting a symbol named `run` in file A therefore
changes the confidence — and the count — of `CALLS` edges emitted from files B and C that did not
change at all, and `mark_entrypoints()`/`reach` is a whole-graph BFS on top of that. A merge that
reparses only the changed paths and splices their nodes/edges produces an index that is *wrong in a
way nothing detects*: stale confidences and stale entrypoint flags flow straight into
`chunks.jsonl` headers and into `pack_context`'s `min_confidence` gate — the same failure mode the
vector model-mismatch guard exists to prevent. Doing it correctly means caching `ParsedFile` per
file and re-running the *whole* resolution phase on every build (cheap: tree-sitter parsing is the
expensive part), which is a different design from `build(..., previous=)` and a run of its own.

What shipped instead is the safe, self-contained half: per-file sha256 in `agent/index.state.json`
(the substrate any incremental build needs) and vector reuse keyed on chunk *text* hash, which is
correct by construction because a chunk's vector depends on its own text and nothing else.

**Say so when fusion silently switches itself off.** `Index` drops vectors whose chunk ids are no
longer in `chunks.jsonl`, so a `chunks.jsonl` rebuilt without re-running `embed` degrades instead of
mis-aligning. The degrade is all-or-nothing, not partial: `query._vectors_for` builds
`[vectors[i] for i in candidates]` inside a `try/except (KeyError, IndexError, TypeError)` and
returns `(None, [])` on the *first* candidate that has no vector, so if any one of the top
`RRF_CANDIDATES` BM25 candidates is unvectorised, `score_rrf` abandons the dense ranking entirely
and returns plain BM25. There is therefore no "fuses on the part it has" coverage risk to guard
against — the ranking is never half-dense.

What is missing is the *report*. `Index.fuse_ok` only compares model id and width, so after a
rebuild without a re-`embed` it can pass, `--vectors` can report success, and fusion can then turn
itself off inside `_vectors_for` with nothing printed either way. Wanted: carry the coverage
fraction out of `_vectors_for` and have `--vectors` say `fused 0/8 candidates — re-run
repo2graph embed` rather than quietly answering a lexical question. Small.

**Port the MCP server to the 2.x SDK API.** The `mcp` extra is bounded to `mcp>=1.0,<2` *on
purpose*, not as an accident of pinning. `repo2graph/mcp.py::serve()` is written against the 1.x
decorator API — `@server.list_tools()` and `@server.call_tool()` on `mcp.server.Server`, plus
`mcp.server.stdio.stdio_server` and `mcp.types.{Tool,TextContent}` — and mcp 2.x removed both
decorator methods from `Server`. Because `import mcp` still succeeds on 2.x, the failure landed as
a raw `AttributeError: 'Server' object has no attribute 'list_tools'` from inside `serve()` on
every fresh `pip install "repo2graph[mcp]"` while the extra was unbounded. `_require_sdk()` now
checks `REQUIRED_SERVER_API` against the `Server` class and exits with an instruction naming the
installed version and `pip install "mcp>=1.0,<2"`, so the unsupported case is a sentence rather
than a traceback — but it is still unsupported.

To pick this up: re-express `serve()` against the 2.x registration API, leaving `dispatch()` — the
only place any logic lives — untouched, so the three handlers and every bounds test still apply
unchanged. Then widen the extra (or branch the wiring on `_sdk_version()`), relax
`REQUIRED_SERVER_API` to whatever 2.x actually needs, and update the README's pin note. Nothing
outside `serve()`, `_require_sdk()`, the `pyproject.toml` extra and that one README paragraph is
coupled to the SDK version, and no test imports the SDK, so the blast radius is small.

## Shipped in batch 1

Branch `audit/batch-1-encoding-hardening` — 15 High/Med in-scope fixes
(ISS-01/02/06/07/13/16/17/18/19/22/27/44/45/50/51) + 5 one-liners
(ISS-08/10/20/32/40) + SH-1. Suite: 73 passed, 2 skipped.
