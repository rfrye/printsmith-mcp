#!/usr/bin/env python3
"""
PrintSmith MCP Server
=====================
MCP server exposing PrintSmith Vision data to Claude via direct PostgreSQL connection.

Supports two transport modes:
- STDIO: For local Claude Desktop (default)
- HTTP/SSE: For remote access from LXC/Docker containers

Environment Variables:
    PG_HOST             - PostgreSQL host (required for live mode)
    PG_PORT             - PostgreSQL port (default: 5432)
    PG_DATABASE         - Database name (default: printsmith)
    PG_USER             - Database user (default: postgres)
    PG_PASSWORD         - Database password (required for live mode)
    PG_TIMEOUT          - Query timeout in seconds (default: 30)
    MCP_TRANSPORT       - Transport mode: "stdio" or "http" (default: stdio)
    MCP_HTTP_PORT       - HTTP port when using http transport (default: 8080)
    MCP_HTTP_HOST       - HTTP host binding (default: 0.0.0.0)
    USE_MOCK_DATA       - Use mock data instead of real DB (default: false)

Usage:
    # STDIO mode (local Claude Desktop)
    python server.py

    # HTTP mode (remote/LXC)
    MCP_TRANSPORT=http MCP_HTTP_PORT=8080 python server.py
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from pathlib import Path

# Auto-load .env from the project root (one level up from src/)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed — rely on shell environment

from mcp.server import Server
from mcp.types import Tool, TextContent, Resource

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("printsmith-mcp")


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Server configuration from environment variables."""

    # PostgreSQL connection
    PG_HOST = os.getenv("PG_HOST", "")
    PG_PORT = int(os.getenv("PG_PORT", "5432"))
    PG_DATABASE = os.getenv("PG_DATABASE", "printsmith")
    PG_USER = os.getenv("PG_USER", "postgres")
    PG_PASSWORD = os.getenv("PG_PASSWORD", "")
    PG_TIMEOUT = int(os.getenv("PG_TIMEOUT", "30"))

    # MCP transport
    MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")  # "stdio" or "http"
    MCP_HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "8080"))
    MCP_HTTP_HOST = os.getenv("MCP_HTTP_HOST", "0.0.0.0")

    # Development
    USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

    @classmethod
    def validate(cls):
        """Validate configuration and fall back to mock if DB not configured."""
        if not cls.USE_MOCK_DATA:
            if not cls.PG_HOST:
                logger.warning("PG_HOST not set — falling back to mock data")
                cls.USE_MOCK_DATA = True
            elif not cls.PG_PASSWORD:
                logger.warning("PG_PASSWORD not set — falling back to mock data")
                cls.USE_MOCK_DATA = True


# Validate config on import
Config.validate()


# =============================================================================
# MOCK DATA (for testing without a PrintSmith database)
# =============================================================================

MOCK_CUSTOMERS = {
    "1001": {
        "accountid": 1001,
        "accountnumber": "ACME-001",
        "name": "Acme Corporation",
        "contact": "John Smith",
        "email": "john@acme.com",
        "phone": "555-0101",
        "creditstatus": "good",
        "creditlimit": 10000,
        "balance": 2450.00,
        "accounttype": "charge",
        "salesrep": "Mike Johnson",
        "notes": "Prefers glossy stock. Rush jobs OK with 24hr notice."
    },
    "1002": {
        "accountid": 1002,
        "accountnumber": "DRTY-002",
        "name": "Downtown Realty",
        "contact": "Sarah Chen",
        "email": "sarah@downtownrealty.com",
        "phone": "555-0102",
        "creditstatus": "good",
        "creditlimit": 5000,
        "balance": 0,
        "accounttype": "charge",
        "salesrep": "Mike Johnson",
        "notes": "Monthly flyer order, usually 5000 qty."
    },
    "1003": {
        "accountid": 1003,
        "accountnumber": "QSS-003",
        "name": "Quick Start Startup",
        "contact": "Alex Rivera",
        "email": "alex@quickstart.io",
        "phone": "555-0103",
        "creditstatus": "new",
        "creditlimit": 1000,
        "balance": 750.00,
        "accounttype": "cod",
        "salesrep": "Lisa Park",
        "notes": "New customer. Interested in business cards and marketing materials."
    }
}

