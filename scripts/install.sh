#!/bin/bash
#===============================================================================
# PrintSmith MCP Server - Installation Script
#===============================================================================
# Run this script inside the LXC container after copying the files.
#
# Usage: bash install.sh
#===============================================================================

set -e

APP_DIR="/opt/printsmith-mcp"
APP_USER="mcp"

echo "=============================================="
echo "Installing PrintSmith MCP Server"
echo "=============================================="

#-------------------------------------------------------------------------------
# VERIFY WE'RE IN THE RIGHT PLACE
#-------------------------------------------------------------------------------

if [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "ERROR: requirements.txt not found in $APP_DIR"
    echo "Make sure you've copied all files to the container first."
    exit 1
fi

#-------------------------------------------------------------------------------
# CREATE VIRTUAL ENVIRONMENT
#-------------------------------------------------------------------------------

echo ""
echo "Creating Python virtual environment..."

cd $APP_DIR
python3 -m venv venv
source venv/bin/activate

#-------------------------------------------------------------------------------
# INSTALL DEPENDENCIES
#-------------------------------------------------------------------------------

echo ""
echo "Installing Python dependencies..."

pip install --upgrade pip
pip install -r requirements.txt

#-------------------------------------------------------------------------------
# CREATE ENVIRONMENT FILE
#-------------------------------------------------------------------------------

echo ""
echo "Creating environment configuration..."

if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'EOF'
# PrintSmith MCP Server Configuration
# ====================================

# PrintSmith Connection (required for live mode)
# Get these from your PrintSmith administrator
PRINTSMITH_BASE_URL=
PRINTSMITH_API_TOKEN=
PRINTSMITH_VERIFY_SSL=true
PRINTSMITH_TIMEOUT=30

# MCP Transport
# - "stdio" for local Claude Desktop
# - "http" for remote access (recommended for LXC)
MCP_TRANSPORT=http
MCP_HTTP_PORT=8080
MCP_HTTP_HOST=0.0.0.0

# Development/Testing
# Set to "true" to use mock data without PrintSmith connection
USE_MOCK_DATA=true
EOF
    echo "Created $APP_DIR/.env - edit this file with your PrintSmith credentials"
else
    echo ".env file already exists, skipping"
fi

#-------------------------------------------------------------------------------
# SET PERMISSIONS
#-------------------------------------------------------------------------------

echo ""
echo "Setting permissions..."

chown -R $APP_USER:$APP_USER $APP_DIR
chmod 600 $APP_DIR/.env  # Protect credentials

#-------------------------------------------------------------------------------
# CREATE SYSTEMD SERVICE
#-------------------------------------------------------------------------------

echo ""
echo "Creating systemd service..."

cat > /etc/systemd/system/printsmith-mcp.service << EOF
[Unit]
Description=PrintSmith MCP Server
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR/src
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python server.py
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable printsmith-mcp

#-------------------------------------------------------------------------------
# DONE
#-------------------------------------------------------------------------------

echo ""
echo "=============================================="
echo "Installation complete!"
echo "=============================================="
echo ""
echo "Configuration file: $APP_DIR/.env"
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Edit the configuration file with your PrintSmith credentials:"
echo "   nano $APP_DIR/.env"
echo ""
echo "2. Start the service:"
echo "   systemctl start printsmith-mcp"
echo ""
echo "3. Check status:"
echo "   systemctl status printsmith-mcp"
echo ""
echo "4. View logs:"
echo "   journalctl -u printsmith-mcp -f"
echo ""
echo "5. Test the server:"
echo "   curl http://localhost:8080/health"
echo ""
