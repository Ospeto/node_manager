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

# Capacity load balancing
node-throttled = <b>⚡ Node Throttled</b>
    { $name } ({ $address }) removed from { $domain }
    Users: { $users } (threshold: { $threshold })

    DNS record removed to reduce load.

node-restored = <b>✅ Node Restored</b>
    { $name } ({ $address }) re-added to { $domain }
    Users: { $users } (threshold: { $threshold })

    DNS record restored, accepting traffic again.

# Observer status
observer-stale = <b>⚠️ Observer Stale</b>
    Scope: { $scope }
    Observer: { $observer }
    Detail: { $detail }

observer-recovered = <b>✅ Observer Recovered</b>
    Scope: { $scope }
    Observer: { $observer }

observer-extended-stale = <b>🚨 Observer Offline Too Long</b>
    Scope: { $scope }
    Observer: { $observer }
    Detail: { $detail }

observer-mass-freeze = <b>🧊 Mass Degradation Freeze</b>
    Scope: { $scope }
    Observer: { $observer }
    Detail: { $detail }

observer-mass-freeze-cleared = <b>✅ Mass Freeze Cleared</b>
    Scope: { $scope }
    Observer: { $observer }

# Observer decisions
observer-drained = <b>🛑 Whitebox Drained</b>
    { $name } ({ $address }) removed from { $domain }
    Scope: { $scope }
    Reasons: { $reasons }

observer-restored = <b>✅ Whitebox Restored</b>
    { $name } ({ $address }) can return to { $domain }
    Scope: { $scope }
    Reasons: { $reasons }

observer-blocked = <b>🟡 Whitebox Drain Blocked</b>
    { $name } ({ $address }) stayed in { $domain }
    Scope: { $scope }
    Reasons: { $reasons }
    Detail: { $detail }

observer-shadow-drained = <b>🌓 Shadow Drain Candidate</b>
    { $name } ({ $address }) would be removed from { $domain }
    Scope: { $scope }
    Reasons: { $reasons }

observer-shadow-restored = <b>🌓 Shadow Restore Candidate</b>
    { $name } ({ $address }) would return to { $domain }
    Scope: { $scope }
    Reasons: { $reasons }

observer-force-active = <b>🧰 Force Active Override</b>
    { $name } ({ $address }) stayed active for { $domain }
    Scope: { $scope }
    Reasons: { $reasons }

observer-force-drained = <b>🧰 Force Drained Override</b>
    { $name } ({ $address }) was operator-drained for { $domain }
    Scope: { $scope }
    Reasons: { $reasons }
