#!/bin/bash

# ──────────────────────────────────────────────
#  Remnawave Node Management Script
# ──────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.yml"
ENV_FILE="$SCRIPT_DIR/.env"
BACKUP_DIR="$SCRIPT_DIR/backups"
YQ_BINARY=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ──────────────────────────────────────────────
#  Detect OS for portable sed -i
# ──────────────────────────────────────────────
SED_INPLACE=()
if [[ "$(uname -s)" == "Darwin" ]]; then
    SED_INPLACE=(-i '')
else
    SED_INPLACE=(-i)
fi

# ──────────────────────────────────────────────
#  yq setup
# ──────────────────────────────────────────────
ensure_yq() {
    # 1) Try system yq (mikefarah version)
    if command -v yq &>/dev/null; then
        # Verify it's mikefarah/yq (not the python-yq wrapper)
        if yq --version 2>&1 | grep -qi 'mikefarah\|github.com/mikefarah'; then
            YQ_BINARY="yq"
            return
        fi
    fi

    # 2) Try local binary
    if [ -f "$SCRIPT_DIR/yq" ]; then
        if "$SCRIPT_DIR/yq" --version &>/dev/null; then
            YQ_BINARY="$SCRIPT_DIR/yq"
            return
        else
            echo -e "${YELLOW}Existing yq binary is incompatible, re-downloading...${NC}"
            rm -f "$SCRIPT_DIR/yq"
        fi
    fi

    # 3) Download
    echo -e "${YELLOW}yq not found. Downloading yq...${NC}"
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    case "$ARCH" in
        x86_64)  ARCH="amd64" ;;
        aarch64) ARCH="arm64" ;;
        arm64)   ARCH="arm64" ;;
        *)
            echo -e "${RED}Unsupported architecture: $ARCH${NC}"
            echo -e "${RED}Please install yq manually: https://github.com/mikefarah/yq${NC}"
            exit 1
            ;;
    esac

    YQ_URL="https://github.com/mikefarah/yq/releases/latest/download/yq_${OS}_${ARCH}"
    echo -e "  Downloading from: ${CYAN}$YQ_URL${NC}"

    if ! curl -fsSL "$YQ_URL" -o "$SCRIPT_DIR/yq"; then
        echo -e "${RED}Failed to download yq. Please install it manually.${NC}"
        exit 1
    fi

    chmod +x "$SCRIPT_DIR/yq"

    # Verify downloaded binary works
    if ! "$SCRIPT_DIR/yq" --version &>/dev/null; then
        echo -e "${RED}Downloaded yq binary is not compatible with this system.${NC}"
        rm -f "$SCRIPT_DIR/yq"
        echo -e "${RED}Please install yq manually: https://github.com/mikefarah/yq${NC}"
        exit 1
    fi

    YQ_BINARY="$SCRIPT_DIR/yq"
    echo -e "${GREEN}yq installed successfully.${NC}"
}

# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────
create_backup() {
    mkdir -p "$BACKUP_DIR"
    local ts
    ts=$(date +%Y%m%d_%H%M%S)

    [ -f "$CONFIG_FILE" ] && cp "$CONFIG_FILE" "$BACKUP_DIR/config.yml.backup_$ts"
    [ -f "$ENV_FILE" ]    && cp "$ENV_FILE"    "$BACKUP_DIR/.env.backup_$ts"

    # Keep only last 20 backup files
    local count
    count=$(find "$BACKUP_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l)
    if [ "$count" -gt 20 ]; then
        find "$BACKUP_DIR" -maxdepth 1 -type f -printf '%T+ %p\n' 2>/dev/null \
            | sort | head -n $(( count - 20 )) | awk '{print $2}' | xargs rm -f 2>/dev/null
        # macOS fallback (no -printf)
        if [ $? -ne 0 ]; then
            ls -t "$BACKUP_DIR"/* 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null
        fi
    fi
}

pause() {
    echo ""
    read -rp "Press [Enter] to continue..."
}

check_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}Error: Config file not found at $CONFIG_FILE${NC}"
        echo -e "${YELLOW}Create it from the example: cp config.example.yml config.yml${NC}"
        return 1
    fi
    return 0
}

check_env() {
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}Error: .env file not found at $ENV_FILE${NC}"
        echo -e "${YELLOW}Create it from the example: cp .env.example .env${NC}"
        return 1
    fi
    return 0
}

# Read domains into a bash array safely
get_domains() {
    local -a domains=()
    while IFS= read -r line; do
        [ -n "$line" ] && domains+=("$line")
    done < <($YQ_BINARY -r '.domains[].domain' "$CONFIG_FILE" 2>/dev/null)
    echo "${domains[@]}"
}

# Read zones for a domain into stdout (one per line)
get_zones() {
    local domain="$1"
    $YQ_BINARY -r ".domains[] | select(.domain == \"$domain\") | .zones[].name" "$CONFIG_FILE" 2>/dev/null
}

# Read IPs for a domain+zone into stdout (one per line)
get_ips() {
    local domain="$1" zone="$2"
    $YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[]" "$CONFIG_FILE" 2>/dev/null
}

select_domain() {
    local -a domains=()
    while IFS= read -r line; do
        [ -n "$line" ] && domains+=("$line")
    done < <($YQ_BINARY -r '.domains[].domain' "$CONFIG_FILE" 2>/dev/null)

    if [ ${#domains[@]} -eq 0 ]; then
        echo -e "${RED}No domains found in config.${NC}"
        return 1
    fi

    echo "Available Domains:"
    select SELECTED_DOMAIN in "${domains[@]}"; do
        if [ -n "$SELECTED_DOMAIN" ]; then
            echo "$SELECTED_DOMAIN"
            return 0
        fi
        echo -e "${RED}Invalid selection, try again.${NC}"
    done
}

select_zone() {
    local domain="$1"
    local -a zones=()
    while IFS= read -r line; do
        [ -n "$line" ] && zones+=("$line")
    done < <(get_zones "$domain")

    if [ ${#zones[@]} -eq 0 ]; then
        echo -e "${RED}No zones found for $domain.${NC}"
        return 1
    fi

    echo "Available Zones in $domain:"
    select SELECTED_ZONE in "${zones[@]}"; do
        if [ -n "$SELECTED_ZONE" ]; then
            echo "$SELECTED_ZONE"
            return 0
        fi
        echo -e "${RED}Invalid selection, try again.${NC}"
    done
}

select_ip() {
    local domain="$1" zone="$2"
    local -a ips=()
    while IFS= read -r line; do
        [ -n "$line" ] && ips+=("$line")
    done < <(get_ips "$domain" "$zone")

    if [ ${#ips[@]} -eq 0 ]; then
        echo -e "${RED}No IPs found for $zone.$domain.${NC}"
        return 1
    fi

    echo "Current IPs:"
    select SELECTED_IP in "${ips[@]}"; do
        if [ -n "$SELECTED_IP" ]; then
            echo "$SELECTED_IP"
            return 0
        fi
        echo -e "${RED}Invalid selection, try again.${NC}"
    done
}

# ──────────────────────────────────────────────
#  1. Show Status
# ──────────────────────────────────────────────
show_status() {
    echo -e "${BOLD}${BLUE}═══════════════════════════════════${NC}"
    echo -e "${BOLD}${BLUE}       Current Configuration       ${NC}"
    echo -e "${BOLD}${BLUE}═══════════════════════════════════${NC}"
    check_config || return

    local domain_count
    domain_count=$($YQ_BINARY '.domains | length' "$CONFIG_FILE")

    for (( d=0; d<domain_count; d++ )); do
        local domain
        domain=$($YQ_BINARY -r ".domains[$d].domain" "$CONFIG_FILE")
        echo -e "\n${BOLD}${CYAN}  📦 Domain: $domain${NC}"

        local zone_count
        zone_count=$($YQ_BINARY ".domains[$d].zones | length" "$CONFIG_FILE")

        for (( z=0; z<zone_count; z++ )); do
            local name ttl proxied
            name=$($YQ_BINARY -r ".domains[$d].zones[$z].name" "$CONFIG_FILE")
            ttl=$($YQ_BINARY -r ".domains[$d].zones[$z].ttl" "$CONFIG_FILE")
            proxied=$($YQ_BINARY -r ".domains[$d].zones[$z].proxied" "$CONFIG_FILE")

            echo -e "    ${GREEN}🌐 Zone: ${BOLD}$name.$domain${NC}  ${YELLOW}(TTL: $ttl, Proxied: $proxied)${NC}"

            local ip_count
            ip_count=$($YQ_BINARY ".domains[$d].zones[$z].ips | length" "$CONFIG_FILE")

            for (( i=0; i<ip_count; i++ )); do
                local ip
                ip=$($YQ_BINARY -r ".domains[$d].zones[$z].ips[$i]" "$CONFIG_FILE")
                echo -e "       └─ $ip"
            done
        done
    done

    echo -e "\n${BOLD}${BLUE}═══════════════════════════════════${NC}"

    if check_env 2>/dev/null; then
        echo -e "\n${BOLD}${CYAN}  ⚙️  Server Config (.env):${NC}"
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            # Mask sensitive values
            if [[ "$key" =~ (KEY|TOKEN|SECRET) ]]; then
                echo -e "    $key = ${YELLOW}****${NC}"
            else
                echo -e "    $key = ${GREEN}$value${NC}"
            fi
        done < "$ENV_FILE"
    fi
}

# ──────────────────────────────────────────────
#  2. Add IP
# ──────────────────────────────────────────────
add_ip() {
    echo -e "${BOLD}${BLUE}=== Add Node IP ===${NC}"
    check_config || return

    local domain zone ip_addr
    domain=$(select_domain) || return
    zone=$(select_zone "$domain") || return

    read -rp "Enter new IP address: " ip_addr
    if [[ -z "$ip_addr" ]]; then
        echo -e "${RED}IP address cannot be empty.${NC}"
        return
    fi

    # Check for duplicate
    local existing
    existing=$(get_ips "$domain" "$zone")
    if echo "$existing" | grep -qxF "$ip_addr"; then
        echo -e "${RED}IP $ip_addr already exists in $zone.$domain${NC}"
        return
    fi

    create_backup
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips) += [\"$ip_addr\"]" "$CONFIG_FILE"
    echo -e "${GREEN}✅ Added $ip_addr to $zone.$domain${NC}"
}

# ──────────────────────────────────────────────
#  3. Remove IP
# ──────────────────────────────────────────────
remove_ip() {
    echo -e "${BOLD}${BLUE}=== Remove Node IP ===${NC}"
    check_config || return

    local domain zone ip_to_remove
    domain=$(select_domain) || return
    zone=$(select_zone "$domain") || return
    ip_to_remove=$(select_ip "$domain" "$zone") || return

    read -rp "Remove $ip_to_remove from $zone.$domain? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Cancelled."
        return
    fi

    create_backup
    $YQ_BINARY -i "del(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[] | select(. == \"$ip_to_remove\"))" "$CONFIG_FILE"
    echo -e "${GREEN}✅ Removed $ip_to_remove from $zone.$domain${NC}"
}

# ──────────────────────────────────────────────
#  4. Replace IP
# ──────────────────────────────────────────────
replace_ip() {
    echo -e "${BOLD}${BLUE}=== Replace Node IP ===${NC}"
    check_config || return

    local domain zone old_ip new_ip
    domain=$(select_domain) || return
    zone=$(select_zone "$domain") || return
    old_ip=$(select_ip "$domain" "$zone") || return

    read -rp "Enter NEW IP address (replacing $old_ip): " new_ip
    if [[ -z "$new_ip" ]]; then
        echo -e "${RED}IP address cannot be empty.${NC}"
        return
    fi

    create_backup
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[] | select(. == \"$old_ip\")) = \"$new_ip\"" "$CONFIG_FILE"
    echo -e "${GREEN}✅ Replaced $old_ip → $new_ip in $zone.$domain${NC}"
}

# ──────────────────────────────────────────────
#  5. Add Zone
# ──────────────────────────────────────────────
add_zone() {
    echo -e "${BOLD}${BLUE}=== Add New Zone ===${NC}"
    check_config || return

    local domain zone_name ttl proxied initial_ip
    domain=$(select_domain) || return

    read -rp "Enter new zone name (subdomain): " zone_name
    if [[ -z "$zone_name" ]]; then
        echo -e "${RED}Zone name cannot be empty.${NC}"
        return
    fi

    # Check if zone already exists
    local existing_zone
    existing_zone=$(get_zones "$domain" | grep -xF "$zone_name")
    if [ -n "$existing_zone" ]; then
        echo -e "${RED}Zone '$zone_name' already exists in $domain.${NC}"
        return
    fi

    read -rp "Enter TTL [60]: " ttl
    ttl=${ttl:-60}
    read -rp "Proxied? (true/false) [false]: " proxied
    proxied=${proxied:-false}
    read -rp "Enter initial IP address: " initial_ip

    if [[ -z "$initial_ip" ]]; then
        echo -e "${RED}Initial IP is required.${NC}"
        return
    fi

    create_backup

    # Use yq to build and append the new zone object properly
    $YQ_BINARY -i "
        (.domains[] | select(.domain == \"$domain\").zones) += [{
            \"name\": \"$zone_name\",
            \"ttl\": $ttl,
            \"proxied\": $proxied,
            \"ips\": [\"$initial_ip\"]
        }]
    " "$CONFIG_FILE"

    echo -e "${GREEN}✅ Added zone $zone_name.$domain with IP $initial_ip${NC}"
}

# ──────────────────────────────────────────────
#  6. Remove Zone
# ──────────────────────────────────────────────
remove_zone() {
    echo -e "${BOLD}${BLUE}=== Remove Zone ===${NC}"
    check_config || return

    local domain zone
    domain=$(select_domain) || return
    zone=$(select_zone "$domain") || return

    echo -e "${RED}WARNING: This will remove zone '$zone' and ALL its IPs from $domain.${NC}"
    read -rp "Are you sure? (y/N): " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Cancelled."
        return
    fi

    create_backup
    $YQ_BINARY -i "del(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\"))" "$CONFIG_FILE"
    echo -e "${GREEN}✅ Removed zone $zone from $domain${NC}"
}

# ──────────────────────────────────────────────
#  7. Edit .env
# ──────────────────────────────────────────────
edit_env() {
    echo -e "${BOLD}${BLUE}=== Edit Server Config (.env) ===${NC}"
    check_env || return

    # Show current values (masked)
    echo -e "${CYAN}Current values:${NC}"
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        if [[ "$key" =~ (KEY|TOKEN|SECRET) ]]; then
            echo -e "  $key = ${YELLOW}****${NC}"
        else
            echo -e "  $key = $value"
        fi
    done < "$ENV_FILE"
    echo ""

    local options=("REMNAWAVE_API_URL" "REMNAWAVE_API_KEY" "CLOUDFLARE_API_TOKEN" "TELEGRAM_BOT_TOKEN" "TELEGRAM_CHAT_ID" "TELEGRAM_TOPIC_ID" "TIMEZONE" "TIME_FORMAT" "Back")

    echo "Select variable to change:"
    select opt in "${options[@]}"; do
        if [ "$opt" = "Back" ]; then
            return
        fi
        if [ -n "$opt" ]; then
            local current
            current=$(grep "^${opt}=" "$ENV_FILE" | cut -d'=' -f2-)
            echo -e "  Current: ${YELLOW}${current:-<not set>}${NC}"
            read -rp "  New value: " new_val

            if [ -z "$new_val" ]; then
                echo -e "${RED}Value cannot be empty.${NC}"
                return
            fi

            create_backup

            if grep -q "^${opt}=" "$ENV_FILE"; then
                sed "${SED_INPLACE[@]}" "s|^${opt}=.*|${opt}=${new_val}|" "$ENV_FILE"
            else
                echo "${opt}=${new_val}" >> "$ENV_FILE"
            fi

            echo -e "${GREEN}✅ Updated $opt${NC}"
            return
        fi
        echo -e "${RED}Invalid selection.${NC}"
    done
}

# ──────────────────────────────────────────────
#  8. Restart Service
# ──────────────────────────────────────────────
restart_service() {
    echo -e "${BOLD}${BLUE}=== Restart Service ===${NC}"

    if ! command -v docker &>/dev/null; then
        echo -e "${RED}Docker is not installed or not in PATH.${NC}"
        return
    fi

    echo -e "${YELLOW}Restarting docker compose service...${NC}"
    if docker compose -f "$SCRIPT_DIR/docker-compose.yml" restart; then
        echo -e "${GREEN}✅ Service restarted successfully.${NC}"
    else
        echo -e "${RED}Failed to restart. Check docker compose logs.${NC}"
    fi
}

# ──────────────────────────────────────────────
#  9. Backup
# ──────────────────────────────────────────────
backup_config() {
    echo -e "${BOLD}${BLUE}=== Create Backup ===${NC}"
    create_backup
    echo -e "${GREEN}✅ Backup created in $BACKUP_DIR/${NC}"
    echo ""
    echo "Recent backups:"
    ls -lt "$BACKUP_DIR"/ 2>/dev/null | head -10
}

# ──────────────────────────────────────────────
#  10. Restore Backup
# ──────────────────────────────────────────────
restore_backup() {
    echo -e "${BOLD}${BLUE}=== Restore Backup ===${NC}"

    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo -e "${RED}No backups found in $BACKUP_DIR/${NC}"
        return
    fi

    # Config backups
    local -a config_backups=()
    while IFS= read -r f; do
        [ -n "$f" ] && config_backups+=("$f")
    done < <(ls -t "$BACKUP_DIR" 2>/dev/null | grep "config.yml")

    if [ ${#config_backups[@]} -gt 0 ]; then
        echo -e "\n${CYAN}Config backups:${NC}"
        select backup_file in "${config_backups[@]}" "Skip"; do
            if [ "$backup_file" = "Skip" ]; then
                break
            fi
            if [ -n "$backup_file" ]; then
                cp "$BACKUP_DIR/$backup_file" "$CONFIG_FILE"
                echo -e "${GREEN}✅ Restored config.yml from $backup_file${NC}"
                break
            fi
        done
    fi

    # Env backups
    local -a env_backups=()
    while IFS= read -r f; do
        [ -n "$f" ] && env_backups+=("$f")
    done < <(ls -t "$BACKUP_DIR" 2>/dev/null | grep ".env")

    if [ ${#env_backups[@]} -gt 0 ]; then
        echo -e "\n${CYAN}.env backups:${NC}"
        select env_backup in "${env_backups[@]}" "Skip"; do
            if [ "$env_backup" = "Skip" ]; then
                break
            fi
            if [ -n "$env_backup" ]; then
                cp "$BACKUP_DIR/$env_backup" "$ENV_FILE"
                echo -e "${GREEN}✅ Restored .env from $env_backup${NC}"
                break
            fi
        done
    fi
}

# ──────────────────────────────────────────────
#  Main Menu
# ──────────────────────────────────────────────
ensure_yq

while true; do
    clear
    echo -e "${BOLD}${BLUE}╔══════════════════════════════════╗${NC}"
    echo -e "${BOLD}${BLUE}║   🖧  Node Management Manager   ║${NC}"
    echo -e "${BOLD}${BLUE}╠══════════════════════════════════╣${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  1.  Show Status                ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  2.  Add IP                    ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  3.  Remove IP                 ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  4.  Replace IP                ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  5.  Add Zone                  ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  6.  Remove Zone               ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  7.  Edit Server Config (.env) ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  8.  Restart Service           ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  9.  Backup Config             ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  10. Restore Backup            ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  0.  Exit                      ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}╚══════════════════════════════════╝${NC}"
    echo ""
    read -rp "Enter choice [0-10]: " choice

    case $choice in
        1)  show_status;       pause ;;
        2)  add_ip;            pause ;;
        3)  remove_ip;         pause ;;
        4)  replace_ip;        pause ;;
        5)  add_zone;          pause ;;
        6)  remove_zone;       pause ;;
        7)  edit_env;          pause ;;
        8)  restart_service;   pause ;;
        9)  backup_config;     pause ;;
        10) restore_backup;    pause ;;
        0)  echo -e "${GREEN}Goodbye!${NC}"; exit 0 ;;
        *)  echo -e "${RED}Invalid choice.${NC}"; pause ;;
    esac
done
