"""
PrintSmith Vision API Client - READ-ONLY
=========================================
This client wraps the PrintSmith Vision E-Commerce Integration API.
All operations are read-only (GET requests only).

PrintSmith API Documentation:
- Uses HTTP/HTTPS with JSON payloads
- Authentication via API token in URL path
- Base pattern: /{Resource}API/{API_TOKEN} or /{Resource}/{API_TOKEN}

To get your API token:
1. Log into PrintSmith Vision as admin
2. Go to Setup > Preferences > API Settings
3. Generate or copy your API token
"""

import httpx
from typing import Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class PrintSmithConfig:
    """Configuration for PrintSmith API connection."""
    base_url: str  # e.g., "https://your-printsmith-server.com" or "http://192.168.1.100:8080"
    api_token: str
    timeout: int = 30
    verify_ssl: bool = True
    
    def __post_init__(self):
        # Remove trailing slash from base_url
        self.base_url = self.base_url.rstrip("/")


class PrintSmithAPIError(Exception):
    """Raised when PrintSmith API returns an error."""
    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(self.message)


class PrintSmithClient:
    """
    Read-only client for PrintSmith Vision API.
    
    All methods perform GET requests only - no data modification.
    """
    
    def __init__(self, config: PrintSmithConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                verify=self.config.verify_ssl,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                }
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def _get(self, endpoint: str, params: dict = None) -> dict:
        """
        Make a GET request to PrintSmith API.
        
        Args:
            endpoint: API endpoint (e.g., "/AccountAPI")
            params: Optional query parameters
            
        Returns:
            JSON response as dict
        """
        client = await self._get_client()
        url = f"{self.config.base_url}{endpoint}/{self.config.api_token}"
        
        logger.debug(f"GET {url} params={params}")
        
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise PrintSmithAPIError(
                f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
                response_body=e.response.text
            )
        except httpx.RequestError as e:
            raise PrintSmithAPIError(f"Request failed: {str(e)}")
        except Exception as e:
            raise PrintSmithAPIError(f"Unexpected error: {str(e)}")

    # =========================================================================
    # ACCOUNT / CUSTOMER OPERATIONS (Read-Only)
    # =========================================================================
    
    async def get_account(self, account_id: str) -> dict:
        """
        Get a single account/customer by ID.
        
        Args:
            account_id: The PrintSmith account ID (primary key)
            
        Returns:
            Account details dict
        """
        result = await self._get("/AccountAPI", params={"account_id": account_id})
        return result
    
    async def get_account_by_number(self, account_number: str) -> dict:
        """
        Get a single account/customer by account number.
        
        Args:
            account_number: The PrintSmith account number (display number)
            
        Returns:
            Account details dict
        """
        result = await self._get("/AccountAPI", params={"account_account_id": account_number})
        return result
    
    async def search_accounts(self, name: str = None, limit: int = 50) -> list[dict]:
        """
        Search accounts by name.
        
        Note: PrintSmith API may not support direct name search.
        This may need to fetch all and filter client-side, or use
        a different endpoint. Adjust based on your PrintSmith version.
        
        Args:
            name: Partial name to search for
            limit: Maximum results to return
            
        Returns:
            List of matching accounts
        """
        # PrintSmith's API search capabilities vary by version
        # This attempts a basic search - may need adjustment
        params = {}
        if name:
            params["name"] = name
        params["limit"] = limit
        
        try:
            result = await self._get("/AccountAPI", params=params)
            if isinstance(result, list):
                return result[:limit]
            elif isinstance(result, dict) and "accounts" in result:
                return result["accounts"][:limit]
            else:
                return [result] if result else []
        except PrintSmithAPIError:
            # If search not supported, return empty
            logger.warning("Account search may not be supported by this PrintSmith version")
            return []

    # =========================================================================
    # INVOICE OPERATIONS (Read-Only)
    # =========================================================================
    
    async def get_invoice(self, invoice_id: str) -> dict:
        """
        Get a single invoice by ID.
        
        Args:
            invoice_id: The PrintSmith invoice ID
            
        Returns:
            Invoice details dict
        """
        result = await self._get("/InvoiceAPI", params={"invoice_id": invoice_id})
        return result
    
    async def get_invoices_by_date_range(
        self, 
        start_date: datetime, 
        end_date: datetime = None
    ) -> list[dict]:
        """
        Get invoices within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range (defaults to now)
            
        Returns:
            List of invoices
        """
        if end_date is None:
            end_date = datetime.now()
        
        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        }
        
        result = await self._get("/InvoiceAPI", params=params)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "invoices" in result:
            return result["invoices"]
        return []
    
    async def get_invoices_by_account(self, account_id: str) -> list[dict]:
        """
        Get all invoices for a specific account.
        
        Args:
            account_id: The PrintSmith account ID
            
        Returns:
            List of invoices for this account
        """
        result = await self._get("/InvoiceAPI", params={"account_id": account_id})
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "invoices" in result:
            return result["invoices"]
        return [result] if result else []

    # =========================================================================
    # ESTIMATE OPERATIONS (Read-Only)
    # =========================================================================
    
    async def get_estimate(self, estimate_id: str) -> dict:
        """
        Get a single estimate by ID.
        
        Args:
            estimate_id: The PrintSmith estimate ID
            
        Returns:
            Estimate details dict
        """
        result = await self._get("/EstimateAPI", params={"estimate_id": estimate_id})
        return result
    
    async def get_estimates_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime = None
    ) -> list[dict]:
        """
        Get estimates within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range (defaults to now)
            
        Returns:
            List of estimates
        """
        if end_date is None:
            end_date = datetime.now()
        
        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        }
        
        result = await self._get("/EstimateAPI", params=params)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "estimates" in result:
            return result["estimates"]
        return []
    
    async def get_estimates_by_account(self, account_id: str) -> list[dict]:
        """
        Get all estimates for a specific account.
        
        Args:
            account_id: The PrintSmith account ID
            
        Returns:
            List of estimates for this account
        """
        result = await self._get("/EstimateAPI", params={"account_id": account_id})
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "estimates" in result:
            return result["estimates"]
        return [result] if result else []

    # =========================================================================
    # JOB / PRODUCTION OPERATIONS (Read-Only)
    # =========================================================================
    
    async def get_job(self, job_id: str) -> dict:
        """
        Get a single job by ID or job number.
        
        Args:
            job_id: The PrintSmith job ID or job number
            
        Returns:
            Job details dict
        """
        # Try by job_id first, then by job number if that fails
        try:
            result = await self._get("/JobAPI", params={"job_id": job_id})
            return result
        except PrintSmithAPIError:
            result = await self._get("/JobAPI", params={"job_number": job_id})
            return result
    
    async def get_jobs_by_status(self, status: str) -> list[dict]:
        """
        Get jobs filtered by status.
        
        Common statuses (may vary by PrintSmith configuration):
        - "pending", "in_progress", "completed", "shipped", "on_hold"
        
        Args:
            status: Job status to filter by
            
        Returns:
            List of jobs with this status
        """
        result = await self._get("/JobAPI", params={"status": status})
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "jobs" in result:
            return result["jobs"]
        return []
    
    async def get_jobs_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime = None,
        date_field: str = "due_date"
    ) -> list[dict]:
        """
        Get jobs within a date range.
        
        Args:
            start_date: Start of date range
            end_date: End of date range (defaults to now)
            date_field: Which date to filter on (due_date, created_date, etc.)
            
        Returns:
            List of jobs
        """
        if end_date is None:
            end_date = datetime.now()
        
        params = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        }
        
        result = await self._get("/JobAPI", params=params)
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "jobs" in result:
            return result["jobs"]
        return []

    # =========================================================================
    # CONTACT OPERATIONS (Read-Only)
    # =========================================================================
    
    async def get_contact(self, contact_id: str) -> dict:
        """
        Get a single contact by ID.
        
        Args:
            contact_id: The PrintSmith contact ID
            
        Returns:
            Contact details dict
        """
        result = await self._get("/ContactAPI", params={"contact_id": contact_id})
        return result
    
    async def get_contacts_by_account(self, account_id: str) -> list[dict]:
        """
        Get all contacts for an account.
        
        Args:
            account_id: The PrintSmith account ID
            
        Returns:
            List of contacts
        """
        result = await self._get("/ContactAPI", params={"account_id": account_id})
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "contacts" in result:
            return result["contacts"]
        return [result] if result else []

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================
    
    async def health_check(self) -> dict:
        """
        Check if PrintSmith API is reachable and token is valid.
        
        Returns:
            Dict with status and any error message
        """
        try:
            # Try to fetch a minimal amount of data
            await self._get("/AccountAPI", params={"limit": 1})
            return {"status": "healthy", "message": "PrintSmith API is reachable"}
        except PrintSmithAPIError as e:
            return {
                "status": "unhealthy",
                "message": str(e),
                "status_code": e.status_code
            }
        except Exception as e:
            return {"status": "unhealthy", "message": str(e)}
