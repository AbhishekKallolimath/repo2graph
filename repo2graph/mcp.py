# @authormark v1 -- do not remove (authorship watermark)⁠​​‌‌​‌‌‌​‌​​​‌‌​​‌​​‌‌‌‌​​‌‌​‌‌‌​​‌‌​‌​​​‌​​​‌​​​‌‌‌​​​​​‌​‌​‌​​​‌​​​‌​​​‌‌‌​‌​​​​‌‌​‌​​​‌‌‌‌​‌​​‌‌​​​​‌​‌​‌‌​​​​‌‌​​​‌​​‌​​‌​‌​​​‌‌​​‌​​​‌‌​​‌​​‌​‌​​‌​​​‌‌​​‌‌​‌‌​‌​​‌​‌​‌​‌‌​⁠
# Copyright (c) 2026 Srinivasan Vijayaraghavan <srinivasan.shyam2000@gmail.com>
# Author: https://github.com/Srinivasan-78
# SPDX-License-Identifier: MIT
# Fingerprint: AMK1.7FO74DpTDt4zaXbJ22R3iV
"""A stdio MCP server over an existing .r2g index: three tools, one engine.

This is an *additional* surface, not a replacement: every tool is a thin call
into `repo2graph.query.Index`, the same object the CLI and the GitHub Action
use, over the same artifacts. The `mcp` SDK is an optional extra and is
imported only inside serve(), so importing this module costs nothing and the
handlers below are testable without the SDK installed.

Two rules apply to every handler and are not negotiable per call:

* `exclude_secrets=True`, always. The CLI sets it only for `--answer`, but a
  tool an agent can call unattended returning `.env` contents is a different
  class of problem from a human deliberately grepping their own checkout.
* Output is hard-bounded. An agent-facing tool that *can* return 50k tokens
  eventually will, so the caller's budget is clamped and the rendered result
  is re-measured and trimmed rather than trusted.
* Work is hard-bounded too. `k` and `hops` are clamped before they reach the
  engine: serve() awaits every call on one asyncio loop, so a single argument
  that costs minutes wedges the whole server for every client, not just the
  caller that sent it.
"""
import argparse
import sys
from pathlib import Path

from .query import Index, _fit_lines, count_tokens

# The budget a call gets when it asks for nothing, and the ceiling no call can
# raise: roughly a quarter of a small model's context, and half of it.
MCP_BUDGET_TOKENS = 6000
MCP_MAX_BUDGET_TOKENS = 12000

# Neighbours listed by repo_neighbours when the caller names no limit, and the
# ceiling no call can raise. `hops` bounds the *time* that tool costs but not
# the *size* of its answer -- the 4-hop reachable set of a mid-size graph is
# most of the graph -- and it is the one tool whose output no token budget
# measures, so the row count is the only thing standing between an agent and a
# 35k-character reply. 50 rows is the same order as MCP_MAX_K.
MCP_NEIGHBOUR_LIMIT = 20
MCP_MAX_NEIGHBOURS = 50

# Ceilings on the two arguments that cost *time* rather than output size.
# `Index.expand` runs `for _ in range(hops)` with no empty-frontier exit, so an
# unclamped `hops=10**9` pins the asyncio loop serve() runs on for ~a minute and
# wedges the whole server -- every tool, every client -- on one bad JSON value a
# model wrote. Four hops already crosses the width of any real call graph, and
# 50 seeds is well past what any budget can render.
MCP_MAX_HOPS = 4
MCP_MAX_K = 50

# Loaded into every agent's context every session, so they are charged for on
# every request whether or not a tool is called: keep them short (AC-31 caps
# the three combined at 600 characters).
TOOL_DESCRIPTIONS = {
    "repo_map": (
        "Repo map: languages, hub files and top entry points. No arguments, "
        "stable across calls. Read this first."),
    "repo_search": (
        "Search the repo for a question and get cited code back: seed chunks "
        "plus their graph neighbours, each headed `[cite: path:start-end]`."),
    "repo_neighbours": (
        "Graph hop from one node id (e.g. sym:pkg/a.py::run): callers, "
        "callees, base classes and the defining file, with edge direction."),
}

