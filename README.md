<p align="center">
  <img src="https://raw.githubusercontent.com/hteppl/remnawave-cloudflare-nodes/master/.github/images/logo.png" alt="remnawave-cloudflare-nodes" width="800px">
</p>

## remnawave-cloudflare-nodes

<p align="left">
  <a href="https://github.com/hteppl/remnawave-cloudflare-nodes/releases/"><img src="https://img.shields.io/github/v/release/hteppl/remnawave-cloudflare-nodes.svg" alt="Release"></a>
  <a href="https://hub.docker.com/r/hteppl/remnawave-cloudflare-nodes/"><img src="https://img.shields.io/badge/DockerHub-remnawave--cloudflare--nodes-blue" alt="DockerHub"></a>
  <a href="https://github.com/hteppl/remnawave-cloudflare-nodes/actions"><img src="https://img.shields.io/github/actions/workflow/status/hteppl/remnawave-cloudflare-nodes/dockerhub-publish.yaml" alt="Build"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="Python 3.12"></a>
  <a href="https://opensource.org/licenses/GPL-3.0"><img src="https://img.shields.io/badge/license-GPLv3-green.svg" alt="License: GPL v3"></a>
</p>

English | [Русский](README.ru.md)

Automatically manage Cloudflare DNS records based on Remnawave (https://docs.rw) node health status.

## Features

- **Automatic Health Monitoring** - Continuously monitors node health status via Remnawave API
- **Dynamic DNS Management** - Adds DNS records for healthy nodes, removes records for unhealthy ones
- **Auto Zone Discovery** - Automatically discovers Cloudflare zone IDs from domain names
- **Multi-Domain Support** - Manage multiple domains with multiple DNS zones each
- **Telegram Notifications** - Real-time alerts for node status changes, DNS updates, and critical events
- **Configurable Intervals** - Set custom health check intervals
- **Docker Ready** - Easy deployment with Docker and Docker Compose

## Prerequisites

Before you begin, ensure you have the following:

- **Remnawave Panel** with nodes configured
- **Remnawave API Token** - Generate from your Remnawave panel settings
- **Cloudflare Account** with DNS zones configured
- **Cloudflare API Token** - Create with DNS edit permissions

## Configuration

Copy [`.env.example`](.env.example) to `.env` and fill in your values:

```env
# Remnawave panel URL and API key
REMNAWAVE_API_URL=https://panel.example.com
REMNAWAVE_API_KEY=remnawave_api_key

# Cloudflare token with DNS edit permissions
CLOUDFLARE_API_TOKEN=cloudflare_api_token

# Telegram bot token from @BotFather
TELEGRAM_BOT_TOKEN=your_bot_token_here
# Chat ID (get from @username_to_id_bot)
TELEGRAM_CHAT_ID=123456789
# Forum topic ID (leave empty for regular chats)
TELEGRAM_TOPIC_ID=

# Timezone (e.g. UTC, Europe/Moscow, America/New_York)
TIMEZONE=UTC
# Time format: %d-day, %m-month, %Y-year, %H-hour, %M-min, %S-sec
TIME_FORMAT="%d.%m.%Y %H:%M:%S"
```

Copy [`config.example.yml`](config.example.yml) to `config.yml` and configure your domains:

```yaml
remnawave:
  # Health check interval in seconds
  check-interval: 30

# Domains and DNS zones to manage
domains:
  - domain: example1.com
    zones:
      - name: s1          # Creates s1.example1.com
        ttl: 60           # Record TTL in seconds
        proxied: false    # Cloudflare proxy (orange cloud)
        ips:              # Node IPs to monitor
          - 1.2.3.4
          - 5.6.7.8

  - domain: example2.com
    zones:
      - name: s2
        ttl: 60
        proxied: false
        ips:
          - 13.14.15.16
          - 17.18.19.20

logging:
  level: INFO # DEBUG, INFO, WARNING, ERROR, CRITICAL

telegram:
  enabled: false
  locale: en  # en, ru
  notify:
    node_changes: true  # Node online/offline
    dns_changes: true   # DNS record changes
    errors: true        # Error alerts
    critical: true      # All nodes down alert
```

### Configuration Reference

| Variable               | Description                                    | Default           | Required |
|------------------------|------------------------------------------------|-------------------|----------|
| `REMNAWAVE_API_URL`    | Remnawave API endpoint to fetch nodes from     | -                 | Yes      |
| `REMNAWAVE_API_KEY`    | API authentication token                       | -                 | Yes      |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token with DNS edit permissions | -                 | Yes      |
| `TELEGRAM_BOT_TOKEN`   | Telegram bot token from @BotFather             | -                 | No       |
| `TELEGRAM_CHAT_ID`     | Chat ID for notifications                      | -                 | No       |
| `TELEGRAM_TOPIC_ID`    | Forum topic ID (for supergroups with topics)   | -                 | No       |
| `TIMEZONE`             | Timezone for timestamps (e.g. Europe/Moscow)   | UTC               | No       |
| `TIME_FORMAT`          | Time format for timestamps                     | %d.%m.%Y %H:%M:%S | No       |
| `check-interval`       | Interval in seconds between health checks      | 30                | No       |
| `logging.level`        | Log level (DEBUG, INFO, WARNING, ERROR)        | INFO              | No       |

## Installation

### Docker (recommended)

1. Create the docker-compose.yml:

```yaml
services:
  remnawave-cloudflare-nodes:
    image: hteppl/remnawave-cloudflare-nodes:latest
    container_name: remnawave-cloudflare-nodes
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./config.yml:/app/config.yml:ro
      - ./logs:/app/logs
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "3"
```

2. Create and configure your environment file:

```bash
cp .env.example .env
nano .env  # or use your preferred editor
```

3. Start the container:

```bash
docker compose up -d && docker compose logs -f
```

### Manual Installation

1. Clone the repository:

```bash
git clone https://github.com/hteppl/remnawave-cloudflare-nodes.git
cd remnawave-cloudflare-nodes
```

2. Create a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create and configure your environment file:

```bash
cp .env.example .env
```

5. Run the application:

```bash
python -m src
```

## How It Works

1. **Initial Fetch** - On startup, the service fetches all nodes from the Remnawave API and auto-discovers
   Cloudflare zone IDs

2. **Health Evaluation** - Based on node status, determines which nodes are healthy:
   - Node must be connected (`is_connected = true`)
   - Node must not be disabled (`is_disabled = false`)
   - Node must have Xray installed (`xray_version` is not null)

3. **DNS Synchronization** - For each configured zone:
   - Adds DNS A records for IPs that are both configured AND healthy
   - Removes DNS A records for IPs that are no longer healthy

4. **Continuous Updates** - The service polls the Remnawave API at the configured interval (`check-interval`) and
   updates DNS records

The service manages DNS records dynamically, ensuring only healthy nodes are included in DNS resolution.

## Telegram Notifications

The service can send real-time notifications to Telegram when events occur.

### Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and get the token
2. Get your chat ID from [@username_to_id_bot](https://t.me/username_to_id_bot)
3. Add the bot to your chat/group
4. Configure environment variables:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=123456789
TELEGRAM_TOPIC_ID=              # Optional: for forum topics
```

5. Enable in `config.yml`:

```yaml
telegram:
  enabled: true
  locale: en  # en, ru
```

### Notification Types

| Event             | Description           | Example                                                                                 |
|-------------------|-----------------------|-----------------------------------------------------------------------------------------|
| **Node Online**   | Node became healthy   | ✅ Node Online<br>node-1 (1.2.3.4) is now available.<br>📊 Nodes: 5/6 online, 0 disabled |
| **Node Offline**  | Node became unhealthy | ❌ Node Offline<br>node-1 (1.2.3.4) is unavailable.<br>Reason: disconnected              |
| **DNS Updated**   | DNS record added      | 📝 DNS Updated<br>Added 1.2.3.4 → s1.example.com                                        |
| **DNS Removed**   | DNS record removed    | 🗑️ DNS Removed<br>Removed 1.2.3.4 from s1.example.com                                  |
| **Critical**      | All nodes down        | 🔴 CRITICAL: All Nodes Down<br>All 5 nodes are unreachable.                             |
| **Service Start** | Monitoring started    | 🚀 Service Started                                                                      |
| **Service Stop**  | Monitoring stopped    | 🛑 Service Stopped                                                                      |

### Configure Notifications

You can enable/disable specific notification types:

```yaml
telegram:
  enabled: true
  locale: en
  notify:
    node_changes: true  # Node online/offline events
    dns_changes: true   # DNS record add/remove
    errors: true        # Error alerts
    critical: true      # All nodes down alert
```

### Logs

Monitor logs to diagnose issues:

```bash
# Docker
docker compose logs -f

# Manual
# Logs are output to stdout and logs/app.log
```

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
