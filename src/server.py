#!/usr/bin/env python3
"""
PrintSmith MCP Server
=====================
MCP server exposing PrintSmith Vision functionality to Claude.

Supports two transport modes:
- STDIO: For local Claude Desktop (default)
- HTTP/SSE: For remote access from LXC/Docker containers

Environment Variables:
    PRINTSMITH_BASE_URL     - PrintSmith server URL (required for live mode)
    PRINTSMITH_API_TOKEN    - API token (required for live mode)
    PRINTSMITH_VERIFY_SSL   - Verify SSL certificates (default: true)
    MCP_TRANSPORT           - Transport mode: "stdio" or "http" (default: stdio)
    MCP_HTTP_PORT           - HTTP port when using http transport (default: 8080)
    MCP_HTTP_HOST           - HTTP host binding (default: 0.0.0.0)
    USE_MOCK_DATA           - Use mock data instead of real API (default: false)

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
    
    # PrintSmith connection
    PRINTSMITH_BASE_URL = os.getenv("PRINTSMITH_BASE_URL", "")
    PRINTSMITH_API_TOKEN = os.getenv("PRINTSMITH_API_TOKEN", "")
    PRINTSMITH_VERIFY_SSL = os.getenv("PRINTSMITH_VERIFY_SSL", "true").lower() == "true"
    PRINTSMITH_TIMEOUT = int(os.getenv("PRINTSMITH_TIMEOUT", "30"))
    
    # MCP transport
    MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")  # "stdio" or "http"
    MCP_HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "8080"))
    MCP_HTTP_HOST = os.getenv("MCP_HTTP_HOST", "0.0.0.0")
    
    # Development
    USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"
    
    @classmethod
    def validate(cls):
        """Validate configuration."""
        if not cls.USE_MOCK_DATA:
            if not cls.PRINTSMITH_BASE_URL:
                logger.warning("PRINTSMITH_BASE_URL not set - falling back to mock data")
                cls.USE_MOCK_DATA = True
            elif not cls.PRINTSMITH_API_TOKEN:
                logger.warning("PRINTSMITH_API_TOKEN not set - falling back to mock data")
                cls.USE_MOCK_DATA = True


# Validate config on import
Config.validate()


# =============================================================================
# MOCK DATA (for testing without PrintSmith)
# =============================================================================

MOCK_CUSTOMERS = {
    "1001": {
        "id": "1001",
        "account_number": "ACME-001",
        "name": "Acme Corporation",
        "contact": "John Smith",
        "email": "john@acme.com",
        "phone": "555-0101",
        "credit_status": "good",
        "credit_limit": 10000,
        "balance": 2450.00,
        "account_type": "charge",
        "sales_rep": "Mike Johnson",
        "addresses": [
            {"type": "billing", "address": "123 Main St, Suite 100, Springfield, IL 62701"}
        ],
        "notes": "Prefers glossy stock. Rush jobs OK with 24hr notice."
    },
    "1002": {
        "id": "1002",
        "account_number": "DRTY-002", 
        "name": "Downtown Realty",
        "contact": "Sarah Chen",
        "email": "sarah@downtownrealty.com",
        "phone": "555-0102",
        "credit_status": "good",
        "credit_limit": 5000,
        "balance": 0,
        "account_type": "charge",
        "sales_rep": "Mike Johnson",
        "addresses": [
            {"type": "billing", "address": "456 Oak Ave, Downtown, Springfield, IL 62702"}
        ],
        "notes": "Monthly flyer order, usually 5000 qty."
    },
    "1003": {
        "id": "1003",
        "account_number": "QSS-003",
        "name": "Quick Start Startup",
        "contact": "Alex Rivera",
        "email": "alex@quickstart.io",
        "phone": "555-0103",
        "credit_status": "new",
        "credit_limit": 1000,
        "balance": 750.00,
        "account_type": "cod",
        "sales_rep": "Lisa Park",
        "addresses": [],
        "notes": "New customer. Interested in business cards and marketing materials."
    }
}

MOCK_JOBS = {
    "J-2024-0156": {
        "job_id": "27230",
        "job_number": "J-2024-0156",
        "invoice_number": "INV-2024-0892",
        "account_id": "1001",
        "customer_name": "Acme Corporation",
        "description": "8.5x11 Brochures, Tri-fold, 4/4",
        "quantity": 2500,
        "status": "in_production",
        "station": "Press 2",
        "due_date": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"),
        "price": 1250.00,
        "paper": "100# Gloss Text",
        "created_date": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
        "special_instructions": "Customer will pick up. Call when ready.",
        "taken_by": "admin",
        "sales_rep": "Mike Johnson"
    },
    "J-2024-0157": {
        "job_id": "27231",
        "job_number": "J-2024-0157",
        "invoice_number": "INV-2024-0893",
        "account_id": "1002",
        "customer_name": "Downtown Realty",
        "description": "Property Flyers, 8.5x11, 4/0",
        "quantity": 5000,
        "status": "ready_for_pickup",
        "station": "Bindery Complete",
        "due_date": datetime.now().strftime("%Y-%m-%d"),
        "price": 450.00,
        "paper": "80# Gloss Text",
        "created_date": (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d"),
        "special_instructions": "",
        "taken_by": "admin",
        "sales_rep": "Mike Johnson"
    },
    "J-2024-0158": {
        "job_id": "27232",
        "job_number": "J-2024-0158",
        "invoice_number": None,
        "account_id": "1003",
        "customer_name": "Quick Start Startup",
        "description": "Business Cards, 2x3.5, 4/4",
        "quantity": 500,
        "status": "pending_approval",
        "station": "Prepress",
        "due_date": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
        "price": 125.00,
        "paper": "14pt C2S",
        "created_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "special_instructions": "Waiting on customer proof approval",
        "taken_by": "lisa",
        "sales_rep": "Lisa Park"
    }
}

MOCK_ESTIMATES = {
    "E-2024-0089": {
        "estimate_id": "5501",
        "estimate_number": "E-2024-0089",
        "account_id": "1003",
        "customer_name": "Quick Start Startup",
        "description": "Promotional Postcards",
        "quantity": 2000,
        "status": "pending",
        "price": 385.00,
        "created_date": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d"),
        "valid_until": (datetime.now() + timedelta(days=28)).strftime("%Y-%m-%d"),
        "taken_by": "lisa",
        "sales_rep": "Lisa Park"
    }
}


# =============================================================================
# PRINTSMITH API CLIENT (conditionally loaded)
# =============================================================================

_ps_client = None

async def get_printsmith_client():
    """Get or create the PrintSmith API client."""
    global _ps_client
    
    if Config.USE_MOCK_DATA:
        return None
    
    if _ps_client is None:
        from printsmith_client import PrintSmithClient, PrintSmithConfig
        
        config = PrintSmithConfig(
            base_url=Config.PRINTSMITH_BASE_URL,
            api_token=Config.PRINTSMITH_API_TOKEN,
            timeout=Config.PRINTSMITH_TIMEOUT,
            verify_ssl=Config.PRINTSMITH_VERIFY_SSL
        )
        _ps_client = PrintSmithClient(config)
    
    return _ps_client


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
            description="Get the current status of a print job including production location, due date, and special instructions. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_number": {
                        "type": "string",
                        "description": "The job number (e.g., J-2024-0156)"
                    }
                },
                "required": ["job_number"]
            }
        ),
        Tool(
            name="list_jobs",
            description="List jobs filtered by status. Useful for seeing what's in production, ready for pickup, pending approval, etc. READ-ONLY.",
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
            description="Get all jobs (current and recent) for a specific customer. READ-ONLY.",
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
            description="Get details of a specific estimate by estimate number. READ-ONLY.",
            inputSchema={
                "type": "object",
                "properties": {
                    "estimate_number": {
                        "type": "string",
                        "description": "The estimate number (e.g., E-2024-0089)"
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
            name="health_check",
            description="Check if the PrintSmith connection is working. Returns connection status and any errors.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls - all read-only operations."""
    
    client = await get_printsmith_client()
    
    try:
        if name == "lookup_customer":
            return await _lookup_customer(client, arguments)
        elif name == "get_job_status":
            return await _get_job_status(client, arguments)
        elif name == "list_jobs":
            return await _list_jobs(client, arguments)
        elif name == "get_customer_jobs":
            return await _get_customer_jobs(client, arguments)
        elif name == "get_ar_summary":
            return await _get_ar_summary(client, arguments)
        elif name == "get_estimate":
            return await _get_estimate(client, arguments)
        elif name == "list_pending_estimates":
            return await _list_pending_estimates(client, arguments)
        elif name == "health_check":
            return await _health_check(client)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

