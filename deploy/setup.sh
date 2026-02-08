#!/bin/bash
# Writer Web - Server Setup Script
# Run this on a fresh Ubuntu VPS (DreamCompute, etc.)
#
# Usage: sudo bash setup.sh YOUR_DOMAIN
#   e.g: sudo bash setup.sh writer.example.com
#
# What this does:
#   1. Installs system packages (python3, nginx, certbot, git)
#   2. Creates a 'writer' user
#   3. Clones the repo and sets up Python venv
#   4. Prompts you to configure API keys and password
#   5. Sets up systemd service (auto-start, auto-restart)
#   6. Sets up nginx reverse proxy
#   7. Gets HTTPS certificate from Let's Encrypt

set -e

DOMAIN="${1:-}"
REPO="https://github.com/J-Kahn/Writer.git"
APP_DIR="/home/writer/Writer"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Usage: sudo bash setup.sh YOUR_DOMAIN${NC}"
    echo "  e.g: sudo bash setup.sh writer.example.com"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run with sudo${NC}"
    exit 1
fi

echo -e "${CYAN}=== Writer Web Server Setup ===${NC}"
echo -e "Domain: ${GREEN}$DOMAIN${NC}"
echo ""

# --- Step 1: System packages ---
echo -e "${YELLOW}[1/7] Installing system packages...${NC}"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx

# --- Step 2: Create user ---
echo -e "${YELLOW}[2/7] Creating 'writer' user...${NC}"
if ! id -u writer &>/dev/null; then
    useradd -m -s /bin/bash writer
    echo -e "${GREEN}User 'writer' created${NC}"
else
    echo "User 'writer' already exists"
fi

# --- Step 3: Clone repo and setup venv ---
echo -e "${YELLOW}[3/7] Setting up application...${NC}"
if [ -d "$APP_DIR" ]; then
    echo "Updating existing repo..."
    sudo -u writer git -C "$APP_DIR" pull
else
    sudo -u writer git clone "$REPO" "$APP_DIR"
fi

echo "Creating Python virtual environment..."
sudo -u writer python3 -m venv "$APP_DIR/venv"
sudo -u writer "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements-web.txt"

# --- Step 4: Configure ---
echo -e "${YELLOW}[4/7] Setting up configuration...${NC}"
CONFIG_DIR="/home/writer/.writer/config"
DOCS_DIR="/home/writer/Documents/Writer"
sudo -u writer mkdir -p "$CONFIG_DIR" "$DOCS_DIR"

if [ ! -f "$CONFIG_DIR/writer.conf" ]; then
    sudo -u writer cp "$APP_DIR/config/writer.conf.example" "$CONFIG_DIR/writer.conf"
    echo ""
    echo -e "${CYAN}============================================${NC}"
    echo -e "${CYAN}  IMPORTANT: Edit your config file now!     ${NC}"
    echo -e "${CYAN}============================================${NC}"
    echo -e "  File: ${GREEN}$CONFIG_DIR/writer.conf${NC}"
    echo ""
    echo "  You MUST set:"
    echo "    1. [ai] section - your API key"
    echo "    2. [web] section - a strong password"
    echo ""
    echo -e "  Opening with nano... (Ctrl+X to save and exit)"
    echo ""
    read -p "  Press Enter to edit config..."
    sudo -u writer nano "$CONFIG_DIR/writer.conf"
else
    echo "Config already exists at $CONFIG_DIR/writer.conf"
fi

# --- Step 5: Systemd service ---
echo -e "${YELLOW}[5/7] Setting up systemd service...${NC}"
cp "$APP_DIR/deploy/writer-web.service" /etc/systemd/system/writer-web.service
systemctl daemon-reload
systemctl enable writer-web
systemctl restart writer-web
echo -e "${GREEN}Service started and enabled on boot${NC}"

# --- Step 6: Nginx ---
echo -e "${YELLOW}[6/7] Configuring nginx...${NC}"
sed "s/YOUR_DOMAIN/$DOMAIN/g" "$APP_DIR/deploy/nginx-writer.conf.template" > /etc/nginx/sites-available/writer
ln -sf /etc/nginx/sites-available/writer /etc/nginx/sites-enabled/writer
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo -e "${GREEN}Nginx configured${NC}"

# --- Step 7: HTTPS ---
echo -e "${YELLOW}[7/7] Setting up HTTPS with Let's Encrypt...${NC}"
echo ""
echo "  Make sure your DNS is pointed to this server first!"
echo "  $DOMAIN -> $(curl -s ifconfig.me 2>/dev/null || echo 'your-server-ip')"
echo ""
read -p "  DNS ready? Press Enter to get certificate (or Ctrl+C to skip)..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || {
    echo -e "${YELLOW}Certbot failed - you can run it manually later:${NC}"
    echo "  sudo certbot --nginx -d $DOMAIN"
}

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Writer Web is running!                    ${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  URL:    ${CYAN}https://$DOMAIN${NC}"
echo -e "  Config: ${CYAN}$CONFIG_DIR/writer.conf${NC}"
echo -e "  Docs:   ${CYAN}$DOCS_DIR${NC}"
echo -e "  Logs:   ${CYAN}journalctl -u writer-web -f${NC}"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl restart writer-web   # restart app"
echo "    sudo systemctl status writer-web    # check status"
echo "    sudo journalctl -u writer-web -f    # view logs"
echo ""
