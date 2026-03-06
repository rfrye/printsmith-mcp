#!/bin/bash
#===============================================================================
# PrintSmith MCP Server - LXC Setup Script for Proxmox
#===============================================================================
# 
# This script sets up an LXC container on Proxmox to run the PrintSmith MCP server.
# 
# PREREQUISITES:
#   - Proxmox VE host with LXC support
#   - Ubuntu/Debian template downloaded
#   - Network configured
#
# USAGE:
#   1. Copy this script to your Proxmox host
#   2. Edit the variables below
#   3. Run: bash setup-lxc.sh
#
#===============================================================================

set -e  # Exit on error

#-------------------------------------------------------------------------------
# CONFIGURATION - EDIT THESE VALUES
#-------------------------------------------------------------------------------

# LXC Container settings
CTID="${CTID:-200}"                          # Container ID (unique on your Proxmox)
HOSTNAME="${HOSTNAME:-printsmith-mcp}"       # Container hostname
TEMPLATE="${TEMPLATE:-local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst}"
STORAGE="${STORAGE:-local-lvm}"              # Storage for container disk
DISK_SIZE="${DISK_SIZE:-8}"                  # Disk size in GB
MEMORY="${MEMORY:-512}"                      # Memory in MB
CORES="${CORES:-1}"                          # CPU cores

# Network - adjust for your environment
BRIDGE="${BRIDGE:-vmbr0}"
IP_ADDRESS="${IP_ADDRESS:-dhcp}"             # Use "dhcp" or "10.0.0.50/24"
GATEWAY="${GATEWAY:-}"                       # Leave empty for DHCP, or set like "10.0.0.1"

# MCP Server settings
MCP_PORT="${MCP_PORT:-8080}"                 # Port for MCP HTTP server

# PrintSmith settings (will be saved to .env file in container)
PRINTSMITH_BASE_URL="${PRINTSMITH_BASE_URL:-}"
PRINTSMITH_API_TOKEN="${PRINTSMITH_API_TOKEN:-}"

#-------------------------------------------------------------------------------
# CREATE CONTAINER
#-------------------------------------------------------------------------------

echo "=============================================="
echo "Creating LXC Container: $HOSTNAME (ID: $CTID)"
echo "=============================================="

# Build network config
if [ "$IP_ADDRESS" = "dhcp" ]; then
    NET_CONFIG="name=eth0,bridge=$BRIDGE,ip=dhcp"
else
    NET_CONFIG="name=eth0,bridge=$BRIDGE,ip=$IP_ADDRESS,gw=$GATEWAY"
fi

# Create the container
pct create $CTID $TEMPLATE \
    --hostname $HOSTNAME \
    --storage $STORAGE \
    --rootfs ${STORAGE}:${DISK_SIZE} \
    --memory $MEMORY \
    --cores $CORES \
    --net0 $NET_CONFIG \
    --unprivileged 1 \
    --features nesting=1 \
    --onboot 1 \
    --start 0

echo "Container created successfully."

#-------------------------------------------------------------------------------
# START CONTAINER AND CONFIGURE
#-------------------------------------------------------------------------------

echo ""
echo "Starting container..."
pct start $CTID

# Wait for container to be ready
echo "Waiting for container to initialize..."
sleep 10

#-------------------------------------------------------------------------------
# INSTALL DEPENDENCIES
#-------------------------------------------------------------------------------

echo ""
echo "Installing dependencies..."

pct exec $CTID -- bash -c "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3 python3-pip python3-venv git curl
"

#-------------------------------------------------------------------------------
# CREATE APPLICATION USER
#-------------------------------------------------------------------------------

echo ""
echo "Creating application user..."

pct exec $CTID -- bash -c "
    useradd -m -s /bin/bash mcp || true
    mkdir -p /opt/printsmith-mcp
    chown mcp:mcp /opt/printsmith-mcp
"

#-------------------------------------------------------------------------------
# SETUP APPLICATION
#-------------------------------------------------------------------------------

echo ""
echo "Setting up PrintSmith MCP server..."

# Create the application directory structure
pct exec $CTID -- bash -c "
    mkdir -p /opt/printsmith-mcp/src
"

echo ""
echo "=============================================="
echo "Container created successfully!"
echo "=============================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Copy the application files to the container:"
echo "   pct push $CTID ./src/server.py /opt/printsmith-mcp/src/server.py"
echo "   pct push $CTID ./src/printsmith_client.py /opt/printsmith-mcp/src/printsmith_client.py"
echo "   pct push $CTID ./requirements.txt /opt/printsmith-mcp/requirements.txt"
echo ""
echo "2. Enter the container:"
echo "   pct enter $CTID"
echo ""
echo "3. Run the install script:"
echo "   cd /opt/printsmith-mcp"
echo "   bash scripts/install.sh"
echo ""
echo "4. Configure your PrintSmith connection:"
echo "   nano /opt/printsmith-mcp/.env"
echo ""
echo "5. Start the service:"
echo "   systemctl start printsmith-mcp"
echo ""
echo "The MCP server will be available at: http://<container-ip>:$MCP_PORT"
echo ""