async def _lookup_customer(client, arguments: dict) -> list[TextContent]:
    """Look up customer by name or ID."""
    query = arguments.get("query", "").lower().strip()
    
    if not query:
        return [TextContent(type="text", text="Please provide a customer name or ID to search for.")]
    
    if Config.USE_MOCK_DATA:
        results = []
        for cust in MOCK_CUSTOMERS.values():
            if (query in cust["name"].lower() or 
                query == cust["id"] or 
                query == cust["account_number"].lower()):
                results.append(cust)
    else:
        # Use real API
        try:
            # Try by account_id first
            if query.isdigit():
                result = await client.get_account(query)
                results = [result] if result else []
            else:
                results = await client.search_accounts(name=query)
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not results:
        return [TextContent(type="text", text=f"No customers found matching '{arguments.get('query')}'")]
    
    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_job_status(client, arguments: dict) -> list[TextContent]:
    """Get status of a specific job."""
    job_number = arguments.get("job_number", "").upper().strip()
    
    if not job_number:
        return [TextContent(type="text", text="Please provide a job number.")]
    
    if Config.USE_MOCK_DATA:
        job = MOCK_JOBS.get(job_number)
    else:
        try:
            job = await client.get_job(job_number)
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not job:
        return [TextContent(type="text", text=f"Job {job_number} not found")]
    
    return [TextContent(type="text", text=json.dumps(job, indent=2, default=str))]


