# @authormark v1 -- do not remove (authorship watermark)⁠​‌‌‌​‌​​​‌​‌​​‌​​‌‌‌​‌​‌​‌‌‌​‌​​​‌​‌​​‌‌​‌​‌‌​​‌​‌​‌​​‌​​‌‌‌‌​‌​​‌‌​‌‌​‌​‌‌​‌‌​‌​​‌‌​‌​​​​‌‌​​‌‌​‌​​‌​‌​​​‌‌‌​​‌​​‌‌​‌​​​‌‌‌​‌‌‌​​‌‌​​‌​​‌​‌​‌​​​‌‌​​​‌​​‌​‌​‌​‌​‌​​​‌‌​​‌‌‌​‌​‌⁠
# Copyright (c) 2026 Srinivasan Vijayaraghavan <srinivasan.shyam2000@gmail.com>
# Author: https://github.com/Srinivasan-78
# SPDX-License-Identifier: MIT
# Fingerprint: AMK1.tRutSYRzmm43J94w2TbUFu
"""Change 2 -- the stdio MCP server. AC-26 .. AC-33.

The `mcp` SDK is an optional extra and is deliberately never imported here:
`repo2graph.mcp`'s three handlers are plain functions taking an `Index`, so
AC-26..AC-31 need no SDK at all, and AC-33 blocks the import on purpose to
assert the error message a user without the extra actually sees.
"""
import sys
import tomllib
from pathlib import Path

import pytest

from conftest import MINI_QUERY, REPO_ROOT, SECRET_QUERY, SYM_AUDIT, SYM_ROUTE
from repo2graph.query import Index, _is_secret_path

PYPROJECT = REPO_ROOT / "pyproject.toml"


def mcp_module():
    from repo2graph import mcp as mcp_mod
    return mcp_mod


def tokens(text: str) -> int:
    from repo2graph.query import count_tokens
    return count_tokens(text)


# ==========================================================================
# AC-26 -- repo_map
# ==========================================================================

def test_ac26_repo_map_is_exactly_map_prepend(mini_index):
    """AC-26: no reformatting, no truncation, no query argument."""
    mcp = mcp_module()
    idx = Index(mini_index)
    assert mcp.tool_repo_map(idx) == idx.map_prepend()
    assert idx.map_prepend().strip(), "the fixture produced an empty map"


# ==========================================================================
# AC-27 / AC-28 -- repo_search and its hard budget ceiling
# ==========================================================================

def test_ac27_repo_search_returns_cited_markdown_within_the_default_budget(
        big_index):
    """AC-27: at least one `### [cite: path:start-end]` header, and the result
    measures no more than MCP_BUDGET_TOKENS.

    `big_index` packs to well over the default budget when unbounded, so the
    default really is enforced here rather than merely not exceeded.
    """
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.tool_repo_search(idx, MINI_QUERY)

    assert isinstance(out, str)
    assert "### [cite: " in out, out[:400]
    assert "-" in out.split("### [cite: ", 1)[1].split("]", 1)[0]
    assert tokens(out) <= mcp.MCP_BUDGET_TOKENS, tokens(out)

    unbounded = idx.pack_context(MINI_QUERY, budget_chars=0)
    assert tokens(unbounded["markdown"]) > mcp.MCP_BUDGET_TOKENS, (
        "the fixture no longer exceeds the default budget")


@pytest.mark.parametrize("budget", [10**9, 10**6, 100000])
def test_ac28_an_absurd_budget_is_clamped_to_the_ceiling(big_index, budget):
    """AC-28: the ceiling is enforced, not advisory."""
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.tool_repo_search(idx, MINI_QUERY, k=20, budget_tokens=budget)
    assert tokens(out) <= mcp.MCP_MAX_BUDGET_TOKENS, tokens(out)

    unbounded = idx.pack_context(MINI_QUERY, k=20, budget_chars=0)
    assert tokens(unbounded["markdown"]) > mcp.MCP_MAX_BUDGET_TOKENS, (
        "the fixture no longer exceeds the ceiling")


