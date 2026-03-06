#!/bin/bash
#===============================================================================
# PrintSmith MCP Server - Deploy to LXC Container
#===============================================================================
# Copies application files to an existing LXC container.
#
# Usage: bash deploy-to-lxc.sh <container_id>
# Example: bash deploy-to-lxc.sh 200
#===============================================================================

set -e

CTID="${1:-}"

if [ -z "$CTID" ]; then
    echo "Usage: $0 <container_id>"
    echo "Example: $0 200"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
APP_DIR="/opt/printsmith-mcp"

echo "=============================================="
echo "Deploying to LXC Container $CTID"
echo "=============================================="

# Check container exists and is running
if ! pct status $CTID | grep -q "running"; then
    echo "Container $CTID is not running. Starting it..."
    pct start $CTID
    sleep 5
fi

# Create directories
echo "Creating directories..."
pct exec $CTID -- mkdir -p $APP_DIR/src $APP_DIR/scripts

# Copy source files
echo "Copying source files..."
pct push $CTID "$PROJECT_DIR/src/server.py" "$APP_DIR/src/server.py"
pct push $CTID "$PROJECT_DIR/src/printsmith_client.py" "$APP_DIR/src/printsmith_client.py"

# Copy requirements
echo "Copying requirements..."
pct push $CTID "$PROJECT_DIR/requirements.txt" "$APP_DIR/requirements.txt"

# Copy install script
echo "Copying install script..."
pct push $CTID "$PROJECT_DIR/scripts/install.sh" "$APP_DIR/scripts/install.sh"
pct exec $CTID -- chmod +x "$APP_DIR/scripts/install.sh"

echo ""
echo "=============================================="
echo "Files deployed successfully!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Enter the container:"
echo "   pct enter $CTID"
echo ""
echo "2. Run the installer:"
echo "   cd $APP_DIR && bash scripts/install.sh"
echo ""
echo "Or run installer directly:"
echo "   pct exec $CTID -- bash -c 'cd $APP_DIR && bash scripts/install.sh'"
echo ""