async def _list_jobs(client, arguments: dict) -> list[TextContent]:
    """List jobs with optional filters."""
    status_filter = arguments.get("status", "all")
    customer_filter = arguments.get("customer_name", "").lower()
    days_back = arguments.get("days_back", 30)
    
    if Config.USE_MOCK_DATA:
        results = []
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        for job in MOCK_JOBS.values():
            # Status filter
            if status_filter != "all" and job["status"] != status_filter:
                continue
            # Customer filter
            if customer_filter and customer_filter not in job["customer_name"].lower():
                continue
            # Date filter
            job_date = datetime.strptime(job["created_date"], "%Y-%m-%d")
            if job_date < cutoff_date:
                continue
            results.append(job)
    else:
        try:
            if status_filter != "all":
                results = await client.get_jobs_by_status(status_filter)
            else:
                start_date = datetime.now() - timedelta(days=days_back)
                results = await client.get_jobs_by_date_range(start_date)
            
            # Apply customer filter if specified
            if customer_filter:
                results = [j for j in results if customer_filter in j.get("customer_name", "").lower()]
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not results:
        return [TextContent(type="text", text="No jobs found matching criteria")]
    
    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_customer_jobs(client, arguments: dict) -> list[TextContent]:
    """Get all jobs for a customer."""
    customer_name = arguments.get("customer_name", "").lower()
    
    if not customer_name:
        return [TextContent(type="text", text="Please provide a customer name.")]
    
    if Config.USE_MOCK_DATA:
        results = [j for j in MOCK_JOBS.values() if customer_name in j["customer_name"].lower()]
    else:
        try:
            # First find the customer
            customers = await client.search_accounts(name=customer_name)
            if not customers:
                return [TextContent(type="text", text=f"No customer found matching '{arguments.get('customer_name')}'")]
            
            account_id = customers[0].get("id") or customers[0].get("account_id")
            results = await client.get_invoices_by_account(account_id)
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not results:
        return [TextContent(type="text", text=f"No jobs found for customer '{arguments.get('customer_name')}'")]
    
    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _get_ar_summary(client, arguments: dict) -> list[TextContent]:
    """Get accounts receivable summary."""
    min_balance = arguments.get("min_balance", 0)
    
    if Config.USE_MOCK_DATA:
        ar_data = []
        total = 0
        for cust in MOCK_CUSTOMERS.values():
            if cust["balance"] >= min_balance:
                ar_data.append({
                    "customer": cust["name"],
                    "account_number": cust["account_number"],
                    "balance": cust["balance"],
                    "credit_status": cust["credit_status"],
                    "credit_limit": cust["credit_limit"]
                })
                total += cust["balance"]
    else:
        # Note: Real implementation would need AR-specific endpoint
        # This is a placeholder showing the expected structure
        try:
            customers = await client.search_accounts(limit=100)
            ar_data = []
            total = 0
            for cust in customers:
                balance = cust.get("balance", 0)
                if balance >= min_balance:
                    ar_data.append({
                        "customer": cust.get("name"),
                        "account_number": cust.get("account_number"),
                        "balance": balance,
                        "credit_status": cust.get("credit_status"),
                        "credit_limit": cust.get("credit_limit")
                    })
                    total += balance
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    summary = {
        "total_outstanding": total,
        "accounts_with_balance": len(ar_data),
        "details": sorted(ar_data, key=lambda x: x["balance"], reverse=True)
    }
    
    return [TextContent(type="text", text=json.dumps(summary, indent=2, default=str))]