TOOL_SCHEMAS = {
    "repo_map": {"type": "object", "properties": {}},
    "repo_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "the question"},
            "k": {"type": "integer",
                  "description": f"seed chunks (default 8, max {MCP_MAX_K})"},
            "hops": {"type": "integer",
                     "description": f"graph hops (default 1, max {MCP_MAX_HOPS})"},
            "budget_tokens": {"type": "integer",
                              "description": f"max {MCP_MAX_BUDGET_TOKENS}"},
        },
        "required": ["query"],
    },
    "repo_neighbours": {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "e.g. sym:pkg/a.py::run"},
            "hops": {"type": "integer",
                     "description": f"graph hops (default 1, max {MCP_MAX_HOPS})"},
            "limit": {"type": "integer",
                      "description": (f"neighbours (default {MCP_NEIGHBOUR_LIMIT}, "
                                      f"max {MCP_MAX_NEIGHBOURS})")},
        },
        "required": ["node_id"],
    },
}

# What repo_search says instead of handing back an empty string.
EMPTY_RESULT = ("no content fit in a {budget}-token budget: nothing matched, "
                "or the budget was too small to render a single line. Retry "
                "with a broader query or budget_tokens up to {ceiling}.")

_INDEXES: dict[str, Index] = {}


def open_index(out) -> Index:
    """One Index per output directory, reused for the life of the process.

    Building an Index reads and inverts every chunk; doing that per tool call
    would make the second call as expensive as the first.
    """
    key = str(Path(out).resolve())
    index = _INDEXES.get(key)
    if index is None:
        index = _INDEXES[key] = Index(Path(out))
    return index


# --------------------------------------------------------------- tools ----

def tool_repo_map(index: Index) -> str:
    """The repo map, verbatim: stable, cacheable, no query argument."""
    return index.map_prepend()


def tool_repo_search(index: Index, query: str, k: int = 8, hops: int = 1,
                     budget_tokens=None) -> str:
    """Cited markdown for `query`, never wider than MCP_MAX_BUDGET_TOKENS."""
    budget = MCP_BUDGET_TOKENS if budget_tokens is None else _int(budget_tokens,
                                                                  MCP_BUDGET_TOKENS)
    budget = max(1, min(budget, MCP_MAX_BUDGET_TOKENS))
    pack = index.pack_context(query, k=_clamp(k, 8, 1, MCP_MAX_K),
                              hops=_clamp(hops, 1, 0, MCP_MAX_HOPS),
                              budget_tokens=budget, exclude_secrets=True)
    text = pack["markdown"]
    if count_tokens(text) > budget:
        # pack_context measures the text it assembles, but the ceiling is the
        # promise made to the caller: re-check it here rather than trust it.
        text = _fit_lines(text, budget, count_tokens)
    if not text.strip():
        # A budget clamped to the floor renders nothing, and an empty tool
        # result is the one answer an agent cannot act on: it reads the same
        # as "no such code". The note deliberately overruns a floor-sized
        # budget -- the promise this handler makes is the MCP_MAX ceiling, and
        # a sentence is cheaper than a retry loop against a blank string.
        return EMPTY_RESULT.format(budget=budget, ceiling=MCP_MAX_BUDGET_TOKENS)
    return text


def tool_repo_neighbours(index: Index, node_id: str, hops: int = 1,
                         limit: int = MCP_NEIGHBOUR_LIMIT) -> str:
    """One graph hop from `node_id` — the thing grep cannot do."""
    node = index.nodes.get(node_id)
    if node is None:
        return (f"node not found: {node_id!r}. Ids look like "
                f"file:<path>, sym:<path>::<qualname> or dir:<path>.")
    limit = _clamp(limit, MCP_NEIGHBOUR_LIMIT, 1, MCP_MAX_NEIGHBOURS)
    lines = [f"neighbours of {_label(index, node_id)}:"]
    for dst, etype, direction, _src in index.expand(
            [node_id], hops=_clamp(hops, 1, 0, MCP_MAX_HOPS)):
        target = index.nodes.get(dst, {})
        if index._is_secret_path(target.get("path") or ""):
            continue
        lines.append(f"- {etype} {direction}: {_label(index, dst)}")
        if len(lines) > limit:
            break
    if len(lines) == 1:
        lines.append("- (none)")
    return "\n".join(lines)


def _label(index: Index, node_id: str) -> str:
    node = index.nodes.get(node_id) or {}
    name = node.get("qualname") or node.get("name") or node_id
    where = node.get("path") or ""
    start = node.get("start_line")
    where = f"{where}:{start}" if where and start else where
    return f"`{name}` ({where}) [{node_id}]" if where else f"`{name}` [{node_id}]"