@pytest.mark.parametrize("budget", [0, -5, -10**9])
def test_ac28_a_zero_or_negative_budget_is_clamped_to_the_floor(big_index,
                                                                budget):
    """AC-28: no crash, no traceback, and still a bounded string."""
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.tool_repo_search(idx, MINI_QUERY, k=20, budget_tokens=budget)
    assert isinstance(out, str)
    assert tokens(out) <= mcp.MCP_MAX_BUDGET_TOKENS


def test_ac28_ceiling_is_above_the_default(big_index):
    """AC-28 (guard): the two constants are ordered the way the plan says."""
    mcp = mcp_module()
    assert 0 < mcp.MCP_BUDGET_TOKENS <= mcp.MCP_MAX_BUDGET_TOKENS


def test_ac28_truncation_happens_on_a_line_boundary(big_index):
    """AC-28: a clamped result is still parseable markdown -- no half line."""
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.tool_repo_search(idx, MINI_QUERY, k=20, budget_tokens=10**9)
    full = idx.pack_context(MINI_QUERY, k=20, budget_chars=0)["markdown"]
    full_lines = set(full.split("\n"))    # never splitlines(): see AGENTS.md
    body = out.split("\n")
    for line in body[:-1]:
        assert line in full_lines, line[:120]


# ==========================================================================
# AC-29 -- secrets never leave through an agent tool
# ==========================================================================

def test_ac29_repo_search_never_returns_a_secret_chunk(mini_index):
    """AC-29: the fixture's `.env` chunk is BM25 rank 1 for SECRET_QUERY and
    still must not appear; the same query with exclude_secrets=False does
    return it, which is what makes this a real test."""
    mcp = mcp_module()
    idx = Index(mini_index)

    leaky = idx.pack_context(SECRET_QUERY, budget_chars=0, exclude_secrets=False)
    leaky_paths = {c.get("path") or "" for c in leaky["chunks"]}
    assert any(_is_secret_path(p) for p in leaky_paths), leaky_paths
    assert ".env" in leaky["markdown"]

    top = idx.chunks[idx.score(SECRET_QUERY)[0][1]]
    assert _is_secret_path(top.get("path") or ""), top.get("path")

    out = mcp.tool_repo_search(idx, SECRET_QUERY)
    for header in out.split("### [cite: ")[1:]:
        path = header.split(":", 1)[0]
        assert not _is_secret_path(path), path
    assert "ACME_DEPLOYMENT_LEDGER_TOKEN" not in out
    assert "abc123deadbeef" not in out


def test_ac29_repo_map_and_neighbours_also_exclude_secrets(mini_index):
    """AC-29 (b): the other two tools must not become the leak instead."""
    mcp = mcp_module()
    idx = Index(mini_index)
    for text in (mcp.tool_repo_map(idx),
                 mcp.tool_repo_neighbours(idx, "file:.env")):
        assert "abc123deadbeef" not in text
        assert "zzz999notreal" not in text


# ==========================================================================
# AC-30 -- repo_neighbours
# ==========================================================================

def test_ac30_neighbours_names_a_reachable_node_its_edge_and_direction(
        mini_index):
    """AC-30: route_request -> audit_event over CALLS out is in the fixture
    graph, so it must be named, with its edge type and its direction."""
    mcp = mcp_module()
    idx = Index(mini_index)

    expected = {(dst, etype, direction)
                for dst, etype, direction, _src in idx.expand([SYM_ROUTE], hops=1)}
    assert (SYM_AUDIT, "CALLS", "out") in expected, expected

    out = mcp.tool_repo_neighbours(idx, SYM_ROUTE)
    assert isinstance(out, str) and out.strip()
    assert "audit_event" in out, out
    assert "CALLS" in out, out
    assert "out" in out, out


def test_ac30_an_unknown_node_id_returns_a_short_message(mini_index):
    """AC-30 (b): not found, not a traceback, and not a wall of text."""
    mcp = mcp_module()
    idx = Index(mini_index)
    out = mcp.tool_repo_neighbours(idx, "sym:nowhere.py::nothing")
    assert isinstance(out, str)
    assert "not found" in out.lower(), out
    assert len(out) <= 400, len(out)


