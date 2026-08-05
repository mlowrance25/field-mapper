# FieldMapper

AI-powered field profiling and relationship discovery for city transportation datasets. Upload a CSV or JSON file and get a data dictionary, field assessment, and relationship analysis — before ingestion, without a database.

## Setup

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
uv sync
```

**API key:** Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
uv run streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Pages

| Page | What it does |
|------|-------------|
| Upload | Load a CSV or JSON dataset |
| Data Dictionary | AI-generated field descriptions, provenance, and confidence |
| Data Assessment | Field categories, reliability, classifiers, and relationships |
| Relationship Analysis | Cardinality and completeness checks between field pairs |

## MCP Server

`mcp_server.py` exposes this repo's deterministic analyzers over stdio via MCP, as a second entry point alongside the Streamlit UI. See the module docstring for the planned HTTP/SSE + auth mode (PLAN-009 Phase 6).

### Test locally with MCP Inspector

Fastest way to interactively call tools and inspect raw request/response traffic — no client wiring needed:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python mcp_server.py
```

- Run from anywhere — both paths are absolute in the config, or run from repo root if you switch to relative paths.
- First run downloads the Inspector package via `npx` (cached after that — nothing installed globally).
- Opens a local web UI (prints a `localhost:6274` URL with an auth token — open that link).
- In the UI: **Tools** tab → **List Tools** → select a tool (e.g. `health_check`) → **Run Tool** → check the **Results** panel.
- The **Console** tab (right side) shows server log/notification output, not tool results.
- `Ctrl+C` in the terminal stops the server and Inspector.

### Wire into a real MCP client

To exercise it through Claude Code instead of Inspector:

```bash
claude mcp add fieldmapper /Users/marvlow/Code/Personal/field-mapper/.venv/bin/python /Users/marvlow/Code/Personal/field-mapper/mcp_server.py
```

Then `claude mcp list` should show `fieldmapper` connected, and its tools become callable in a session.

It's also already registered for the Claude Desktop app in `~/Library/Application Support/Claude/claude_desktop_config.json` (only takes effect if Claude Desktop is installed).