async def _get_estimate(client, arguments: dict) -> list[TextContent]:
    """Get a specific estimate."""
    estimate_number = arguments.get("estimate_number", "").upper().strip()
    
    if not estimate_number:
        return [TextContent(type="text", text="Please provide an estimate number.")]
    
    if Config.USE_MOCK_DATA:
        estimate = MOCK_ESTIMATES.get(estimate_number)
    else:
        try:
            estimate = await client.get_estimate(estimate_number)
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not estimate:
        return [TextContent(type="text", text=f"Estimate {estimate_number} not found")]
    
    return [TextContent(type="text", text=json.dumps(estimate, indent=2, default=str))]


async def _list_pending_estimates(client, arguments: dict) -> list[TextContent]:
    """List pending estimates."""
    customer_filter = arguments.get("customer_name", "").lower()
    
    if Config.USE_MOCK_DATA:
        results = [e for e in MOCK_ESTIMATES.values() if e["status"] == "pending"]
        if customer_filter:
            results = [e for e in results if customer_filter in e["customer_name"].lower()]
    else:
        try:
            start_date = datetime.now() - timedelta(days=90)
            results = await client.get_estimates_by_date_range(start_date)
            results = [e for e in results if e.get("status") == "pending"]
            if customer_filter:
                results = [e for e in results if customer_filter in e.get("customer_name", "").lower()]
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {str(e)}")]
    
    if not results:
        return [TextContent(type="text", text="No pending estimates found")]
    
    return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]


async def _health_check(client) -> list[TextContent]:
    """Check PrintSmith connection health."""
    if Config.USE_MOCK_DATA:
        result = {
            "status": "healthy",
            "mode": "mock_data",
            "message": "Using mock data - no PrintSmith connection configured"
        }
    else:
        try:
            result = await client.health_check()
            result["mode"] = "live"
            result["base_url"] = Config.PRINTSMITH_BASE_URL
        except Exception as e:
            result = {
                "status": "unhealthy",
                "mode": "live",
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
            "mode": "mock_data" if Config.USE_MOCK_DATA else "live",
            "printsmith_url": Config.PRINTSMITH_BASE_URL if not Config.USE_MOCK_DATA else None,
            "transport": Config.MCP_TRANSPORT,
            "tools_available": 8,
            "read_only": True
        }, indent=2)
    else:
        raise ValueError(f"Unknown resource: {uri}")


# =============================================================================
# MAIN - Transport Selection
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
    """Run server with HTTP/SSE transport (for remote access)."""
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    import uvicorn
    
    logger.info(f"Starting PrintSmith MCP server (HTTP transport on {Config.MCP_HTTP_HOST}:{Config.MCP_HTTP_PORT})")
    
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
    """Main entry point."""
    if Config.MCP_TRANSPORT == "http":
        await run_http()
    else:
        await run_stdio()


if __name__ == "__main__":
    asyncio.run(main())