def test_ac30_neighbours_respects_its_limit(mini_index):
    """AC-30 (c): an agent-facing tool must be bounded here too."""
    mcp = mcp_module()
    idx = Index(mini_index)
    short = mcp.tool_repo_neighbours(idx, SYM_ROUTE, limit=1)
    longer = mcp.tool_repo_neighbours(idx, SYM_ROUTE, limit=50)
    assert len(short) <= len(longer)


# ==========================================================================
# AC-31 -- tool descriptions are context an agent pays for every session
# ==========================================================================

def test_ac31_tool_descriptions_are_three_and_stay_under_600_chars():
    """AC-31: exactly the three tool names, ~150 tokens combined."""
    mcp = mcp_module()
    assert set(mcp.TOOL_DESCRIPTIONS) == {"repo_map", "repo_search",
                                          "repo_neighbours"}
    for name, text in mcp.TOOL_DESCRIPTIONS.items():
        assert isinstance(text, str) and text.strip(), name
    total = sum(len(d) for d in mcp.TOOL_DESCRIPTIONS.values())
    assert total <= 600, total


# ==========================================================================
# AC-32 / AC-33 -- packaging and the console entry point
# ==========================================================================

def load_pyproject() -> dict:
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


def requirement_names(specs):
    out = set()
    for spec in specs:
        name = spec.split(";")[0].split("[")[0]
        for sep in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            name = name.split(sep)[0]
        out.add(name.strip())
    return out


def test_ac32_mcp_is_an_optional_extra_with_a_console_script():
    """AC-32: `mcp` extra + `repo2graph-mcp` entry point."""
    data = load_pyproject()
    extras = data["project"]["optional-dependencies"]
    assert "mcp" in extras, sorted(extras)
    assert requirement_names(extras["mcp"]) == {"mcp"}, extras["mcp"]
    scripts = data["project"]["scripts"]
    assert scripts.get("repo2graph-mcp") == "repo2graph.mcp:main", scripts
    assert scripts.get("repo2graph") == "repo2graph.cli:main", scripts


def test_ac32_runtime_dependencies_are_still_only_tree_sitter():
    """AC-32: a bare `pip install repo2graph` brings in nothing new."""
    data = load_pyproject()
    assert requirement_names(data["project"]["dependencies"]) == {
        "tree-sitter", "tree-sitter-language-pack"}


def test_ac33_entry_point_without_the_sdk_explains_the_extra(mini_index,
                                                             monkeypatch):
    """AC-33: a user without the extra gets an actionable message and a
    non-zero exit, never an ImportError traceback."""
    mcp = mcp_module()
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit) as exc:
        mcp.main(["--out", str(mini_index)])
    message = str(exc.value)
    assert 'pip install "repo2graph[mcp]"' in message, message
    assert exc.value.code not in (0, None)


def test_ac33_serve_without_the_sdk_raises_the_same_systemexit(mini_index,
                                                               monkeypatch):
    """AC-33 (b): the guard lives at the import site, not only in main()."""
    mcp = mcp_module()
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit) as exc:
        mcp.serve(Path(mini_index))
    assert 'pip install "repo2graph[mcp]"' in str(exc.value)


def test_ac33_open_index_caches_one_index_per_directory(mini_index):
    """AC-33 (c): the server must not re-read the whole index per tool call."""
    mcp = mcp_module()
    first = mcp.open_index(mini_index)
    second = mcp.open_index(mini_index)
    assert first is second
    assert isinstance(first, Index)


# ==========================================================================
# Regressions -- REVIEW iteration 2
# ==========================================================================
#
# R-5: `k` and `hops` were coerced but never clamped. `Index.expand` runs
# `for _ in range(hops)` with no empty-frontier exit, so `hops=10**9` blocked
# serve()'s single event loop for ~a minute. Output size was already bounded;
# time was not. These assert the value that reaches the engine, not the value
# that comes back, because a clamp that only trims the answer is not a clamp.

