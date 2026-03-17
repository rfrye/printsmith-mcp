# CLAUDE.md — PrintSmith MCP Server

This file describes the codebase for AI assistants working in this repository.

## Project Overview

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/docs) server that connects Claude to **PrintSmith Vision**, a print shop management system (EFI/ePS). It exposes 10 read-only tools for querying customers, invoices, estimates, and accounts receivable.

**All operations are strictly READ-ONLY. No data is ever written to PrintSmith.**

---

## Repository Structure

```
printsmith-mcp/
├── src/
│   ├── server.py              # Main MCP server — entry point, all tool definitions
│   ├── printsmith_db.py       # Direct PostgreSQL client (active backend)
│   ├── printsmith_client.py   # Legacy HTTP API client (not used by server.py)
│   └── __init__.py
├── scripts/
│   ├── setup-lxc.sh           # Create LXC container on Proxmox
│   ├── deploy-to-lxc.sh       # Copy files to LXC container
│   └── install.sh             # Install & configure inside container
├── requirements.txt
├── README.md
└── CLAUDE.md                  # This file
```

---

## Architecture

### Data Flow

```
Claude ──MCP──► server.py ──► printsmith_db.py ──► PostgreSQL (PrintSmith DB)
                    │
                    └──► Mock data (when PG not configured)
```

### Transport Modes

The server supports two transport modes, selected via `MCP_TRANSPORT`:

| Mode | Use Case | How |
|------|----------|-----|
| `stdio` (default) | Local Claude Desktop | stdin/stdout |
| `http` | Remote (LXC/Docker) | HTTP + SSE at `/sse` and `/messages` |

HTTP mode uses `starlette` + `uvicorn` with Server-Sent Events. The SSE endpoint is `/sse`, health check is at `/health`.

---

## Key Files

### `src/server.py`

The main entry point. Contains:

- **`Config` class** — All configuration from environment variables. Auto-falls back to mock data if `PG_HOST` or `PG_PASSWORD` is missing.
- **Mock data** — `MOCK_CUSTOMERS`, `MOCK_INVOICES`, `MOCK_ESTIMATES` — in-memory dicts used when `USE_MOCK_DATA=true` or DB is unconfigured.
- **`get_db()`** — Lazy-initializes the `PrintSmithDB` singleton connection pool.
- **`list_tools()`** — Registers all 10 MCP tools with their schemas.
- **`call_tool()`** — Routes tool calls to private `_tool_name()` functions.
- **`run_stdio()` / `run_http()`** — Transport implementations.

Tool implementations all follow the same pattern:
1. Check `Config.USE_MOCK_DATA` — if true, query in-memory dicts
2. Otherwise, call the appropriate `PrintSmithDB` method
3. Return `list[TextContent]` with JSON-serialized results

### `src/printsmith_db.py`

Direct async PostgreSQL client using `asyncpg`. Key design points:

- **`PrintSmithDBConfig`** dataclass holds connection parameters
- **`PrintSmithDB`** manages a lazy connection pool (`_pool`)
- **`_fetch()` / `_fetchrow()`** are the only query primitives — both are SELECT-only
- **`run_readonly_query()`** accepts arbitrary SQL but rejects non-SELECT/WITH statements
- **`discover_schema()`** queries `information_schema` — useful for debugging column name mismatches
- **`sample_table()`** validates table names (alphanumeric + underscore only) before interpolating

**Schema note**: PrintSmith Vision uses non-standard column names. Key mappings:
- Customer table: `account`, primary key is `id`, display number is `useracctid`, name is `title`
- Invoice table: `invoicebase`, joined to `account` via `account_id`
- Estimates table: `estimate`, joined to `account` via `account_id`

### `src/printsmith_client.py`

Legacy HTTP API client for the PrintSmith Vision E-Commerce Integration API. **Not currently used by `server.py`** (replaced by the direct PostgreSQL approach). Kept for reference or future use. Uses `httpx` for async HTTP requests with token-in-URL auth (`/{ResourceAPI}/{API_TOKEN}`).

---

## MCP Tools Reference

| Tool | Required Args | Optional Args |
|------|--------------|---------------|
| `lookup_customer` | `query` | — |
| `get_job_status` | `job_number` | — |
| `list_jobs` | — | `status`, `customer_name`, `days_back`, `taken_by` |
| `get_customer_jobs` | `customer_name` | — |
| `get_ar_summary` | — | `min_balance` |
| `get_estimate` | `estimate_number` | — |
| `list_pending_estimates` | — | `customer_name` |
| `discover_schema` | — | `table_name` |
| `sample_table` | `table_name` | `limit` (max 10) |
| `health_check` | — | — |

