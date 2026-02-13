# Service lifecycle
service-started = <b>🚀 Service Started</b>
    Monitoring is now active.

service-stopped = <b>🛑 Service Stopped</b>
    Monitoring has been shut down.

# Node status changes
node-became-healthy = <b>✅ Node Online</b>
    { $name } ({ $address }) is now available.

    📊 Nodes: { $online }/{ $total } online, { $disabled } disabled

node-became-unhealthy = <b>❌ Node Offline</b>
    { $name } ({ $address }) is unavailable.
    Reason: { $reason }

    📊 Nodes: { $online }/{ $total } online, { $disabled } disabled

# DNS operations
dns-record-added = <b>📝 DNS Updated</b>
    Added { $ip } → { $domain }

dns-record-removed = <b>🗑️ DNS Removed</b>
    Removed { $ip } from { $domain }

# Errors
dns-operation-error = <b>⚠️ DNS Error</b>
    Failed to { $action } { $ip } for { $domain }
    Error: { $error }

health-check-error = <b>⚠️ Health Check Failed</b>
    Error during health check: { $error }

# Critical states
all-nodes-down = <b>🔴 CRITICAL: All Nodes Down</b>
    All { $total } nodes are unreachable.
    Affected: { $nodes }

    DNS records have been cleared. Immediate attention required.