@pytest.mark.parametrize("hops", [10**9, 10**12, 5, "99999", None, -3])
def test_r5_neighbours_hops_never_exceeds_the_ceiling(mini_index, hops):
    """R-5 (a): whatever a model writes into `hops`, expand() sees 0..MAX."""
    mcp = mcp_module()
    idx = Index(mini_index)
    seen = []
    real = idx.expand
    idx.expand = lambda seeds, **kw: (seen.append(kw.get("hops")),
                                      real(seeds, **kw))[1]

    out = mcp.tool_repo_neighbours(idx, SYM_ROUTE, hops=hops)
    assert isinstance(out, str) and out.strip()
    assert seen and all(0 <= h <= mcp.MCP_MAX_HOPS for h in seen), seen


@pytest.mark.parametrize("k,hops", [(10**9, 10**9), ("nonsense", -1), (0, 7)])
def test_r5_search_k_and_hops_never_exceed_their_ceilings(mini_index, k, hops):
    """R-5 (b): the same on the search path, where both arguments cost time."""
    mcp = mcp_module()
    idx = Index(mini_index)
    seen = {}
    real = idx.pack_context

    def spy(query, **kw):
        seen.update(kw)
        return real(query, **kw)

    idx.pack_context = spy
    out = mcp.tool_repo_search(idx, MINI_QUERY, k=k, hops=hops)
    assert isinstance(out, str)
    assert 1 <= seen["k"] <= mcp.MCP_MAX_K, seen
    assert 0 <= seen["hops"] <= mcp.MCP_MAX_HOPS, seen


def test_r5_dispatch_clamps_too(mini_index):
    """R-5 (c): the clamp lives in the handlers, so the JSON route inherits it."""
    mcp = mcp_module()
    idx = Index(mini_index)
    seen = {}
    real = idx.pack_context

    def spy(query, **kw):
        seen.update(kw)
        return real(query, **kw)

    idx.pack_context = spy
    mcp.dispatch(idx, "repo_search",
                 {"query": MINI_QUERY, "k": 10**6, "hops": 10**6})
    assert seen["k"] == mcp.MCP_MAX_K
    assert seen["hops"] == mcp.MCP_MAX_HOPS


def test_r5_sane_arguments_are_left_alone(mini_index):
    """R-5 (d): the ceilings must not quietly rewrite ordinary calls."""
    mcp = mcp_module()
    idx = Index(mini_index)
    seen = {}
    real = idx.pack_context

    def spy(query, **kw):
        seen.update(kw)
        return real(query, **kw)

    idx.pack_context = spy
    mcp.tool_repo_search(idx, MINI_QUERY, k=3, hops=2)
    assert (seen["k"], seen["hops"]) == (3, 2)
    assert mcp.MCP_MAX_K > 8 and mcp.MCP_MAX_HOPS > 1, "a ceiling below the default"


# ==========================================================================
# Regression -- REVIEW iteration 3
# ==========================================================================
#
# R-7: `limit` on repo_neighbours had a floor and no ceiling, so the size of
# that answer was caller-controlled -- 35 414 characters at hops=4 limit=10**9
# against a 1 532-character default on an 895-node index. It is the one tool
# whose output no token budget measures, so the row count is the bound. The
# fixture graph is far smaller than any ceiling, so these drive expand() with a
# synthetic frontier: a clamp asserted against four real neighbours would pass
# with no clamp at all.

def _flood(idx, n=5000):
    """Make expand() yield more neighbours than any ceiling allows."""
    idx.expand = lambda seeds, **kw: [
        (f"sym:pkg/flood.py::n{i}", "CALLS", "out", seeds[0]) for i in range(n)]


def _rows(text):
    return [ln for ln in text.split("\n") if ln.startswith("- ")]


@pytest.mark.parametrize("limit", [10**9, 10**12, "99999", 51])
def test_r7_neighbours_limit_never_exceeds_the_ceiling(mini_index, limit):
    """R-7 (a): whatever a model writes into `limit`, the reply is bounded."""
    mcp = mcp_module()
    idx = Index(mini_index)
    _flood(idx)
    out = mcp.tool_repo_neighbours(idx, SYM_ROUTE, limit=limit)
    assert len(_rows(out)) <= mcp.MCP_MAX_NEIGHBOURS, len(_rows(out))