MOCK_INVOICES = {
    "J-2024-0156": {
        "invoiceid": 27230,
        "invoicenumber": "J-2024-0156",
        "accountid": 1001,
        "customer_name": "Acme Corporation",
        "description": "8.5x11 Brochures, Tri-fold, 4/4",
        "quantity": 2500,
        "status": "in_production",
        "station": "Press 2",
        "duedate": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"),
        "total": 1250.00,
        "paper": "100# Gloss Text",
        "createdate": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "specialinstructions": "Customer will pick up. Call when ready.",
        "takenby": "admin",
        "salesrep": "Mike Johnson"
    },
    "J-2024-0157": {
        "invoiceid": 27231,
        "invoicenumber": "J-2024-0157",
        "accountid": 1002,
        "customer_name": "Downtown Realty",
        "description": "Property Flyers, 8.5x11, 4/0",
        "quantity": 5000,
        "status": "ready_for_pickup",
        "station": "Bindery Complete",
        "duedate": datetime.now().strftime("%Y-%m-%d"),
        "total": 450.00,
        "paper": "80# Gloss Text",
        "createdate": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "specialinstructions": "",
        "takenby": "admin",
        "salesrep": "Mike Johnson"
    },
    "J-2024-0158": {
        "invoiceid": 27232,
        "invoicenumber": "J-2024-0158",
        "accountid": 1003,
        "customer_name": "Quick Start Startup",
        "description": "Business Cards, 2x3.5, 4/4",
        "quantity": 500,
        "status": "pending_approval",
        "station": "Prepress",
        "duedate": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
        "total": 125.00,
        "paper": "14pt C2S",
        "createdate": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "specialinstructions": "Waiting on customer proof approval",
        "takenby": "lisa",
        "salesrep": "Lisa Park"
    }
}

MOCK_ESTIMATES = {
    "E-2024-0089": {
        "estimateid": 5501,
        "estimatenumber": "E-2024-0089",
        "accountid": 1003,
        "customer_name": "Quick Start Startup",
        "description": "Promotional Postcards",
        "quantity": 2000,
        "status": "pending",
        "total": 385.00,
        "createdate": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "validuntil": (datetime.now() + timedelta(days=28)).strftime("%Y-%m-%d"),
        "takenby": "lisa",
        "salesrep": "Lisa Park"
    }
}


# =============================================================================
# DATABASE CLIENT (conditionally loaded)
# =============================================================================

_db_client = None


async def get_db():
    """Get or create the PrintSmith PostgreSQL client."""
    global _db_client

    if Config.USE_MOCK_DATA:
        return None

    if _db_client is None:
        from printsmith_db import PrintSmithDB, PrintSmithDBConfig

        config = PrintSmithDBConfig(
            host=Config.PG_HOST,
            port=Config.PG_PORT,
            database=Config.PG_DATABASE,
            user=Config.PG_USER,
            password=Config.PG_PASSWORD,
            timeout=Config.PG_TIMEOUT,
        )
        _db_client = PrintSmithDB(config)

    return _db_client


# =============================================================================
# MCP SERVER
# =============================================================================