def _int(value, fallback: int) -> int:
    """An MCP client's arguments are JSON a model wrote: coerce, never raise."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value, fallback: int, low: int, high: int) -> int:
    """_int, then held inside [low, high]: no argument may cost unbounded time."""
    return max(low, min(_int(value, fallback), high))


def dispatch(index: Index, name: str, arguments: dict) -> str:
    """Route one tool call to its handler. Pure, so serve() holds no logic."""
    args = arguments or {}
    if name == "repo_map":
        return tool_repo_map(index)
    if name == "repo_search":
        return tool_repo_search(index, str(args.get("query") or ""),
                                k=_int(args.get("k"), 8),
                                hops=_int(args.get("hops"), 1),
                                budget_tokens=args.get("budget_tokens"))
    if name == "repo_neighbours":
        return tool_repo_neighbours(index, str(args.get("node_id") or ""),
                                    hops=_int(args.get("hops"), 1),
                                    limit=_int(args.get("limit"),
                                               MCP_NEIGHBOUR_LIMIT))
    return f"unknown tool: {name!r}. Available: {', '.join(TOOL_DESCRIPTIONS)}."


# -------------------------------------------------------------- server ----

MISSING_SDK = ('the MCP server needs the optional `mcp` extra: '
               'pip install "repo2graph[mcp]"')

# The SDK range serve() is written against, and the API it needs from it.
# serve() uses the 1.x decorator API (`@server.list_tools()` /
# `@server.call_tool()`); mcp 2.x removed both methods from `Server`, so a 2.x
# install *imports* perfectly and then dies mid-serve() with
# `AttributeError: 'Server' object has no attribute 'list_tools'`. A successful
# `import mcp` is therefore not evidence the SDK is usable -- the guard has to
# look at the API surface, or the user gets exactly the traceback it exists to
# prevent, one SDK major later.
SDK_SPEC = "mcp>=1.0,<2"
REQUIRED_SERVER_API = ("list_tools", "call_tool")


def _sdk_version(module) -> str:
    """Best-effort version of the installed SDK, for the error message."""
    version = getattr(module, "__version__", None)
    if version:
        return str(version)
    try:
        from importlib.metadata import version as _dist_version
        return str(_dist_version("mcp"))
    except Exception:
        return "unknown"


def _unusable_sdk(version: str, detail: str) -> str:
    return (f"the installed mcp SDK ({version}) is not supported by "
            f"repo2graph-mcp: {detail}. Install a 1.x SDK instead: "
            f'pip install "{SDK_SPEC}" '
            '(or `pip install "repo2graph[mcp]"` in a clean environment).')


def _require_sdk():
    """Turn a missing *or unusable* optional dependency into an instruction.

    Two distinct failures, both of which must end in a sentence a user can act
    on rather than a traceback: the SDK is absent, or the SDK is present but
    speaks an API serve() cannot drive.
    """
    try:
        import mcp
    except ImportError:
        raise SystemExit(MISSING_SDK) from None
    if mcp is None:
        raise SystemExit(MISSING_SDK)
    try:
        from mcp.server import Server
    except ImportError as exc:
        raise SystemExit(_unusable_sdk(
            _sdk_version(mcp), f"`from mcp.server import Server` failed ({exc})")) from None
    missing = [name for name in REQUIRED_SERVER_API if not hasattr(Server, name)]
    if missing:
        raise SystemExit(_unusable_sdk(
            _sdk_version(mcp),
            "its Server has no " + "/".join(missing)
            + " decorator (removed in mcp 2.x)"))
    return mcp


def serve(out) -> None:
    """Run the stdio MCP server against the index at `out`.

    Deliberately thin: every answer comes from dispatch(), which is tested
    without the SDK, so SDK API drift can break the wiring but nothing else.
    """
    _require_sdk()
    import asyncio

    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    index_dir = Path(out)
    server = Server("repo2graph")

    @server.list_tools()
    async def list_tools():
        return [Tool(name=name, description=description,
                     inputSchema=TOOL_SCHEMAS[name])
                for name, description in TOOL_DESCRIPTIONS.items()]

    @server.call_tool()
    async def call_tool(name, arguments):
        text = dispatch(open_index(index_dir), name, arguments or {})
        return [TextContent(type="text", text=text)]

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream,
                             server.create_initialization_options())

    asyncio.run(_run())


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="repo2graph-mcp",
        description="Serve a repo2graph index over MCP on stdio")
    p.add_argument("-o", "--out", default=".r2g",
                   help="index directory built by `repo2graph build` (default: .r2g)")
    args = p.parse_args(argv)
    serve(Path(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
