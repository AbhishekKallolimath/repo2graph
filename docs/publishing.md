# Releasing and listing repo2graph

Publishing is automated — `.github/workflows/publish.yml` ships to PyPI and the
MCP Registry from one GitHub Release, with no long-lived credential anywhere.
But three things have to be set up by hand **once**, because they need you to be
logged in as you. Do those first, then every release is a tag push.

---

## One-time setup

### 1. Register the PyPI Trusted Publisher

PyPI has to be told which workflow is allowed to publish `repo2graph`. Until this
exists, the `pypi` job fails with `invalid-publisher`.

Go to <https://pypi.org/manage/account/publishing/> and add a **pending**
publisher (pending = the project does not exist on PyPI yet, which is the case
here):

| Field | Value |
|---|---|
| PyPI Project Name | `repo2graph` |
| Owner | `Srinivasan-78` |
| Repository name | `repo2graph` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

The environment name matters: the workflow declares `environment: name: pypi`,
and PyPI checks it. A mismatch here is the single most common failure.

> The name `repo2graph` was unclaimed on PyPI as of this writing. If someone
> takes it first, change `[project] name` in `pyproject.toml` *and* the
> `identifier` in `server.json`, and re-register.

### 2. Create the `pypi` environment on GitHub

Settings → Environments → **New environment** → `pypi`. No secrets go in it —
it exists so the publish is gated and shows up in the deployment log. Add a
required reviewer if you want a human to approve each release.

### 3. Nothing to do for the MCP Registry

`mcp-publisher login github-oidc` authenticates as this repository using the
workflow's OIDC token, so there is no account to create and no secret to store.
The namespace `io.github.Srinivasan-78/*` is yours automatically because it
matches the repo owner.

---

## Cutting a release

1. Bump the version in **both** places — they are checked against the tag before
   anything is published:
   - `pyproject.toml` → `[project] version`
   - `server.json` → `version` **and** `packages[0].version`
2. Commit, and re-stamp the watermarks (see [AGENTS.md](../AGENTS.md)).
3. Publish a GitHub Release with tag `vX.Y.Z`.

That one event runs two workflows:

- `release.yml` moves the floating `v1` tag, so `uses: Srinivasan-78/repo2graph@v1`
  keeps working.
- `publish.yml` checks the versions agree, runs the tests, builds, uploads to
  PyPI, waits for PyPI to actually serve the new version, then publishes
  `server.json` to the MCP Registry.

Verify:

```bash
pip index versions repo2graph
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=repo2graph" | jq .
uvx --from "repo2graph[mcp]" repo2graph-mcp /some/project    # the thing users will run
```

### The ownership marker

The registry proves you own the PyPI package by finding this exact string in the
package description, which setuptools takes from `README.md`:

```
<!-- mcp-name: io.github.Srinivasan-78/repo2graph -->
```

It is near the top of `README.md` and `publish.yml` refuses to run without it.
Do not remove it, and do not let it end up glued to trailing punctuation — the
token must be followed by whitespace, a newline, or the comment close.

---

## Listing it

**Do these after the first successful publish, not before.** Both lists point
people at an install command; submitting while `pip install repo2graph` still
404s wastes the reviewer's time and yours.

### MCP Registry

Automatic — `publish.yml` does it. Nothing to submit.

### punkpeye/awesome-mcp-servers

Accepts pull requests. Fork, add the line below to the **Developer Tools**
section, and open a PR. Their `CONTRIBUTING.md` fast-tracks agent-authored PRs
if the title ends with `🤖🤖🤖`.

```markdown
- [Srinivasan-78/repo2graph](https://github.com/Srinivasan-78/repo2graph) [![Srinivasan-78/repo2graph MCP server](https://glama.ai/mcp/servers/Srinivasan-78/repo2graph/badges/score.svg)](https://glama.ai/mcp/servers/Srinivasan-78/repo2graph) 🐍 🏠 🍎 🪟 🐧 - Ask a codebase questions and get cited code back. Builds a tree-sitter graph of the repo — files, functions, calls, imports, inheritance — then answers with BM25 plus graph expansion, so every hit arrives with its callers and callees attached and a `[cite: path:start-end]` header. Three tools: `repo_map`, `repo_search`, `repo_neighbours` (the graph hop grep cannot do). Indexes the repo itself on the first call, so there is no setup step. Output is hard-capped at 12k tokens and paths that look like credential stores are never returned. `uvx --from "repo2graph[mcp]" repo2graph-mcp /path/to/project`
```

Legend used: 🐍 Python codebase, 🏠 local service, 🍎🪟🐧 all three platforms.
Not 🎖️ — that means an official vendor implementation.

### wong2/awesome-mcp-servers

**Does not accept pull requests.** Its README says so at the top. Submit through
the form instead:

<https://mcpservers.org/submit>

Use the same description and the `uvx` command above.

### Worth considering too

- **Glama** (<https://glama.ai/mcp/servers>) — indexes from the registry and the
  awesome lists; the badge in the entry above is theirs.
- **mcp.so**, **Smithery** (<https://smithery.ai>) — both take direct
  submissions and are where a lot of client UIs pull their directory from.