`discover_schema` and `sample_table` only work in live DB mode (not mock).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_HOST` | `""` | PostgreSQL host (required for live mode) |
| `PG_PORT` | `5432` | PostgreSQL port |
| `PG_DATABASE` | `printsmith` | Database name |
| `PG_USER` | `postgres` | Database user |
| `PG_PASSWORD` | `""` | Database password (required for live mode) |
| `PG_TIMEOUT` | `30` | Query timeout in seconds |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HTTP_PORT` | `8080` | HTTP port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP bind address |
| `USE_MOCK_DATA` | `false` | Force mock data mode |

The server auto-loads `.env` from the project root via `python-dotenv` (the `.env` file is one level above `src/`).

---

## Development Workflow

### Running Locally (Mock Data)

```bash
cd printsmith-mcp
pip install -r requirements.txt

# Test with built-in mock data (no DB needed)
USE_MOCK_DATA=true python src/server.py
```

### Running with Live DB

Create a `.env` file in the project root:

```ini
PG_HOST=192.168.1.100
PG_PASSWORD=your_password
PG_DATABASE=printsmith
MCP_TRANSPORT=stdio  # or http
```

Then:
```bash
python src/server.py
```

### HTTP Mode (LXC/Remote)

```bash
MCP_TRANSPORT=http MCP_HTTP_PORT=8080 python src/server.py
# Health: curl http://localhost:8080/health
# SSE:    http://localhost:8080/sse
```

---

## Deployment (Proxmox LXC)

1. **Create container**: `bash scripts/setup-lxc.sh` (run on Proxmox host, edit variables at top)
2. **Deploy files**: `bash scripts/deploy-to-lxc.sh <CTID>`
3. **Install inside container**: `pct enter <CTID>` then `bash /opt/printsmith-mcp/scripts/install.sh`
4. **Configure**: `nano /opt/printsmith-mcp/.env` — set `PG_HOST`, `PG_PASSWORD`, `USE_MOCK_DATA=false`
5. **Start service**: `systemctl start printsmith-mcp`

The install script creates a `systemd` service running as the `mcp` user with security hardening (`NoNewPrivileges`, `ProtectSystem=strict`).

---

## Conventions & Patterns

### Adding a New Tool

1. Add a `Tool(...)` entry in `list_tools()` in `server.py`
2. Add a routing `elif name == "new_tool":` in `call_tool()`
3. Implement `async def _new_tool(db, arguments: dict) -> list[TextContent]:`
   - Handle `Config.USE_MOCK_DATA` branch first
   - Call a method on `PrintSmithDB` for live mode
   - Return `[TextContent(type="text", text=json.dumps(result, default=str))]`
4. Add the DB method to `printsmith_db.py` — use `_fetch()` or `_fetchrow()` only

### Error Handling

- DB errors bubble up through `PrintSmithDBError` and are caught in `call_tool()` — returned as text error messages, never exceptions to the MCP client
- Schema mismatches: use `discover_schema` tool first, then adjust queries in `printsmith_db.py`
- `json.dumps(..., default=str)` handles `datetime`, `Decimal`, and other non-JSON-serializable types

### SQL Safety

- Never use f-strings to interpolate user input into SQL — always use `asyncpg` parameterized queries (`$1`, `$2`, ...)
- `sample_table()` validates table names to alphanumeric + underscore before interpolating the table name into SQL
- Only `SELECT` and `WITH` statements are permitted in `run_readonly_query()`

### Schema Variability

PrintSmith Vision schema column names can vary by installation and version. If queries fail:
1. Call `discover_schema` tool (or `discover_schema(table_name="account")`) to inspect actual columns
2. Call `sample_table` to see real data shapes
3. Update the queries in `printsmith_db.py` accordingly

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `mcp>=1.0.0` | MCP protocol SDK |
| `asyncpg>=0.29.0` | Async PostgreSQL client |
| `uvicorn>=0.30.0` | ASGI server for HTTP transport |
| `starlette>=0.38.0` | HTTP routing for HTTP transport |
| `anyio>=4.0.0` | Async runtime support |
| `python-dotenv>=1.0.0` | Auto-load `.env` file |

---

## Git Branches

- `master` — main development branch
- `claude/add-claude-documentation-lu6xA` — documentation feature branch

---

## Security Notes

- The `.env` file is created with `chmod 600` (owner read/write only)
- The systemd service runs as the unprivileged `mcp` user
- All PostgreSQL queries are parameterized (no SQL injection risk from user input)
- The HTTP transport has no authentication — use firewall rules to restrict access to the MCP port
- For production/multi-tenant: add authentication to the `/sse` endpoint and per-customer credential storage
