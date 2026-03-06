"""
PrintSmith Vision - Direct PostgreSQL Client
=============================================
Connects directly to the PrintSmith Vision PostgreSQL database.
All operations are READ-ONLY (SELECT statements only).

PrintSmith Vision Database Notes:
- Default DB name: printsmith (may vary by installation)
- Default port: 5432
- This client was built against the most common PrintSmith Vision schema.
  If queries fail, use discover_schema() to inspect your actual table/column
  names and report them so the queries can be adjusted.

Common schema variations to watch for:
  - accountid  vs  account_id
  - invoiceid  vs  invoice_id
  - createdate vs  create_date  vs  created_date
  - duedate    vs  due_date
"""

import asyncpg
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PrintSmithDBConfig:
    """Configuration for direct PostgreSQL connection."""
    host: str               # e.g., "192.168.1.100" or "printsmith-server"
    port: int = 5432
    database: str = "printsmith"
    user: str = "postgres"
    password: str = ""
    min_connections: int = 1
    max_connections: int = 5
    timeout: int = 30


class PrintSmithDBError(Exception):
    """Raised when a database operation fails."""
    pass


class PrintSmithDB:
    """
    Read-only direct PostgreSQL client for PrintSmith Vision.
    All methods execute SELECT statements only — no INSERT/UPDATE/DELETE.
    """

    def __init__(self, config: PrintSmithDBConfig):
        self.config = config
        self._pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the async connection pool."""
        if self._pool is None or self._pool._closed:
            try:
                self._pool = await asyncpg.create_pool(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.user,
                    password=self.config.password,
                    min_size=self.config.min_connections,
                    max_size=self.config.max_connections,
                    command_timeout=self.config.timeout,
                )
            except Exception as e:
                raise PrintSmithDBError(f"Failed to connect to PostgreSQL at {self.config.host}:{self.config.port}/{self.config.database}: {e}")
        return self._pool

    async def close(self):
        """Close the connection pool."""
        if self._pool and not self._pool._closed:
            await self._pool.close()

    async def _fetch(self, query: str, *args) -> list[dict]:
        """Execute a SELECT and return list of row dicts."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            try:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]
            except asyncpg.PostgresError as e:
                raise PrintSmithDBError(f"Query failed: {e}\nQuery: {query[:200]}")

    async def _fetchrow(self, query: str, *args) -> Optional[dict]:
        """Execute a SELECT and return a single row dict (or None)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(query, *args)
                return dict(row) if row else None
            except asyncpg.PostgresError as e:
                raise PrintSmithDBError(f"Query failed: {e}\nQuery: {query[:200]}")

    # =========================================================================
    # SCHEMA DISCOVERY — Use these if queries fail to find correct column names
    # =========================================================================

    async def discover_schema(self) -> dict:
        """
        List all public tables and their columns.
        Use this to verify table/column names for your PrintSmith version.
        """
        tables = await self._fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)

        schema = {}
        for t in tables:
            tname = t['table_name']
            cols = await self._fetch("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
            """, tname)
            schema[tname] = [
                {
                    'column': c['column_name'],
                    'type': c['data_type'],
                    'nullable': c['is_nullable'] == 'YES'
                }
                for c in cols
            ]
        return schema

    async def sample_table(self, table_name: str, limit: int = 3) -> list[dict]:
        """
        Return sample rows from a table.
        Useful for discovering actual column names and data formats.
        Safety: only alphanumeric/underscore table names are accepted.
        """
        if not all(c.isalnum() or c == '_' for c in table_name):
            raise PrintSmithDBError(f"Invalid table name: '{table_name}'")
        rows = await self._fetch(f'SELECT * FROM "{table_name}" LIMIT $1', limit)
        return rows

    async def run_readonly_query(self, sql: str) -> list[dict]:
        """
        Run an arbitrary read-only SQL query.
        Only SELECT statements are permitted.
        """
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
            raise PrintSmithDBError("Only SELECT statements are allowed.")
        return await self._fetch(sql)

    # =========================================================================
    # ACCOUNT / CUSTOMER OPERATIONS
    # =========================================================================

    async def get_account(self, account_id: str) -> Optional[dict]:
        """Get a single account/customer by primary key."""
        try:
            pk = int(account_id)
        except ValueError:
            raise PrintSmithDBError(f"account_id must be numeric, got: '{account_id}'")

        return await self._fetchrow("""
            SELECT *
            FROM account
            WHERE accountid = $1
        """, pk)

    async def get_account_by_number(self, account_number: str) -> Optional[dict]:
        """Get account by the display account number."""
        return await self._fetchrow("""
            SELECT *
            FROM account
            WHERE accountnumber = $1
        """, account_number)

    async def search_accounts(self, name: str = None, limit: int = 50) -> list[dict]:
        """Search accounts by name (case-insensitive partial match)."""
        if name:
            return await self._fetch("""
                SELECT *
                FROM account
                WHERE LOWER(name) LIKE LOWER($1)
                ORDER BY name
                LIMIT $2
            """, f"%{name}%", limit)
        else:
            return await self._fetch("""
                SELECT *
                FROM account
                ORDER BY name
                LIMIT $1
            """, limit)

    async def get_accounts_with_balance(self, min_balance: float = 0.0) -> list[dict]:
        """Get accounts with an AR balance at or above min_balance."""
        return await self._fetch("""
            SELECT
                accountid,
                name,
                accountnumber,
                balance,
                creditstatus,
                creditlimit
            FROM account
            WHERE balance >= $1
            ORDER BY balance DESC
        """, min_balance)

    # =========================================================================
    # INVOICE / JOB OPERATIONS
    # =========================================================================

    async def get_invoice(self, invoice_id: str) -> Optional[dict]:
        """Get invoice by numeric ID."""
        try:
            pk = int(invoice_id)
        except ValueError:
            raise PrintSmithDBError(f"invoice_id must be numeric, got: '{invoice_id}'")

        return await self._fetchrow("""
            SELECT i.*, a.name AS customer_name
            FROM invoice i
            LEFT JOIN account a ON i.accountid = a.accountid
            WHERE i.invoiceid = $1
        """, pk)

    async def get_invoice_by_number(self, invoice_number: str) -> Optional[dict]:
        """Get invoice by invoice/job number."""
        return await self._fetchrow("""
            SELECT i.*, a.name AS customer_name
            FROM invoice i
            LEFT JOIN account a ON i.accountid = a.accountid
            WHERE i.invoicenumber = $1
        """, invoice_number)

    async def get_invoices_by_account(self, account_id: str) -> list[dict]:
        """Get all invoices for a specific account (most recent first)."""
        try:
            pk = int(account_id)
        except ValueError:
            raise PrintSmithDBError(f"account_id must be numeric, got: '{account_id}'")

        return await self._fetch("""
            SELECT i.*, a.name AS customer_name
            FROM invoice i
            LEFT JOIN account a ON i.accountid = a.accountid
            WHERE i.accountid = $1
            ORDER BY i.createdate DESC
            LIMIT 100
        """, pk)

    async def get_invoices_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime = None
    ) -> list[dict]:
        """Get invoices created within a date range."""
        if end_date is None:
            end_date = datetime.now()

        return await self._fetch("""
            SELECT i.*, a.name AS customer_name
            FROM invoice i
            LEFT JOIN account a ON i.accountid = a.accountid
            WHERE i.createdate BETWEEN $1 AND $2
            ORDER BY i.createdate DESC
        """, start_date, end_date)

    async def get_invoices_by_status(self, status: str) -> list[dict]:
        """Get invoices filtered by status string."""
        return await self._fetch("""
            SELECT i.*, a.name AS customer_name
            FROM invoice i
            LEFT JOIN account a ON i.accountid = a.accountid
            WHERE LOWER(i.status) = LOWER($1)
            ORDER BY i.duedate ASC
        """, status)

    # =========================================================================
    # ESTIMATE OPERATIONS
    # =========================================================================

    async def get_estimate(self, estimate_ref: str) -> Optional[dict]:
        """Get estimate by estimate number or numeric ID."""
        # Try by estimate number first (the user-facing value)
        row = await self._fetchrow("""
            SELECT e.*, a.name AS customer_name
            FROM estimate e
            LEFT JOIN account a ON e.accountid = a.accountid
            WHERE e.estimatenumber = $1
        """, estimate_ref)

        if row is None and estimate_ref.isdigit():
            row = await self._fetchrow("""
                SELECT e.*, a.name AS customer_name
                FROM estimate e
                LEFT JOIN account a ON e.accountid = a.accountid
                WHERE e.estimateid = $1
            """, int(estimate_ref))

        return row

    async def get_estimates_by_account(self, account_id: str) -> list[dict]:
        """Get all estimates for a specific account."""
        try:
            pk = int(account_id)
        except ValueError:
            raise PrintSmithDBError(f"account_id must be numeric, got: '{account_id}'")

        return await self._fetch("""
            SELECT e.*, a.name AS customer_name
            FROM estimate e
            LEFT JOIN account a ON e.accountid = a.accountid
            WHERE e.accountid = $1
            ORDER BY e.createdate DESC
        """, pk)

    async def get_estimates_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime = None
    ) -> list[dict]:
        """Get estimates created within a date range."""
        if end_date is None:
            end_date = datetime.now()

        return await self._fetch("""
            SELECT e.*, a.name AS customer_name
            FROM estimate e
            LEFT JOIN account a ON e.accountid = a.accountid
            WHERE e.createdate BETWEEN $1 AND $2
            ORDER BY e.createdate DESC
        """, start_date, end_date)

    # =========================================================================
    # CONTACT OPERATIONS
    # =========================================================================

    async def get_contacts_by_account(self, account_id: str) -> list[dict]:
        """Get all contacts for an account."""
        try:
            pk = int(account_id)
        except ValueError:
            raise PrintSmithDBError(f"account_id must be numeric, got: '{account_id}'")

        return await self._fetch("""
            SELECT *
            FROM contact
            WHERE accountid = $1
            ORDER BY name
        """, pk)

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    async def health_check(self) -> dict:
        """Check if the PostgreSQL connection is working."""
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                pg_version = await conn.fetchval("SELECT version()")
                db_name = await conn.fetchval("SELECT current_database()")
                table_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                )
            return {
                "status": "healthy",
                "database": db_name,
                "host": self.config.host,
                "port": self.config.port,
                "postgres_version": pg_version,
                "public_table_count": int(table_count),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "host": self.config.host,
                "port": self.config.port,
            }
