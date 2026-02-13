#!/bin/bash

# Configuration
CONFIG_FILE="config.yml"
ENV_FILE=".env"
BACKUP_DIR="backups"
YQ_BINARY="./yq"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check and install yq if needed
ensure_yq() {
    if [ ! -f "$YQ_BINARY" ]; then
        if command -v yq &> /dev/null; then
            YQ_BINARY="yq"
        else
            echo -e "${YELLOW}yq not found. Downloading yq...${NC}"
            # Determine OS and Architecture
            OS=$(uname -s | tr '[:upper:]' '[:lower:]')
            ARCH=$(uname -m)
            
            if [ "$ARCH" = "x86_64" ]; then
                ARCH="amd64"
            elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
                ARCH="arm64" 
            else
                echo -e "${RED}Unsupported architecture: $ARCH${NC}"
                exit 1
            fi

            YQ_URL="https://github.com/mikefarah/yq/releases/latest/download/yq_${OS}_${ARCH}"
            
            curl -L "$YQ_URL" -o "$YQ_BINARY"
            chmod +x "$YQ_BINARY"
            echo -e "${GREEN}yq downloaded successfully to $YQ_BINARY${NC}"
        fi
    fi
}

# Helper: Create backup
create_backup() {
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    if [ -f "$CONFIG_FILE" ]; then
        cp "$CONFIG_FILE" "$BACKUP_DIR/config.yml.backup_$TIMESTAMP"
    fi
    if [ -f "$ENV_FILE" ]; then
        cp "$ENV_FILE" "$BACKUP_DIR/.env.backup_$TIMESTAMP"
    fi
    # Keep only last 10 backups
    ls -t "$BACKUP_DIR"/* | tail -n +21 | xargs -I {} rm -- "{}" 2>/dev/null
}

# Helper: Press any key to continue
pause() {
    read -p "Press [Enter] key to continue..."
}

# 1. Show Status
show_status() {
    echo -e "${BLUE}=== Current Configuration ===${NC}"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}Config file not found!${NC}"
        return
    fi
    
    echo -e "${YELLOW}Domains and Zones:${NC}"
    $YQ_BINARY '.domains[] | "  Domain: " + .domain + "\n" + (.zones[] | "    Zone: " + .name + " (TTL: " + (.ttl|toString) + ", Proxied: " + (.proxied|toString) + ")\n      IPs: " + (.ips | join(", ")))' "$CONFIG_FILE"
    echo ""
}

# 2. Add IP
add_ip() {
    echo -e "${BLUE}=== Add Node IP ===${NC}"
    
    # Select Domain
    DOMAINS=$($YQ_BINARY '.domains[].domain' "$CONFIG_FILE")
    echo "Available Domains:"
    select DOMAIN in $DOMAINS; do
        [ -n "$DOMAIN" ] && break
    done
    
    # Select Zone
    ZONES=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\") | .zones[].name" "$CONFIG_FILE")
    echo "Available Zones in $DOMAIN:"
    select ZONE in $ZONES; do
        [ -n "$ZONE" ] && break
    done

    read -p "Enter new IP address: " IP_ADDR
    
    if [[ -z "$IP_ADDR" ]]; then
        echo -e "${RED}Invalid IP${NC}"
        return
    fi
    
    create_backup
    
    # yq expression to append IP
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips) += \"$IP_ADDR\"" "$CONFIG_FILE"
    
    echo -e "${GREEN}Added $IP_ADDR to $ZONE.$DOMAIN${NC}"
}

# 3. Remove IP
remove_ip() {
    echo -e "${BLUE}=== Remove Node IP ===${NC}"
    
    # Select Domain
    DOMAINS=$($YQ_BINARY '.domains[].domain' "$CONFIG_FILE")
    echo "Available Domains:"
    select DOMAIN in $DOMAINS; do
        [ -n "$DOMAIN" ] && break
    done
    
    # Select Zone
    ZONES=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\") | .zones[].name" "$CONFIG_FILE")
    echo "Available Zones in $DOMAIN:"
    select ZONE in $ZONES; do
        [ -n "$ZONE" ] && break
    done
    
    # Select IP to remove
    IPS=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips[]" "$CONFIG_FILE")
    echo "Select IP to remove:"
    select IP_TO_REMOVE in $IPS; do
        [ -n "$IP_TO_REMOVE" ] && break
    done
    
    create_backup
    
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips) -= \"$IP_TO_REMOVE\"" "$CONFIG_FILE"
    
    echo -e "${GREEN}Removed $IP_TO_REMOVE from $ZONE.$DOMAIN${NC}"
}

# 4. Replace IP
replace_ip() {
    echo -e "${BLUE}=== Replace Node IP ===${NC}"
    
    # Select Domain
    DOMAINS=$($YQ_BINARY '.domains[].domain' "$CONFIG_FILE")
    echo "Available Domains:"
    select DOMAIN in $DOMAINS; do
        [ -n "$DOMAIN" ] && break
    done
    
    # Select Zone
    ZONES=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\") | .zones[].name" "$CONFIG_FILE")
    echo "Available Zones in $DOMAIN:"
    select ZONE in $ZONES; do
        [ -n "$ZONE" ] && break
    done
    
    # Select IP to replace
    IPS=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips[]" "$CONFIG_FILE")
    echo "Select IP to replace:"
    select OLD_IP in $IPS; do
        [ -n "$OLD_IP" ] && break
    done
    
    read -p "Enter NEW IP address: " NEW_IP
    
    if [[ -z "$NEW_IP" ]]; then
        echo -e "${RED}Invalid IP${NC}"
        return
    fi
    
    create_backup
    
    # Remove old, add new
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips) -= \"$OLD_IP\"" "$CONFIG_FILE"
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\").ips) += \"$NEW_IP\"" "$CONFIG_FILE"
    
    echo -e "${GREEN}Replaced $OLD_IP with $NEW_IP in $ZONE.$DOMAIN${NC}"
}

# 5. Add Zone
add_zone() {
    echo -e "${BLUE}=== Add New Zone ===${NC}"
    
    # Select Domain
    DOMAINS=$($YQ_BINARY '.domains[].domain' "$CONFIG_FILE")
    echo "Available Domains:"
    select DOMAIN in $DOMAINS; do
        [ -n "$DOMAIN" ] && break
    done
    
    read -p "Enter new zone name (subdomain): " ZONE_NAME
    read -p "Enter TTL [default: 60]: " TTL
    TTL=${TTL:-60}
    read -p "Proxied? (true/false) [default: false]: " PROXIED
    PROXIED=${PROXIED:-false}
    read -p "Enter initial IP address: " INITIAL_IP
    
    if [[ -z "$ZONE_NAME" || -z "$INITIAL_IP" ]]; then
        echo -e "${RED}Zone name and IP are required${NC}"
        return
    fi
    
    create_backup
    
    # Construct YAML object for new zone
    NEW_ZONE_YAML="{\"name\":\"$ZONE_NAME\",\"ttl\":$TTL,\"proxied\":$PROXIED,\"ips\":[\"$INITIAL_IP\"]}"
    
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$DOMAIN\").zones) += $NEW_ZONE_YAML" "$CONFIG_FILE"
    
    echo -e "${GREEN}Added zone $ZONE_NAME to $DOMAIN${NC}"
}

# 6. Remove Zone
remove_zone() {
    echo -e "${BLUE}=== Remove Zone ===${NC}"
    
    # Select Domain
    DOMAINS=$($YQ_BINARY '.domains[].domain' "$CONFIG_FILE")
    echo "Available Domains:"
    select DOMAIN in $DOMAINS; do
        [ -n "$DOMAIN" ] && break
    done
    
    # Select Zone
    ZONES=$($YQ_BINARY ".domains[] | select(.domain == \"$DOMAIN\") | .zones[].name" "$CONFIG_FILE")
    echo "Select Zone to remove:"
    select ZONE in $ZONES; do
        [ -n "$ZONE" ] && break
    done
    
    read -p "Are you sure you want to delete zone '$ZONE'? (y/N): " CONFIRM
    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
        echo "Cancelled."
        return
    fi

    create_backup
    
    $YQ_BINARY -i "del(.domains[] | select(.domain == \"$DOMAIN\").zones[] | select(.name == \"$ZONE\"))" "$CONFIG_FILE"
    
    echo -e "${GREEN}Removed zone $ZONE from $DOMAIN${NC}"
}

# 7. Edit Server Config (.env)
edit_env() {
    echo -e "${BLUE}=== Edit Server Config (.env) ===${NC}"
    
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}.env file not found!${NC}"
        return
    fi
    
    create_backup
    
    OPTIONS=("Change REMNAWAVE_API_URL" "Change REMNAWAVE_API_KEY" "Change CLOUDFLARE_API_TOKEN" "Change TELEGRAM_BOT_TOKEN" "Change TELEGRAM_CHAT_ID" "Back")
    
    select OPT in "${OPTIONS[@]}"; do
        case $OPT in
            "Change REMNAWAVE_API_URL")
                read -p "Enter new URL: " NEW_VAL
                sed -i.bak "s|^REMNAWAVE_API_URL=.*|REMNAWAVE_API_URL=$NEW_VAL|" "$ENV_FILE" && rm "$ENV_FILE.bak"
                break
                ;;
            "Change REMNAWAVE_API_KEY")
                read -p "Enter new API Key: " NEW_VAL
                sed -i.bak "s|^REMNAWAVE_API_KEY=.*|REMNAWAVE_API_KEY=$NEW_VAL|" "$ENV_FILE" && rm "$ENV_FILE.bak"
                break
                ;;
            "Change CLOUDFLARE_API_TOKEN")
                read -p "Enter new Cloudflare Token: " NEW_VAL
                sed -i.bak "s|^CLOUDFLARE_API_TOKEN=.*|CLOUDFLARE_API_TOKEN=$NEW_VAL|" "$ENV_FILE" && rm "$ENV_FILE.bak"
                break
                ;;
            "Change TELEGRAM_BOT_TOKEN")
                read -p "Enter new Bot Token: " NEW_VAL
                sed -i.bak "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$NEW_VAL|" "$ENV_FILE" && rm "$ENV_FILE.bak"
                break
                ;;
            "Change TELEGRAM_CHAT_ID")
                read -p "Enter new Chat ID: " NEW_VAL
                sed -i.bak "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=$NEW_VAL|" "$ENV_FILE" && rm "$ENV_FILE.bak"
                break
                ;;
            "Back")
                break
                ;;
            *) echo "Invalid option";;
        esac
    done
    echo -e "${GREEN}Updated .env file${NC}"
}

# 8. Restart Service
restart_service() {
    echo -e "${BLUE}=== Restarting Service ===${NC}"
    docker compose restart
    echo -e "${GREEN}Service restarted.${NC}"
}

# 9. Backup Config
backup_config() {
    create_backup
    echo -e "${GREEN}Backup created in $BACKUP_DIR${NC}"
}

# 10. Restore Backup
restore_backup() {
    echo -e "${BLUE}=== Restore Backup ===${NC}"
    
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR")" ]; then
        echo -e "${RED}No backups found.${NC}"
        return
    fi
    
    echo "Available Config Backups:"
    select BACKUP_FILE in $(ls "$BACKUP_DIR" | grep "config.yml"); do
        [ -n "$BACKUP_FILE" ] && break
    done
    
    if [ -n "$BACKUP_FILE" ]; then
        cp "$BACKUP_DIR/$BACKUP_FILE" "$CONFIG_FILE"
        echo -e "${GREEN}Restored $CONFIG_FILE from $BACKUP_FILE${NC}"
    fi

    echo "Available .env Backups:"
    select ENV_BACKUP in $(ls "$BACKUP_DIR" | grep ".env"); do
        [ -n "$ENV_BACKUP" ] && break
    done
    
    if [ -n "$ENV_BACKUP" ]; then
        cp "$BACKUP_DIR/$ENV_BACKUP" "$ENV_FILE"
        echo -e "${GREEN}Restored $ENV_FILE from $ENV_BACKUP${NC}"
    fi
}

# Main Loop
ensure_yq

while true; do
    clear
    echo -e "${BLUE}==============================${NC}"
    echo -e "${BLUE}   Node Management Manager    ${NC}"
    echo -e "${BLUE}==============================${NC}"
    echo "1. Show Status"
    echo "2. Add IP"
    echo "3. Remove IP"
    echo "4. Replace IP"
    echo "5. Add Zone"
    echo "6. Remove Zone"
    echo "7. Edit Server Config (.env)"
    echo "8. Restart Service"
    echo "9. Backup Config"
    echo "10. Restore Backup"
    echo "0. Exit"
    echo -e "${BLUE}==============================${NC}"
    
    read -p "Enter choice: " choice
    
    case $choice in
        1) show_status; pause ;;
        2) add_ip; pause ;;
        3) remove_ip; pause ;;
        4) replace_ip; pause ;;
        5) add_zone; pause ;;
        6) remove_zone; pause ;;
        7) edit_env; pause ;;
        8) restart_service; pause ;;
        9) backup_config; pause ;;
        10) restore_backup; pause ;;
        0) exit 0 ;;
        *) echo -e "${RED}Invalid choice${NC}"; pause ;;
    esac
done