server = Server("printsmith-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available PrintSmith tools (read-only operations)."""
    return [
        Tool(
            name="lookup_customer",
            description="Look up a customer/account by name, ID, or account number. Returns account details including contact info, credit status, balance, and notes. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Customer name, account ID, or account number to search for"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_job_status",
            description="Get the current status of an invoice/job including production location, due date, and special instructions. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_number": {
                        "type": "string",
                        "description": "The invoice/job number (e.g., J-2024-0156) or numeric invoice ID"
                    }
                },
                "required": ["job_number"]
            }
        ),
        Tool(
            name="list_jobs",
            description="List invoices/jobs filtered by status. Useful for seeing what's in production, ready for pickup, pending approval, etc. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: pending_approval, in_production, ready_for_pickup, completed, or 'all'",
                        "enum": ["all", "pending_approval", "in_production", "ready_for_pickup", "completed"]
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Optional: filter by customer name"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Optional: only show jobs from the last N days (default: 30)",
                        "default": 30
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_customer_jobs",
            description="Get all invoices/jobs (current and recent) for a specific customer. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "Customer name to search for"
                    }
                },
                "required": ["customer_name"]
            }
        ),
        Tool(
            name="get_ar_summary",
            description="Get accounts receivable summary showing customers with outstanding balances. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_balance": {
                        "type": "number",
                        "description": "Optional: minimum balance to include (default: 0)",
                        "default": 0
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_estimate",
            description="Get details of a specific estimate by estimate number or ID. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_number": {
                        "type": "string",
                        "description": "The estimate number (e.g., E-2024-0089) or numeric estimate ID"
                    }
                },
                "required": ["estimate_number"]
            }
        ),
        Tool(
            name="list_pending_estimates",
            description="List estimates that are pending (not yet converted to jobs). READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "Optional: filter by customer name"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="discover_schema",
            description="Discover the PrintSmith PostgreSQL schema — lists all tables and columns. Use this first if other tools return errors, to verify the actual column/table names in your installation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Optional: show columns for a specific table only (e.g., 'account', 'invoice')"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="sample_table",
            description="Return a few sample rows from any PrintSmith table. Useful for seeing actual data formats and verifying column names. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Table name to sample (e.g., 'account', 'invoice', 'estimate')"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of rows to return (default: 3, max: 10)",
                        "default": 3
                    }
                },
                "required": ["table_name"]
            }
        ),
        Tool(
            name="health_check",
            description="Check if the PrintSmith PostgreSQL connection is working. Returns connection status, database name, and PostgreSQL version.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls — all read-only operations."""

    db = await get_db()

    try:
        if name == "lookup_customer":
            return await _lookup_customer(db, arguments)
        elif name == "get_job_status":
            return await _get_job_status(db, arguments)
        elif name == "list_jobs":
            return await _list_jobs(db, arguments)
        elif name == "get_customer_jobs":
            return await _get_customer_jobs(db, arguments)
        elif name == "get_ar_summary":
            return await _get_ar_summary(db, arguments)
        elif name == "get_estimate":
            return await _get_estimate(db, arguments)
        elif name == "list_pending_estimates":
            return await _list_pending_estimates(db, arguments)
        elif name == "discover_schema":
            return await _discover_schema(db, arguments)
        elif name == "sample_table":
            return await _sample_table(db, arguments)
        elif name == "health_check":
            return await _health_check(db)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

async def _lookup_customer(db, arguments: dict) -> list[TextContent]:
    """Look up customer by name, ID, or account number."""
    query = arguments.get("query", "").strip()

    if not query:
        return [TextContent(type="text", text="Please provide a customer name or ID to search for.")]

    if Config.USE_MOCK_DATA:
        q = query.lower()
        results = []
        for cust in MOCK_CUSTOMERS.values():
            if (q in cust["name"].lower() or
                    q == str(cust["accountid"]) or
                    q == cust["accountnumber"].lower()):
                results.append(cust)
    else:
        try:
            results = []
            if query.isdigit():
                # Try by numeric ID
                row = await db.get_account(query)
                if row:
                    results = [row]
            if not results:
                # Try by account number exact match
                row = await db.get_account_by_number(query)
                if row:
                    results = [row]
            if not results:
                # Fall back to name search
                results = await db.search_accounts(name=query)
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not results:
        return [TextContent(type="text", text=f"No customers found matching '{query}'")]

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_job_status(db, arguments: dict) -> list[TextContent]:
    """Get status of a specific invoice/job."""
    job_number = arguments.get("job_number", "").strip()

    if not job_number:
        return [TextContent(type="text", text="Please provide a job/invoice number.")]

    if Config.USE_MOCK_DATA:
        invoice = MOCK_INVOICES.get(job_number.upper())
    else:
        try:
            if job_number.isdigit():
                invoice = await db.get_invoice(job_number)
            else:
                invoice = await db.get_invoice_by_number(job_number)
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not invoice:
        return [TextContent(type="text", text=f"Job/invoice '{job_number}' not found")]

    return [TextContent(type="text", text=json.dumps(invoice, indent=2, default=str))]


async def _list_jobs(db, arguments: dict) -> list[TextContent]:
    """List invoices/jobs with optional filters."""
    status_filter = arguments.get("status", "all")
    customer_filter = arguments.get("customer_name", "").lower()
    days_back = arguments.get("days_back", 30)

    if Config.USE_MOCK_DATA:
        results = []
        cutoff_date = datetime.now() - timedelta(days=days_back)

        for inv in MOCK_INVOICES.values():
            if status_filter != "all" and inv["status"] != status_filter:
                continue
            if customer_filter and customer_filter not in inv["customer_name"].lower():
                continue
            inv_date = datetime.strptime(inv["createdate"], "%Y-%m-%d")
            if inv_date < cutoff_date:
                continue
            results.append(inv)
    else:
        try:
            if status_filter != "all":
                results = await db.get_invoices_by_status(status_filter)
            else:
                start_date = datetime.now() - timedelta(days=days_back)
                results = await db.get_invoices_by_date_range(start_date)

            if customer_filter:
                results = [
                    r for r in results
                    if customer_filter in (r.get("customer_name") or r.get("name") or "").lower()
                ]
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not results:
        return [TextContent(type="text", text="No jobs/invoices found matching criteria")]

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_customer_jobs(db, arguments: dict) -> list[TextContent]:
    """Get all invoices for a customer."""
    customer_name = arguments.get("customer_name", "").strip()

    if not customer_name:
        return [TextContent(type="text", text="Please provide a customer name.")]

    if Config.USE_MOCK_DATA:
        results = [
            inv for inv in MOCK_INVOICES.values()
            if customer_name.lower() in inv["customer_name"].lower()
        ]
    else:
        try:
            customers = await db.search_accounts(name=customer_name)
            if not customers:
                return [TextContent(type="text", text=f"No customer found matching '{customer_name}'")]

            account_id = str(customers[0].get("accountid") or customers[0].get("account_id") or "")
            if not account_id:
                return [TextContent(type="text", text="Found customer but could not determine account ID")]

            results = await db.get_invoices_by_account(account_id)
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not results:
        return [TextContent(type="text", text=f"No jobs/invoices found for '{customer_name}'")]

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_ar_summary(db, arguments: dict) -> list[TextContent]:
    """Get accounts receivable summary."""
    min_balance = float(arguments.get("min_balance", 0))

    if Config.USE_MOCK_DATA:
        ar_data = []
        total = 0.0
        for cust in MOCK_CUSTOMERS.values():
            if cust["balance"] >= min_balance:
                ar_data.append({
                    "customer": cust["name"],
                    "account_number": cust["accountnumber"],
                    "balance": cust["balance"],
                    "credit_status": cust["creditstatus"],
                    "credit_limit": cust["creditlimit"]
                })
                total += cust["balance"]
    else:
        try:
            rows = await db.get_accounts_with_balance(min_balance)
            ar_data = []
            total = 0.0
            for row in rows:
                balance = float(row.get("balance") or 0)
                ar_data.append({
                    "customer": row.get("name"),
                    "account_number": row.get("accountnumber"),
                    "balance": balance,
                    "credit_status": row.get("creditstatus"),
                    "credit_limit": row.get("creditlimit"),
                })
                total += balance
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    summary = {
        "total_outstanding": round(total, 2),
        "accounts_with_balance": len(ar_data),
        "details": sorted(ar_data, key=lambda x: x["balance"], reverse=True)
    }

    return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]