def test_r7_the_default_limit_still_applies(mini_index):
    """R-7 (b): the ceiling did not become the default."""
    mcp = mcp_module()
    idx = Index(mini_index)
    _flood(idx)
    out = mcp.tool_repo_neighbours(idx, SYM_ROUTE)
    assert len(_rows(out)) <= mcp.MCP_NEIGHBOUR_LIMIT, len(_rows(out))
    assert mcp.MCP_MAX_NEIGHBOURS > mcp.MCP_NEIGHBOUR_LIMIT, "ceiling below default"


def test_r7_dispatch_inherits_the_limit_clamp(mini_index):
    """R-7 (c): the clamp lives in the handler, so the JSON route gets it too."""
    mcp = mcp_module()
    idx = Index(mini_index)
    _flood(idx)
    out = mcp.dispatch(idx, "repo_neighbours",
                       {"node_id": SYM_ROUTE, "limit": 10**6})
    assert len(_rows(out)) <= mcp.MCP_MAX_NEIGHBOURS, len(_rows(out))


def test_r7_a_sane_limit_is_left_alone(mini_index):
    """R-7 (d): the ceiling must not quietly rewrite an ordinary request."""
    mcp = mcp_module()
    idx = Index(mini_index)
    _flood(idx)
    assert len(_rows(mcp.tool_repo_neighbours(idx, SYM_ROUTE, limit=7))) == 7
    assert len(_rows(mcp.tool_repo_neighbours(idx, SYM_ROUTE, limit=1))) == 1


# ==========================================================================
# Regressions -- VERIFY iteration 4
# ==========================================================================
#
# R-8: the extra declared `mcp>=1.0`, which resolves to mcp 2.x today. mcp 2.x
# removed the `Server.list_tools` / `Server.call_tool` decorators that serve()
# is written against, so `repo2graph-mcp` died with
# `AttributeError: 'Server' object has no attribute 'list_tools'` -- a raw
# traceback that the old `_require_sdk()` could not catch, because `import mcp`
# succeeds perfectly well on 2.x. The extra is now bounded below 2, and the
# guard checks the API surface rather than the mere importability of the
# package. The fake SDK below is what makes this testable without installing
# any SDK at all: the suite still never imports the real `mcp`.

def _fake_sdk(monkeypatch, *, decorators: bool, version="2.2.0",
              with_server_module=True):
    """Install a minimal stand-in for the `mcp` package in sys.modules.

    `decorators=False` reproduces the 2.x shape: importable, with a `Server`
    class that has no `list_tools`/`call_tool`.
    """
    import types as _types

    mcp_pkg = _types.ModuleType("mcp")
    mcp_pkg.__version__ = version

    def _noop_decorator(self):
        def register(fn):
            return fn
        return register

    class Server:
        def __init__(self, name):
            self.name = name

        def create_initialization_options(self):
            return {}

    if decorators:
        Server.list_tools = _noop_decorator
        Server.call_tool = _noop_decorator

    modules = {"mcp": mcp_pkg}
    if with_server_module:
        server_mod = _types.ModuleType("mcp.server")
        server_mod.Server = Server
        stdio_mod = _types.ModuleType("mcp.server.stdio")
        stdio_mod.stdio_server = None
        types_mod = _types.ModuleType("mcp.types")
        types_mod.TextContent = object
        types_mod.Tool = object
        mcp_pkg.server = server_mod
        server_mod.stdio = stdio_mod
        mcp_pkg.types = types_mod
        modules.update({"mcp.server": server_mod,
                        "mcp.server.stdio": stdio_mod,
                        "mcp.types": types_mod})
    else:
        monkeypatch.setitem(sys.modules, "mcp.server", None)
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return mcp_pkg


def test_r8_an_sdk_without_the_decorator_api_is_an_instruction(mini_index,
                                                               monkeypatch):
    """R-8 (a): the exact shape that shipped broken -- serve() must refuse,
    naming the installed version and what to install, not raise
    AttributeError from inside the SDK wiring."""
    mcp = mcp_module()
    _fake_sdk(monkeypatch, decorators=False, version="2.2.0")
    with pytest.raises(SystemExit) as exc:
        mcp.serve(Path(mini_index))
    message = str(exc.value)
    assert "2.2.0" in message, message
    assert "mcp>=1.0,<2" in message, message
    assert exc.value.code not in (0, None)


