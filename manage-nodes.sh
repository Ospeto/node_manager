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
DIM='\033[2m'
NC='\033[0m'

# Detect OS for portable sed
if [[ "$(uname -s)" == "Darwin" ]]; then
    SED_INPLACE=(-i '')
else
    SED_INPLACE=(-i)
fi

# ──────────────────────────────────────────────
#  yq setup
# ──────────────────────────────────────────────
ensure_yq() {
    # 1) Check system yq
    if command -v yq &>/dev/null; then
        if yq --version 2>&1 | grep -qi 'mikefarah\|github.com/mikefarah'; then
            YQ_BINARY="yq"
            return
        fi
    fi

    # 2) Check local binary
    if [ -f "$SCRIPT_DIR/yq" ]; then
        if "$SCRIPT_DIR/yq" --version &>/dev/null; then
            YQ_BINARY="$SCRIPT_DIR/yq"
            return
        else
            echo -e "${YELLOW}Existing yq binary is broken, re-downloading...${NC}"
            rm -f "$SCRIPT_DIR/yq"
        fi
    fi

    # 3) Download
    echo -e "${YELLOW}yq not found. Downloading...${NC}"
    local os arch
    os=$(uname -s | tr '[:upper:]' '[:lower:]')
    arch=$(uname -m)
    case "$arch" in
        x86_64)  arch="amd64" ;;
        aarch64|arm64) arch="arm64" ;;
        *)
            echo -e "${RED}Unsupported architecture: $arch${NC}"
            echo -e "${RED}Install yq manually: https://github.com/mikefarah/yq${NC}"
            exit 1 ;;
    esac

    if ! curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_${os}_${arch}" -o "$SCRIPT_DIR/yq"; then
        echo -e "${RED}Download failed. Install yq manually.${NC}"
        exit 1
    fi
    chmod +x "$SCRIPT_DIR/yq"

    if ! "$SCRIPT_DIR/yq" --version &>/dev/null; then
        rm -f "$SCRIPT_DIR/yq"
        echo -e "${RED}Downloaded binary incompatible. Install yq manually.${NC}"
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
    # Prune old backups (keep last 20 files)
    ls -t "$BACKUP_DIR"/* 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
}

pause() {
    echo ""
    read -rp "Press [Enter] to continue..."
}

check_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}Config file not found: $CONFIG_FILE${NC}"
        echo -e "${YELLOW}Run: cp config.example.yml config.yml${NC}"
        return 1
    fi
}

check_env() {
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}.env file not found: $ENV_FILE${NC}"
        echo -e "${YELLOW}Run: cp .env.example .env${NC}"
        return 1
    fi
}

# ──────────────────────────────────────────────
#  Interactive pickers
#  ALL UI output goes to >&2 so only the
#  selected value goes to stdout for capture.
# ──────────────────────────────────────────────
pick_domain() {
    local -a domains=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && domains+=("$line")
    done < <($YQ_BINARY -r '.domains[].domain' "$CONFIG_FILE" 2>/dev/null)

    if [[ ${#domains[@]} -eq 0 ]]; then
        echo -e "${RED}No domains found in config.${NC}" >&2
        return 1
    fi

    if [[ ${#domains[@]} -eq 1 ]]; then
        echo -e "${DIM}Auto-selected domain: ${BOLD}${domains[0]}${NC}" >&2
        echo "${domains[0]}"
        return 0
    fi

    echo -e "${CYAN}Select domain:${NC}" >&2
    local i
    for i in "${!domains[@]}"; do
        echo -e "  ${BOLD}$((i+1)))${NC} ${domains[$i]}" >&2
    done
    while true; do
        read -rp "Domain [1-${#domains[@]}]: " num
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#domains[@]} )); then
            echo "${domains[$((num-1))]}"
            return 0
        fi
        echo -e "${RED}Invalid. Enter a number 1-${#domains[@]}.${NC}" >&2
    done
}

pick_zone() {
    local domain="$1"
    local -a zones=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && zones+=("$line")
    done < <($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\") | .zones[].name" "$CONFIG_FILE" 2>/dev/null)

    if [[ ${#zones[@]} -eq 0 ]]; then
        echo -e "${RED}No zones found for $domain.${NC}" >&2
        return 1
    fi

    if [[ ${#zones[@]} -eq 1 ]]; then
        echo -e "${DIM}Auto-selected zone: ${BOLD}${zones[0]}${NC}" >&2
        echo "${zones[0]}"
        return 0
    fi

    echo -e "${CYAN}Select zone in ${BOLD}$domain${NC}${CYAN}:${NC}" >&2
    local i
    for i in "${!zones[@]}"; do
        # Show zone IPs inline for context
        local ips
        ips=$($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"${zones[$i]}\").ips | join(\", \")" "$CONFIG_FILE" 2>/dev/null)
        echo -e "  ${BOLD}$((i+1)))${NC} ${zones[$i]}.$domain  ${DIM}[${ips}]${NC}" >&2
    done
    while true; do
        read -rp "Zone [1-${#zones[@]}]: " num
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#zones[@]} )); then
            echo "${zones[$((num-1))]}"
            return 0
        fi
        echo -e "${RED}Invalid. Enter a number 1-${#zones[@]}.${NC}" >&2
    done
}

pick_ip() {
    local domain="$1" zone="$2"
    local -a ips=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && ips+=("$line")
    done < <($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[]" "$CONFIG_FILE" 2>/dev/null)

    if [[ ${#ips[@]} -eq 0 ]]; then
        echo -e "${RED}No IPs in $zone.$domain.${NC}" >&2
        return 1
    fi

    echo -e "${CYAN}Select IP in ${BOLD}$zone.$domain${NC}${CYAN}:${NC}" >&2
    local i
    for i in "${!ips[@]}"; do
        echo -e "  ${BOLD}$((i+1)))${NC} ${ips[$i]}" >&2
    done
    while true; do
        read -rp "IP [1-${#ips[@]}]: " num
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#ips[@]} )); then
            echo "${ips[$((num-1))]}"
            return 0
        fi
        echo -e "${RED}Invalid. Enter a number 1-${#ips[@]}.${NC}" >&2
    done
}

# Show current IPs for a zone (for display)
show_zone_ips() {
    local domain="$1" zone="$2"
    local -a ips=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && ips+=("$line")
    done < <($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[]" "$CONFIG_FILE" 2>/dev/null)

    if [[ ${#ips[@]} -eq 0 ]]; then
        echo -e "  ${DIM}(no IPs)${NC}"
    else
        for ip in "${ips[@]}"; do
            echo -e "  ${GREEN}•${NC} $ip"
        done
    fi
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
        echo -e "\n  ${BOLD}${CYAN}📦 $domain${NC}"

        local zone_count
        zone_count=$($YQ_BINARY ".domains[$d].zones | length" "$CONFIG_FILE")

        for (( z=0; z<zone_count; z++ )); do
            local name ttl proxied
            name=$($YQ_BINARY -r ".domains[$d].zones[$z].name" "$CONFIG_FILE")
            ttl=$($YQ_BINARY -r ".domains[$d].zones[$z].ttl" "$CONFIG_FILE")
            proxied=$($YQ_BINARY -r ".domains[$d].zones[$z].proxied" "$CONFIG_FILE")

            echo -e "    ${GREEN}🌐 $name.$domain${NC}  ${DIM}TTL=$ttl  Proxied=$proxied${NC}"

            local ip_count
            ip_count=$($YQ_BINARY ".domains[$d].zones[$z].ips | length" "$CONFIG_FILE")
            for (( i=0; i<ip_count; i++ )); do
                local ip
                ip=$($YQ_BINARY -r ".domains[$d].zones[$z].ips[$i]" "$CONFIG_FILE")
                echo "       └─ $ip"
            done
        done
    done
    echo ""
}

# ──────────────────────────────────────────────
#  2. Add IP  (supports adding multiple at once)
# ──────────────────────────────────────────────
add_ip() {
    echo -e "${BOLD}${BLUE}=== Add Node IP ===${NC}"
    check_config || return

    # Pick domain & zone
    local domain zone
    domain=$(pick_domain) || return
    zone=$(pick_zone "$domain") || return

    # Show current IPs
    echo -e "\n${CYAN}Current IPs in ${BOLD}$zone.$domain${NC}${CYAN}:${NC}"
    show_zone_ips "$domain" "$zone"

    echo -e "\n${YELLOW}Enter IP address(es) to add.${NC}"
    echo -e "${DIM}You can enter multiple IPs separated by spaces, or one per line.${NC}"
    echo -e "${DIM}Type 'done' or press Enter on empty line when finished.${NC}"

    local -a new_ips=()
    while true; do
        read -rp "> " input
        # Empty line or "done" = finished
        [[ -z "$input" || "$input" == "done" ]] && break

        # Split by spaces/commas
        for ip in $input; do
            ip=$(echo "$ip" | tr -d ',' | xargs)
            [[ -z "$ip" ]] && continue

            # Basic IP format check
            if ! [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                echo -e "${RED}  ✗ '$ip' is not a valid IPv4 address, skipped.${NC}"
                continue
            fi

            # Duplicate check against existing
            local existing
            existing=$($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[]" "$CONFIG_FILE" 2>/dev/null)
            if echo "$existing" | grep -qxF "$ip"; then
                echo -e "${YELLOW}  ⚠ $ip already exists, skipped.${NC}"
                continue
            fi

            # Duplicate check against what we're about to add
            local already_queued=false
            for queued in "${new_ips[@]}"; do
                [[ "$queued" == "$ip" ]] && already_queued=true && break
            done
            if $already_queued; then
                echo -e "${YELLOW}  ⚠ $ip already queued, skipped.${NC}"
                continue
            fi

            new_ips+=("$ip")
            echo -e "${GREEN}  ✓ $ip queued${NC}"
        done
    done

    if [[ ${#new_ips[@]} -eq 0 ]]; then
        echo -e "${YELLOW}No IPs to add.${NC}"
        return
    fi

    # Confirm
    echo -e "\n${CYAN}Will add ${BOLD}${#new_ips[@]}${NC}${CYAN} IP(s) to ${BOLD}$zone.$domain${NC}${CYAN}:${NC}"
    for ip in "${new_ips[@]}"; do
        echo -e "  ${GREEN}+ $ip${NC}"
    done
    read -rp "Proceed? (Y/n): " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && { echo "Cancelled."; return; }

    create_backup

    # Add each IP
    for ip in "${new_ips[@]}"; do
        $YQ_BINARY -i "(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips) += [\"$ip\"]" "$CONFIG_FILE"
    done

    echo -e "\n${GREEN}✅ Added ${#new_ips[@]} IP(s) to $zone.$domain${NC}"
    echo -e "\n${CYAN}Updated IPs:${NC}"
    show_zone_ips "$domain" "$zone"
}

# ──────────────────────────────────────────────
#  3. Remove IP  (supports removing multiple)
# ──────────────────────────────────────────────
remove_ip() {
    echo -e "${BOLD}${BLUE}=== Remove Node IP ===${NC}"
    check_config || return

    local domain zone
    domain=$(pick_domain) || return
    zone=$(pick_zone "$domain") || return

    # Read all IPs into array
    local -a ips=()
    while IFS= read -r line; do
        [[ -n "$line" ]] && ips+=("$line")
    done < <($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[]" "$CONFIG_FILE" 2>/dev/null)

    if [[ ${#ips[@]} -eq 0 ]]; then
        echo -e "${RED}No IPs in $zone.$domain.${NC}"
        return
    fi

    echo -e "\n${CYAN}Current IPs in ${BOLD}$zone.$domain${NC}${CYAN}:${NC}"
    local i
    for i in "${!ips[@]}"; do
        echo -e "  ${BOLD}$((i+1)))${NC} ${ips[$i]}"
    done

    echo -e "\n${YELLOW}Enter the number(s) of IPs to remove.${NC}"
    echo -e "${DIM}Separate multiple with spaces (e.g. 1 3 4), or 'all' to remove all.${NC}"
    read -rp "> " selection

    local -a to_remove=()

    if [[ "$selection" == "all" ]]; then
        to_remove=("${ips[@]}")
    else
        for num in $selection; do
            if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#ips[@]} )); then
                to_remove+=("${ips[$((num-1))]}")
            else
                echo -e "${RED}  ✗ Invalid number: $num (skipped)${NC}"
            fi
        done
    fi

    if [[ ${#to_remove[@]} -eq 0 ]]; then
        echo -e "${YELLOW}Nothing selected.${NC}"
        return
    fi

    # Warn if removing all
    local remaining=$(( ${#ips[@]} - ${#to_remove[@]} ))
    if [[ $remaining -eq 0 ]]; then
        echo -e "${RED}⚠  WARNING: This will remove ALL IPs from $zone.$domain!${NC}"
    fi

    echo -e "\n${CYAN}Will remove ${BOLD}${#to_remove[@]}${NC}${CYAN} IP(s):${NC}"
    for ip in "${to_remove[@]}"; do
        echo -e "  ${RED}- $ip${NC}"
    done
    read -rp "Proceed? (y/N): " confirm
    [[ "$confirm" != "y" && "$confirm" != "Y" ]] && { echo "Cancelled."; return; }

    create_backup

    for ip in "${to_remove[@]}"; do
        $YQ_BINARY -i "del(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[] | select(. == \"$ip\"))" "$CONFIG_FILE"
    done

    echo -e "\n${GREEN}✅ Removed ${#to_remove[@]} IP(s) from $zone.$domain${NC}"
    echo -e "\n${CYAN}Remaining IPs:${NC}"
    show_zone_ips "$domain" "$zone"
}

# ──────────────────────────────────────────────
#  4. Replace IP
# ──────────────────────────────────────────────
replace_ip() {
    echo -e "${BOLD}${BLUE}=== Replace Node IP ===${NC}"
    check_config || return

    local domain zone old_ip new_ip
    domain=$(pick_domain) || return
    zone=$(pick_zone "$domain") || return

    echo -e "\n${CYAN}Current IPs in ${BOLD}$zone.$domain${NC}${CYAN}:${NC}"
    show_zone_ips "$domain" "$zone"

    old_ip=$(pick_ip "$domain" "$zone") || return

    read -rp "New IP to replace $old_ip: " new_ip
    if [[ -z "$new_ip" ]]; then
        echo -e "${RED}IP cannot be empty.${NC}"
        return
    fi
    if ! [[ "$new_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo -e "${RED}'$new_ip' is not a valid IPv4 address.${NC}"
        return
    fi

    echo -e "\n${CYAN}Replace: ${RED}$old_ip${NC} → ${GREEN}$new_ip${NC}"
    read -rp "Proceed? (Y/n): " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && { echo "Cancelled."; return; }

    create_backup
    $YQ_BINARY -i "(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\").ips[] | select(. == \"$old_ip\")) = \"$new_ip\"" "$CONFIG_FILE"

    echo -e "\n${GREEN}✅ Replaced $old_ip → $new_ip in $zone.$domain${NC}"
    echo -e "\n${CYAN}Updated IPs:${NC}"
    show_zone_ips "$domain" "$zone"
}

# ──────────────────────────────────────────────
#  5. Add Zone
# ──────────────────────────────────────────────
add_zone() {
    echo -e "${BOLD}${BLUE}=== Add New Zone ===${NC}"
    check_config || return

    local domain zone_name ttl proxied
    domain=$(pick_domain) || return

    read -rp "New zone name (subdomain): " zone_name
    if [[ -z "$zone_name" ]]; then
        echo -e "${RED}Zone name cannot be empty.${NC}"
        return
    fi

    # Check duplicate
    local existing
    existing=$($YQ_BINARY -r ".domains[] | select(.domain == \"$domain\") | .zones[].name" "$CONFIG_FILE" 2>/dev/null)
    if echo "$existing" | grep -qxF "$zone_name"; then
        echo -e "${RED}Zone '$zone_name' already exists in $domain.${NC}"
        return
    fi

    read -rp "TTL [60]: " ttl
    ttl=${ttl:-60}
    read -rp "Proxied? true/false [false]: " proxied
    proxied=${proxied:-false}

    echo -e "\n${YELLOW}Enter IP address(es) for this zone.${NC}"
    echo -e "${DIM}Separate multiple with spaces, or one per line. Empty line to finish.${NC}"

    local -a zone_ips=()
    while true; do
        read -rp "> " input
        [[ -z "$input" || "$input" == "done" ]] && break
        for ip in $input; do
            ip=$(echo "$ip" | tr -d ',' | xargs)
            [[ -z "$ip" ]] && continue
            if ! [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                echo -e "${RED}  ✗ '$ip' invalid, skipped.${NC}"
                continue
            fi
            zone_ips+=("$ip")
            echo -e "${GREEN}  ✓ $ip${NC}"
        done
    done

    if [[ ${#zone_ips[@]} -eq 0 ]]; then
        echo -e "${RED}At least one IP is required.${NC}"
        return
    fi

    # Build the IPs array as a yq expression
    local ips_json="["
    for i in "${!zone_ips[@]}"; do
        [[ $i -gt 0 ]] && ips_json+=","
        ips_json+="\"${zone_ips[$i]}\""
    done
    ips_json+="]"

    echo -e "\n${CYAN}Will create zone:${NC}"
    echo -e "  ${BOLD}$zone_name.$domain${NC}  TTL=$ttl  Proxied=$proxied"
    for ip in "${zone_ips[@]}"; do
        echo -e "  ${GREEN}+ $ip${NC}"
    done
    read -rp "Proceed? (Y/n): " confirm
    [[ "$confirm" == "n" || "$confirm" == "N" ]] && { echo "Cancelled."; return; }

    create_backup
    $YQ_BINARY -i "
        (.domains[] | select(.domain == \"$domain\").zones) += [{
            \"name\": \"$zone_name\",
            \"ttl\": $ttl,
            \"proxied\": $proxied,
            \"ips\": $ips_json
        }]
    " "$CONFIG_FILE"

    echo -e "\n${GREEN}✅ Created zone $zone_name.$domain${NC}"
}

# ──────────────────────────────────────────────
#  6. Remove Zone
# ──────────────────────────────────────────────
remove_zone() {
    echo -e "${BOLD}${BLUE}=== Remove Zone ===${NC}"
    check_config || return

    local domain zone
    domain=$(pick_domain) || return
    zone=$(pick_zone "$domain") || return

    echo -e "\n${RED}⚠  This will remove zone '$zone' and ALL its IPs:${NC}"
    show_zone_ips "$domain" "$zone"
    read -rp "Type 'yes' to confirm: " confirm
    [[ "$confirm" != "yes" ]] && { echo "Cancelled."; return; }

    create_backup
    $YQ_BINARY -i "del(.domains[] | select(.domain == \"$domain\").zones[] | select(.name == \"$zone\"))" "$CONFIG_FILE"
    echo -e "\n${GREEN}✅ Removed zone $zone from $domain${NC}"
}

# ──────────────────────────────────────────────
#  7. Edit .env
# ──────────────────────────────────────────────
edit_env() {
    echo -e "${BOLD}${BLUE}=== Edit Server Config (.env) ===${NC}"
    check_env || return

    # Show current
    echo -e "${CYAN}Current values:${NC}"
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        if [[ "$key" =~ (KEY|TOKEN|SECRET) ]]; then
            echo -e "  $key = ${YELLOW}****${NC}"
        else
            echo -e "  $key = $value"
        fi
    done < "$ENV_FILE"
    echo ""

    local options=("REMNAWAVE_API_URL" "REMNAWAVE_API_KEY" "CLOUDFLARE_API_TOKEN" "TELEGRAM_BOT_TOKEN" "TELEGRAM_CHAT_ID" "TELEGRAM_TOPIC_ID" "TIMEZONE" "TIME_FORMAT" "Back")

    echo -e "${CYAN}Select variable to change:${NC}"
    local i
    for i in "${!options[@]}"; do
        echo -e "  ${BOLD}$((i+1)))${NC} ${options[$i]}"
    done
    read -rp "Choice [1-${#options[@]}]: " num

    if ! [[ "$num" =~ ^[0-9]+$ ]] || (( num < 1 || num > ${#options[@]} )); then
        echo -e "${RED}Invalid.${NC}"
        return
    fi

    local opt="${options[$((num-1))]}"
    [[ "$opt" == "Back" ]] && return

    local current
    current=$(grep "^${opt}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2-)
    echo -e "  Current: ${YELLOW}${current:-<not set>}${NC}"
    read -rp "  New value: " new_val

    if [[ -z "$new_val" ]]; then
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
}

# ──────────────────────────────────────────────
#  8. Restart Service
# ──────────────────────────────────────────────
restart_service() {
    echo -e "${BOLD}${BLUE}=== Restart Service ===${NC}"
    if ! command -v docker &>/dev/null; then
        echo -e "${RED}Docker not found.${NC}"
        return
    fi
    echo -e "${YELLOW}Restarting...${NC}"
    if docker compose -f "$SCRIPT_DIR/docker-compose.yml" restart; then
        echo -e "${GREEN}✅ Service restarted.${NC}"
    else
        echo -e "${RED}Failed. Check docker compose logs.${NC}"
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
    ls -lt "$BACKUP_DIR"/ 2>/dev/null | head -10
}

# ──────────────────────────────────────────────
#  10. Restore Backup
# ──────────────────────────────────────────────
restore_backup() {
    echo -e "${BOLD}${BLUE}=== Restore Backup ===${NC}"
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo -e "${RED}No backups found.${NC}"
        return
    fi

    # Config backups
    local -a cfg_backups=()
    while IFS= read -r f; do
        [[ -n "$f" ]] && cfg_backups+=("$f")
    done < <(ls -t "$BACKUP_DIR" 2>/dev/null | grep "config.yml")

    if [[ ${#cfg_backups[@]} -gt 0 ]]; then
        echo -e "\n${CYAN}Config backups:${NC}"
        for i in "${!cfg_backups[@]}"; do
            echo -e "  ${BOLD}$((i+1)))${NC} ${cfg_backups[$i]}"
        done
        echo -e "  ${BOLD}$((${#cfg_backups[@]}+1)))${NC} Skip"
        read -rp "Choice: " num
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#cfg_backups[@]} )); then
            cp "$BACKUP_DIR/${cfg_backups[$((num-1))]}" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Restored config.yml${NC}"
        fi
    fi

    # .env backups
    local -a env_backups=()
    while IFS= read -r f; do
        [[ -n "$f" ]] && env_backups+=("$f")
    done < <(ls -t "$BACKUP_DIR" 2>/dev/null | grep ".env")

    if [[ ${#env_backups[@]} -gt 0 ]]; then
        echo -e "\n${CYAN}.env backups:${NC}"
        for i in "${!env_backups[@]}"; do
            echo -e "  ${BOLD}$((i+1)))${NC} ${env_backups[$i]}"
        done
        echo -e "  ${BOLD}$((${#env_backups[@]}+1)))${NC} Skip"
        read -rp "Choice: " num
        if [[ "$num" =~ ^[0-9]+$ ]] && (( num >= 1 && num <= ${#env_backups[@]} )); then
            cp "$BACKUP_DIR/${env_backups[$((num-1))]}" "$ENV_FILE"
            echo -e "${GREEN}✅ Restored .env${NC}"
        fi
    fi
}

# ──────────────────────────────────────────────
#  11. Load Balancing Settings
# ──────────────────────────────────────────────
load_balancing() {
    echo -e "${BOLD}${BLUE}=== Load Balancing Settings ===${NC}"
    check_config || return

    # Read current state
    local lb_enabled
    lb_enabled=$($YQ_BINARY -r '.load-balancing.enabled // false' "$CONFIG_FILE" 2>/dev/null)

    if [[ "$lb_enabled" == "true" ]]; then
        echo -e "  Status:        ${GREEN}${BOLD}ENABLED${NC}"
    else
        echo -e "  Status:        ${RED}${BOLD}DISABLED${NC}"
    fi

    local max_users recover_users min_nodes
    max_users=$($YQ_BINARY -r '.load-balancing.max-users-per-node // 50' "$CONFIG_FILE" 2>/dev/null)
    recover_users=$($YQ_BINARY -r '.load-balancing.recover-users-per-node // 30' "$CONFIG_FILE" 2>/dev/null)
    min_nodes=$($YQ_BINARY -r '.load-balancing.min-active-nodes // 1' "$CONFIG_FILE" 2>/dev/null)

    echo -e "  Max users:     ${CYAN}$max_users${NC}  ${DIM}(remove DNS above this)${NC}"
    echo -e "  Recover users: ${CYAN}$recover_users${NC}  ${DIM}(re-add DNS below this)${NC}"
    echo -e "  Min active:    ${CYAN}$min_nodes${NC}  ${DIM}(always keep this many nodes)${NC}"
    echo ""

    echo -e "${CYAN}Options:${NC}"
    echo -e "  ${BOLD}1)${NC} Toggle ON/OFF"
    echo -e "  ${BOLD}2)${NC} Set max users per node"
    echo -e "  ${BOLD}3)${NC} Set recover users per node"
    echo -e "  ${BOLD}4)${NC} Set min active nodes"
    echo -e "  ${BOLD}5)${NC} Back"
    read -rp "Choice [1-5]: " opt

    case $opt in
        1)
            create_backup
            if [[ "$lb_enabled" == "true" ]]; then
                $YQ_BINARY -i '.load-balancing.enabled = false' "$CONFIG_FILE"
                echo -e "${RED}⏸  Load balancing DISABLED${NC}"
            else
                # Ensure the section exists
                $YQ_BINARY -i '.load-balancing.enabled = true' "$CONFIG_FILE"
                $YQ_BINARY -i '.load-balancing.max-users-per-node |= (. // 50)' "$CONFIG_FILE"
                $YQ_BINARY -i '.load-balancing.recover-users-per-node |= (. // 30)' "$CONFIG_FILE"
                $YQ_BINARY -i '.load-balancing.min-active-nodes |= (. // 1)' "$CONFIG_FILE"
                echo -e "${GREEN}▶  Load balancing ENABLED${NC}"
            fi
            ;;
        2)
            read -rp "Max users per node [$max_users]: " val
            val=${val:-$max_users}
            create_backup
            $YQ_BINARY -i ".load-balancing.max-users-per-node = $val" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Max users set to $val${NC}"
            ;;
        3)
            read -rp "Recover users per node [$recover_users]: " val
            val=${val:-$recover_users}
            create_backup
            $YQ_BINARY -i ".load-balancing.recover-users-per-node = $val" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Recover users set to $val${NC}"
            ;;
        4)
            read -rp "Min active nodes [$min_nodes]: " val
            val=${val:-$min_nodes}
            create_backup
            $YQ_BINARY -i ".load-balancing.min-active-nodes = $val" "$CONFIG_FILE"
            echo -e "${GREEN}✅ Min active nodes set to $val${NC}"
            ;;
        5) return ;;
        *) echo -e "${RED}Invalid.${NC}" ;;
    esac
}

# ──────────────────────────────────────────────
#  Main
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
    echo -e "${BOLD}${BLUE}║${NC}  11. Load Balancing Settings    ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}║${NC}  0.  Exit                      ${BOLD}${BLUE}║${NC}"
    echo -e "${BOLD}${BLUE}╚══════════════════════════════════╝${NC}"
    echo ""
    read -rp "Enter choice [0-11]: " choice

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
        11) load_balancing;    pause ;;
        0)  echo -e "${GREEN}Goodbye!${NC}"; exit 0 ;;
        *)  echo -e "${RED}Invalid choice.${NC}"; pause ;;
    esac
done