async def _get_estimate(db, arguments: dict) -> list[TextContent]:
    """Get a specific estimate."""
    estimate_ref = arguments.get("estimate_number", "").strip()

    if not estimate_ref:
        return [TextContent(type="text", text="Please provide an estimate number.")]

    if Config.USE_MOCK_DATA:
        estimate = MOCK_ESTIMATES.get(estimate_ref.upper())
    else:
        try:
            estimate = await db.get_estimate(estimate_ref)
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not estimate:
        return [TextContent(type="text", text=f"Estimate '{estimate_ref}' not found")]

    return [TextContent(type="text", text=json.dumps(estimate, indent=2, default=str))]


async def _list_pending_estimates(db, arguments: dict) -> list[TextContent]:
    """List pending estimates."""
    customer_filter = arguments.get("customer_name", "").lower()

    if Config.USE_MOCK_DATA:
        results = [e for e in MOCK_ESTIMATES.values() if e["status"] == "pending"]
        if customer_filter:
            results = [e for e in results if customer_filter in e["customer_name"].lower()]
    else:
        try:
            start_date = datetime.now() - timedelta(days=90)
            results = await db.get_estimates_by_date_range(start_date)
            results = [e for e in results if str(e.get("status", "")).lower() == "pending"]
            if customer_filter:
                results = [
                    e for e in results
                    if customer_filter in (e.get("customer_name") or e.get("name") or "").lower()
                ]
        except Exception as e:
            return [TextContent(type="text", text=f"Database error: {str(e)}")]

    if not results:
        return [TextContent(type="text", text="No pending estimates found")]

    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _discover_schema(db, arguments: dict) -> list[TextContent]:
    """Discover the PrintSmith PostgreSQL schema."""
    table_filter = arguments.get("table_name", "").strip().lower()

    if Config.USE_MOCK_DATA:
        result = {
            "mode": "mock_data",
            "message": "Schema discovery is only available in live database mode.",
            "mock_tables": ["account", "invoice", "estimate"]
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    try:
        schema = await db.discover_schema()
        if table_filter:
            matching = {k: v for k, v in schema.items() if table_filter in k.lower()}
            if not matching:
                return [TextContent(type="text", text=f"No tables matching '{table_filter}' found.\nAll tables: {', '.join(sorted(schema.keys()))}")]
            return [TextContent(type="text", text=json.dumps(matching, indent=2))]
        else:
            # Return table list with column counts to avoid huge output
            summary = {
                "table_count": len(schema),
                "tables": {
                    tname: {
                        "column_count": len(cols),
                        "columns": [c["column"] for c in cols]
                    }
                    for tname, cols in sorted(schema.items())
                }
            }
            return [TextContent(type="text", text=json.dumps(summary, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=f"Database error: {str(e)}")]


async def _sample_table(db, arguments: dict) -> list[TextContent]:
    """Return sample rows from a table."""
    table_name = arguments.get("table_name", "").strip()
    limit = min(int(arguments.get("limit", 3)), 10)  # cap at 10

    if not table_name:
        return [TextContent(type="text", text="Please provide a table name.")]

    if Config.USE_MOCK_DATA:
        return [TextContent(type="text", text="sample_table is only available in live database mode.")]

    try:
        rows = await db.sample_table(table_name, limit)
        if not rows:
            return [TextContent(type="text", text=f"Table '{table_name}' is empty or does not exist.")]
        return [TextContent(type="text", text=json.dumps(rows, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=f"Database error: {str(e)}")]


async def _health_check(db) -> list[TextContent]:
    """Check PrintSmith database connection health."""
    if Config.USE_MOCK_DATA:
        result = {
            "status": "healthy",
            "mode": "mock_data",
            "message": "Using mock data — no PostgreSQL connection configured"
        }
    else:
        try:
            result = await db.health_check()
            result["mode"] = "live_postgres"
        except Exception as e:
            result = {
                "status": "unhealthy",
                "mode": "live_postgres",
                "message": str(e)
            }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# =============================================================================
# RESOURCES
# =============================================================================

@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available resources."""
    return [
        Resource(
            uri="printsmith://status",
            name="Server Status",
            description="Current server configuration and connection status",
            mimeType="application/json"
        )
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a resource."""
    if uri == "printsmith://status":
        return json.dumps({
            "mode": "mock_data" if Config.USE_MOCK_DATA else "live_postgres",
            "pg_host": Config.PG_HOST if not Config.USE_MOCK_DATA else None,
            "pg_database": Config.PG_DATABASE if not Config.USE_MOCK_DATA else None,
            "transport": Config.MCP_TRANSPORT,
            "tools_available": 10,
            "read_only": True
        }, indent=2)
    else:
        raise ValueError(f"Unknown resource: {uri}")


# =============================================================================
# MAIN — Transport Selection
# =============================================================================

async def run_stdio():
    """Run server with STDIO transport (for local Claude Desktop)."""
    from mcp.server.stdio import stdio_server

    logger.info("Starting PrintSmith MCP server (STDIO transport)")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


async def run_http():
    """Run server with HTTP/SSE transport (for remote/LXC access)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    import uvicorn

    logger.info(
        f"Starting PrintSmith MCP server "
        f"(HTTP transport on {Config.MCP_HTTP_HOST}:{Config.MCP_HTTP_PORT})"
    )

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options()
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    async def health(request):
        return JSONResponse({"status": "ok", "server": "printsmith-mcp"})

    app = Starlette(
        routes=[
            Route("/health", health),
            Route("/sse", handle_sse),
            Route("/messages", handle_messages, methods=["POST"]),
        ]
    )

    config = uvicorn.Config(
        app,
        host=Config.MCP_HTTP_HOST,
        port=Config.MCP_HTTP_PORT,
        log_level="info"
    )
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


async def main():
    """Main entry point — select transport based on MCP_TRANSPORT env var."""
    if Config.MCP_TRANSPORT == "http":
        await run_http()
    else:
        await run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
