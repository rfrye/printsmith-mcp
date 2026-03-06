# PrintSmith MCP Server

An MCP (Model Context Protocol) server that connects Claude to PrintSmith Vision, enabling AI-assisted print shop management.

**All operations are READ-ONLY** - this server only queries data, never modifies it.

---

## Features

| Tool | Description |
|------|-------------|
| `lookup_customer` | Search customers by name, ID, or account number |
| `get_job_status` | Get production status of a specific job |
| `list_jobs` | List jobs filtered by status (in production, ready for pickup, etc.) |
| `get_customer_jobs` | Get all jobs for a specific customer |
| `get_ar_summary` | Accounts receivable summary |
| `get_estimate` | Get details of a specific estimate |
| `list_pending_estimates` | List estimates awaiting conversion |
| `health_check` | Verify PrintSmith connection |

---

## Quick Start (Mock Data)

Test the server without a PrintSmith connection:

```bash
cd printsmith-mcp
pip install -r requirements.txt
USE_MOCK_DATA=true python src/server.py
```

---

## Deployment on Proxmox LXC

### Step 1: Create the LXC Container

On your Proxmox host:

```bash
# Download the setup script
scp scripts/setup-lxc.sh root@proxmox:/tmp/

# SSH to Proxmox and run
ssh root@proxmox
cd /tmp

# Edit variables at top of script, then run:
bash setup-lxc.sh
```

This creates an Ubuntu 24.04 LXC container with Python installed.

### Step 2: Deploy Application Files

From your local machine (where you downloaded this repo):

```bash
# Set your container ID
CTID=200

# Copy files to container
pct push $CTID src/server.py /opt/printsmith-mcp/src/server.py
pct push $CTID src/printsmith_client.py /opt/printsmith-mcp/src/printsmith_client.py
pct push $CTID requirements.txt /opt/printsmith-mcp/requirements.txt
pct push $CTID scripts/install.sh /opt/printsmith-mcp/scripts/install.sh
```

Or use the deploy script:
```bash
bash scripts/deploy-to-lxc.sh 200
```

### Step 3: Install Inside Container

```bash
pct enter 200

cd /opt/printsmith-mcp
bash scripts/install.sh
```

### Step 4: Configure PrintSmith Connection

```bash
nano /opt/printsmith-mcp/.env
```

Edit these values:
```ini
PRINTSMITH_BASE_URL=https://your-printsmith-server.com
PRINTSMITH_API_TOKEN=your-api-token-here
USE_MOCK_DATA=false
```

### Step 5: Start the Service

```bash
systemctl start printsmith-mcp
systemctl status printsmith-mcp

# View logs
journalctl -u printsmith-mcp -f
```

### Step 6: Test

```bash
# From inside container
curl http://localhost:8080/health

# From Proxmox host (replace IP)
curl http://10.0.0.50:8080/health
```

---

## Connecting to Claude

### Option A: Claude Desktop (if LXC has STDIO access)

Not recommended for LXC. Use Option B.

### Option B: Remote MCP Connection (Recommended)

The server runs in HTTP/SSE mode, accessible at:
```
http://<container-ip>:8080/sse
```

To use with Claude, you'll need an MCP client that supports remote servers. Check Anthropic's documentation for current options.

### Option C: For Development/Testing

You can also run the server locally in STDIO mode for Claude Desktop:

```bash
MCP_TRANSPORT=stdio python src/server.py
```

---

## PrintSmith API Reference

### Getting Your API Token

1. Log into PrintSmith Vision as administrator
2. Go to **Setup → Preferences → API Settings**
3. Generate or copy your API token

### API Endpoints Used (Read-Only)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/AccountAPI/{token}` | GET | Customer/account data |
| `/InvoiceAPI/{token}` | GET | Invoice data |
| `/EstimateAPI/{token}` | GET | Estimate data |
| `/JobAPI/{token}` | GET | Job/production data |
| `/ContactAPI/{token}` | GET | Contact data |

### Authentication

PrintSmith uses token-in-URL authentication:
```
GET https://your-server.com/AccountAPI/YOUR_API_TOKEN?account_id=1234
```

### Common Query Parameters

| Parameter | Description |
|-----------|-------------|
| `account_id` | Primary key ID |
| `account_account_id` | Display account number |
| `contact_id` | Contact primary key |
| `start_date` | Range filter start (YYYY-MM-DD) |
| `end_date` | Range filter end (YYYY-MM-DD) |
| `status` | Status filter |

### Response Format

All responses are JSON:
```json
{
  "id": "1234",
  "name": "Acme Corporation",
  "balance": 2450.00,
  "credit_status": "good"
}
```

### Error Responses

```json
{
  "status": "Failure",
  "message": "Account with number(account_account_id): 9999 was not found."
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PRINTSMITH_BASE_URL` | (required) | PrintSmith server URL |
| `PRINTSMITH_API_TOKEN` | (required) | API authentication token |
| `PRINTSMITH_VERIFY_SSL` | `true` | Verify SSL certificates |
| `PRINTSMITH_TIMEOUT` | `30` | Request timeout in seconds |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `http` |
| `MCP_HTTP_PORT` | `8080` | HTTP server port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP server bind address |
| `USE_MOCK_DATA` | `false` | Use mock data (no PrintSmith needed) |

---

## Project Structure

```
printsmith-mcp/
├── src/
│   ├── server.py              # MCP server (main entry point)
│   └── printsmith_client.py   # PrintSmith API client (read-only)
├── scripts/
│   ├── setup-lxc.sh           # Create LXC container on Proxmox
│   ├── deploy-to-lxc.sh       # Copy files to container
│   └── install.sh             # Install inside container
├── requirements.txt
└── README.md
```

---

## Security Considerations

1. **API Token**: Stored in `.env` file with restricted permissions (600)
2. **Read-Only**: All operations are GET requests only
3. **Network**: Consider firewall rules to restrict access to MCP port
4. **SSL**: Enable `PRINTSMITH_VERIFY_SSL` in production

For a multi-tenant SaaS, you'll need additional:
- Per-customer credential storage (encrypted)
- Authentication for the MCP endpoint
- Rate limiting
- Audit logging

---

## Troubleshooting

### Container won't start
```bash
pct status 200
pct config 200
journalctl -u pve-container@200
```

### Service fails to start
```bash
pct enter 200
journalctl -u printsmith-mcp -n 50
```

### Can't connect to PrintSmith
```bash
# Test from inside container
curl -v "https://your-printsmith-server.com/AccountAPI/YOUR_TOKEN?limit=1"
```

### SSL certificate errors
```bash
# Temporarily disable SSL verification
echo "PRINTSMITH_VERIFY_SSL=false" >> /opt/printsmith-mcp/.env
systemctl restart printsmith-mcp
```

---

## Next Steps

1. **Test with mock data** - Verify everything works
2. **Connect to real PrintSmith** - Add your credentials
3. **Identify high-value features** - What do users need most?
4. **Add authentication** - Secure the MCP endpoint
5. **Build multi-tenant** - Credential management for multiple customers

---

## Resources

- [MCP Documentation](https://modelcontextprotocol.io/docs)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [PrintSmith Vision](https://printepssw.com/) - Contact EFI/ePS for API documentation
