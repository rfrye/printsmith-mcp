# PrintSmith MCP — Production Plan

> Created: 2026-03-17. Pick up from here next session.

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

## Information Still Needed (collect before Phase 1)

| Item | Status |
|------|--------|
| Proxmox host IP and intended CTID for new LXC | Not collected |
| PrintSmith Postgres host IP | Not collected |
| Postgres credentials currently used for the dump | Not collected |
| PrintSmith Postgres version (`SELECT version();`) | Not collected |
| LAN subnet (e.g. `192.168.1.0/24`) for pg_hba.conf | Not collected |

---

## Usage Roadmap (long-term)

1. **Admin/owner** — first target, using Claude Desktop via HTTP/SSE
2. **Staff (CSRs, press operators)** — same MCP server, expand tool set
3. **Automated workflows** — event-driven triggers
4. **Customer-facing** — job status lookups (requires auth + scoped access)

---

## Notes

- `src/printsmith_client.py` is a legacy HTTP API client — not used, kept for reference
- Schema column names vary by PrintSmith installation — use `discover_schema` tool if queries break
- HTTP transport mode (`MCP_TRANSPORT=http`) is what Claude Desktop will use for remote LXC access
- SSE endpoint: `/sse`, health check: `/health`
