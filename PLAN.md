# PrintSmith MCP — Production Plan

> Created: 2026-03-17. Last updated: 2026-03-17.

---

## Context

- PrintSmith Vision runs on a **Windows Server** (bare metal or VM) on the LAN
- PostgreSQL (bundled with PrintSmith) has port 5432 **open to the LAN**
- MCP server currently talks to a **manual DB dump** — stale, non-live
- Goal: move to live production data with strong safety guarantees

---

## Agreed Architecture

```
Claude Desktop (admin)
        │
        │  HTTP + SSE (MCP protocol)
        ▼
┌─────────────────────────────────────┐
│  Proxmox LXC — printsmith-mcp      │
│                                     │
│  printsmith-mcp (systemd service)  │
│        │                            │
│        ▼                            │
│  PostgreSQL (local, on LXC)         │  ← MCP server always talks to this
│        ▲                            │
│  sync-db.sh (cron, every 15-30m)   │
└──────────────────────────────────┬──┘
                                   │ pg_dump (read-only, over LAN)
                                   ▼
                     ┌─────────────────────────┐
                     │  PrintSmith Windows      │
                     │  PostgreSQL (port 5432)  │  ← Never written to
                     └─────────────────────────┘
```

**Key safety properties:**
- MCP server never connects to PrintSmith Postgres directly
- pg_dump is inherently read-only (SELECT only)
- Dedicated read-only Postgres user on Windows (GRANT SELECT only)
- All queries in `printsmith_db.py` are parameterized
- `run_readonly_query()` rejects non-SELECT statements

---

## Replica Strategy Decision

**Chosen: Scheduled pg_dump snapshot (not streaming replication)**

Reasons:
- Zero risk to production — pg_dump is read-only
- No changes needed to PrintSmith's Postgres config
- 15-30 min data freshness is acceptable for operational queries
- Completely isolated — MCP talks to local Postgres copy
- Streaming replication was the alternative but adds complexity and requires touching Windows Postgres config

---

## Phases of Work

### Phase 1 — LXC Setup & Data Pipeline *(not started)*
- [ ] Create Proxmox LXC (Debian/Ubuntu, 2 CPU, 2GB RAM, ~20GB disk)
- [ ] Install PostgreSQL on LXC (snapshot target DB, separate from PrintSmith)
- [ ] Create dedicated read-only Postgres user on PrintSmith's Windows Postgres
- [ ] Write `scripts/sync-db.sh`: pg_dump from Windows → pg_restore to LXC local Postgres
- [ ] Set up cron on LXC running `sync-db.sh` every 15-30 minutes
- [ ] Update `scripts/setup-lxc.sh`, `deploy-to-lxc.sh`, `install.sh` to reflect new architecture

### Phase 2 — MCP Server Deployment *(not started)*
- [ ] Deploy MCP server to LXC via updated deploy script
- [ ] Configure `.env` to point at `localhost` Postgres (LXC local, not Windows)
- [ ] Start systemd service, verify `health_check` tool works with real data
- [ ] Test all 10 tools against real snapshot data

### Phase 3 — Claude Desktop Connection *(not started)*
- [ ] Configure `claude_desktop_config.json` to connect to MCP via HTTP/SSE
- [ ] Verify end-to-end: Claude Desktop → LXC → real PrintSmith data

### Phase 4 — Future Expansion *(design for, don't build yet)*
- Staff access (same MCP server, auth layer TBD)
- Customer-facing job status (needs scoped queries + auth)
- Automated workflows / webhook triggers

---

## Environment — Collected

| Item | Value |
|------|-------|
| PrintSmith Postgres host | `10.0.0.126` |
| Postgres port | `5432` |
| Postgres database | `printsmith` |
| Postgres superuser | `postgres` / `postgres` (default — see read-only user plan below) |
| Postgres version | `9.3.4` (Visual C++ build, 64-bit) — **see compatibility note** |
| LAN subnet | `10.0.0.0/24` |
| Proxmox host IP | `10.0.0.99` |
| New LXC CTID | `300` |

### PostgreSQL 9.3 Compatibility Note

PrintSmith ships with **PostgreSQL 9.3.4**, which is EOL (end of life since 2018). This affects the sync pipeline:

- `pg_dump` on the LXC must be version **9.3.x** OR a newer client (10+) using `--no-privileges --no-owner` — modern `pg_dump` can dump from older servers but format differences exist
- **Recommended**: install `postgresql-client-9.3` on the LXC, or use `pg_dump` ≥ 10 with `--format=plain` and test carefully
- `asyncpg` (used by the MCP server) supports PostgreSQL 9.3+ — no issue there

### Read-Only User Plan

**Before using `postgres/postgres` for anything, create a dedicated read-only user.**
Run this on the PrintSmith Postgres (connect as `postgres`):

```sql
CREATE USER mcp_readonly WITH PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE printsmith TO mcp_readonly;
GRANT USAGE ON SCHEMA public TO mcp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_readonly;
```

Then use `mcp_readonly` for all `pg_dump` and MCP server connections. The `postgres` superuser credentials should never appear in any script or `.env` file.

---

## Usage Roadmap (long-term)

1. **Admin/owner** — first target, using Claude Desktop via HTTP/SSE
2. **Staff (CSRs, press operators)** — same MCP server, expand tool set
3. **Automated workflows** — event-driven triggers
4. **Customer-facing** — job status lookups (requires auth + scoped access)

---

## GitHub Setup

The repo should live on GitHub for backup, version history, and easy access from any session.

Steps (one-time, do before next working session):
1. Create a new **private** repo on GitHub (e.g. `rfrye/printsmith-mcp`)
2. Add it as a remote: `git remote add github git@github.com:rfrye/printsmith-mcp.git`
3. Push all branches: `git push github --all`
4. From then on push to both remotes, or set GitHub as the primary remote

The `.env` file is already in `.gitignore` (or should be verified) — credentials must never be committed.

---

## Notes

- `src/printsmith_client.py` is a legacy HTTP API client — not used, kept for reference
- Schema column names vary by PrintSmith installation — use `discover_schema` tool if queries break
- HTTP transport mode (`MCP_TRANSPORT=http`) is what Claude Desktop will use for remote LXC access
- SSE endpoint: `/sse`, health check: `/health`
- The `postgres` superuser password is the default (`postgres`) — change it or ensure firewall rules prevent external access