def test_r8_the_entry_point_refuses_the_same_way(mini_index, monkeypatch):
    """R-8 (b): via the console script, which is how a user meets it."""
    mcp = mcp_module()
    _fake_sdk(monkeypatch, decorators=False, version="2.2.0")
    with pytest.raises(SystemExit) as exc:
        mcp.main(["--out", str(mini_index)])
    assert "mcp>=1.0,<2" in str(exc.value), str(exc.value)


def test_r8_a_broken_server_module_is_also_an_instruction(mini_index,
                                                          monkeypatch):
    """R-8 (c): the other way a future SDK can move -- `mcp` imports but
    `mcp.server` does not."""
    mcp = mcp_module()
    _fake_sdk(monkeypatch, decorators=False, with_server_module=False)
    with pytest.raises(SystemExit) as exc:
        mcp._require_sdk()
    assert "mcp>=1.0,<2" in str(exc.value), str(exc.value)


def test_r8_a_supported_sdk_passes_the_guard(monkeypatch):
    """R-8 (d): the guard must not become a blanket refusal -- an SDK that
    does carry the API serve() needs is accepted."""
    mcp = mcp_module()
    fake = _fake_sdk(monkeypatch, decorators=True, version="1.9.0")
    assert mcp._require_sdk() is fake


def test_r8_the_missing_sdk_message_is_still_the_missing_sdk_message(
        mini_index, monkeypatch):
    """R-8 (e): absent and unusable are different problems with different
    instructions; the new branch must not swallow AC-33's."""
    mcp = mcp_module()
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit) as exc:
        mcp.serve(Path(mini_index))
    assert 'pip install "repo2graph[mcp]"' in str(exc.value)
    assert "not supported" not in str(exc.value)


def test_r8_the_extra_is_bounded_below_the_unsupported_major():
    """R-8 (f): the declared extra and the guard's advice are one string. An
    unbounded `mcp>=1.0` resolves to 2.x and is what caused this."""
    mcp = mcp_module()
    spec = load_pyproject()["project"]["optional-dependencies"]["mcp"]
    assert spec == [mcp.SDK_SPEC], (spec, mcp.SDK_SPEC)
    assert "<2" in mcp.SDK_SPEC


# ==========================================================================
# R-10 -- a floor-clamped budget must not hand an agent an empty string
# ==========================================================================

@pytest.mark.parametrize("budget", [0, -5, -10**9, 1])
def test_r10_a_floor_clamped_budget_explains_itself(big_index, budget):
    """R-10 (a): AC-28 only requires "no crash"; an empty tool result reads to
    an agent exactly like "no such code", so say which it was."""
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.tool_repo_search(idx, MINI_QUERY, k=20, budget_tokens=budget)
    assert out.strip(), "an empty string is the thing this test exists to stop"
    assert "budget_tokens" in out and str(mcp.MCP_MAX_BUDGET_TOKENS) in out
    assert tokens(out) <= mcp.MCP_MAX_BUDGET_TOKENS


def test_r10_the_note_is_short_and_never_the_normal_answer(big_index):
    """R-10 (b): a real pack must not be replaced by the note, and the note
    must stay far below the default budget so it cannot itself be trimmed."""
    mcp = mcp_module()
    idx = Index(big_index)
    real = mcp.tool_repo_search(idx, MINI_QUERY)
    assert "### [cite:" in real
    assert "no content fit in" not in real
    assert tokens(mcp.EMPTY_RESULT.format(budget=1, ceiling=12000)) < 200


def test_r10_dispatch_inherits_the_note(big_index):
    """R-10 (c): the note lives in the handler, so the JSON route gets it too."""
    mcp = mcp_module()
    idx = Index(big_index)
    out = mcp.dispatch(idx, "repo_search",
                       {"query": MINI_QUERY, "budget_tokens": -5})
    assert out.strip() and "budget_tokens" in out
