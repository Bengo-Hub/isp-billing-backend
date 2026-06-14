# ============================================================================
# CODEVERTEX CONFIGURATION CLEANUP SCRIPT
# ============================================================================
# This script removes all codevertex provisioning configurations
# Run this in WinBox Terminal before fresh provisioning
# ============================================================================
#
# IMPORTANT — HOTSPOT NAME CAVEAT:
# The hotspot SERVER is NOT named "codevertex". The provisioning layer enriches
# the service config and creates the hotspot server with name "ISP-Hotspot"
# (see app/schemas/provisioning.py + app/modules/provisioning/service.py), while
# the hotspot PROFILE is named "codevertex-hsprof". So matching the server by
# `name~"codevertex"` removes NOTHING, and because the (still-present) hotspot is
# bound to codevertex-bridge, the bridge removal in STEP 8 then fails with
# "interface in use". The hotspot server is ALWAYS bound to codevertex-bridge,
# so we remove it BY INTERFACE instead. This mirrors what the backend does in
# generate_configuration_commands() (clean-slate removal by interface).
# ============================================================================

:put "Starting Codevertex configuration cleanup..."

# ============================================================================
# STEP 1: Remove Hotspot Configuration
# ============================================================================
:put "Removing hotspot configurations..."

# Remove hotspot instances BY INTERFACE (the server name varies — "ISP-Hotspot"
# — so name~"codevertex" would miss it and block bridge removal later).
:foreach i in=[/ip/hotspot/find interface~"codevertex"] do={
  /ip/hotspot/remove $i
  :put "  Removed hotspot"
}

# Remove hotspot profiles
:foreach i in=[/ip/hotspot/profile/find name~"codevertex"] do={
  /ip/hotspot/profile/remove $i
  :put "  Removed hotspot profile"
}

# Remove walled garden entries
:foreach i in=[/ip/hotspot/walled-garden/find comment~"codevertex"] do={
  /ip/hotspot/walled-garden/remove $i
  :put "  Removed walled garden entry"
}

# Remove walled garden IP entries
:foreach i in=[/ip/hotspot/walled-garden/ip/find comment~"codevertex"] do={
  /ip/hotspot/walled-garden/ip/remove $i
  :put "  Removed walled garden IP entry"
}

# Remove hotspot users
:foreach i in=[/ip/hotspot/user/find comment~"codevertex"] do={
  /ip/hotspot/user/remove $i
  :put "  Removed hotspot user"
}

# Remove DNS static entries for captive portal detection
:foreach i in=[/ip/dns/static/find comment~"codevertex-captive-portal-detection"] do={
  /ip/dns/static/remove $i
  :put "  Removed DNS static entry for captive portal detection"
}

# Remove DNS redirect NAT rules
:foreach i in=[/ip/firewall/nat/find comment~"codevertex-dns-redirect"] do={
  /ip/firewall/nat/remove $i
  :put "  Removed DNS redirect NAT rule"
}

# Remove SSL certificates for captive portal
:foreach i in=[/certificate/find name~"codevertex"] do={
  /certificate/remove $i
  :put "  Removed SSL certificate"
}

# ============================================================================
# STEP 2: Remove DHCP Configuration
# ============================================================================
:put "Removing DHCP configurations..."

# Remove DHCP servers
:foreach i in=[/ip/dhcp-server/find name~"codevertex"] do={
  /ip/dhcp-server/remove $i
  :put "  Removed DHCP server"
}

# Remove DHCP networks
:foreach i in=[/ip/dhcp-server/network/find comment~"codevertex"] do={
  /ip/dhcp-server/network/remove $i
  :put "  Removed DHCP network"
}

# ============================================================================
# STEP 3: Remove IP Pool
# ============================================================================
:put "Removing IP pools..."

:foreach i in=[/ip/pool/find name~"codevertex"] do={
  /ip/pool/remove $i
  :put "  Removed IP pool"
}

# ============================================================================
# STEP 4: Remove PPPoE Configuration
# ============================================================================
:put "Removing PPPoE configurations..."

# Remove PPPoE servers
:foreach i in=[/interface/pppoe-server/server/find service-name~"codevertex"] do={
  /interface/pppoe-server/server/remove $i
  :put "  Removed PPPoE server"
}

# Remove PPP profiles
:foreach i in=[/ppp/profile/find name~"codevertex"] do={
  /ppp/profile/remove $i
  :put "  Removed PPP profile"
}

# Remove PPP secrets
:foreach i in=[/ppp/secret/find comment~"codevertex"] do={
  /ppp/secret/remove $i
  :put "  Removed PPP secret"
}

# ============================================================================
# STEP 5: Remove Firewall Rules
# ============================================================================
:put "Removing firewall rules..."

# Remove firewall filter rules
:foreach i in=[/ip/firewall/filter/find comment~"codevertex"] do={
  /ip/firewall/filter/remove $i
  :put "  Removed firewall filter rule"
}

# Remove firewall mangle rules
:foreach i in=[/ip/firewall/mangle/find comment~"codevertex"] do={
  /ip/firewall/mangle/remove $i
  :put "  Removed firewall mangle rule"
}

# Remove firewall NAT rules (be careful, check if you have other NAT rules)
:foreach i in=[/ip/firewall/nat/find comment~"codevertex"] do={
  /ip/firewall/nat/remove $i
  :put "  Removed firewall NAT rule"
}

# ============================================================================
# STEP 6: Remove Queue Trees (Bandwidth Management)
# ============================================================================
:put "Removing queue trees..."

# Remove queue trees
:foreach i in=[/queue/tree/find comment~"codevertex"] do={
  /queue/tree/remove $i
  :put "  Removed queue tree"
}

# Remove simple queues
:foreach i in=[/queue/simple/find comment~"codevertex"] do={
  /queue/simple/remove $i
  :put "  Removed simple queue"
}

# Remove queue types
:foreach i in=[/queue/type/find name~"codevertex"] do={
  /queue/type/remove $i
  :put "  Removed queue type"
}

# ============================================================================
# STEP 7: Remove System Configurations
# ============================================================================
:put "Removing system configurations..."

# Remove system scheduler entries.
# NOTE: the polling agent scheduler is name="codevertex-agent" with the comment
# "CodeVertex billing agent ..." (capital C/V). `~` is case-sensitive, so
# comment~"codevertex" does NOT match it — match by NAME so the agent is actually
# stopped. If you leave the agent running it will keep re-creating hotspot/PPP
# users on its next poll, undoing this cleanup.
:foreach i in=[/system/scheduler/find name~"codevertex"] do={
  /system/scheduler/remove $i
  :put "  Removed scheduler entry"
}
:foreach i in=[/system/scheduler/find comment~"codevertex"] do={
  /system/scheduler/remove $i
  :put "  Removed scheduler entry"
}

# Remove the cached agent body file the scheduler imported each tick
:do { /file/remove [find name="cvagent.rsc"] } on-error={}

# Remove remote logging actions
:foreach i in=[/system/logging/action/find name~"codevertex"] do={
  /system/logging/action/remove $i
  :put "  Removed logging action"
}

# ============================================================================
# STEP 8: Remove Bridge Configuration (LAST - has dependencies)
# ============================================================================
:put "Removing bridge configurations..."

# Remove bridge ports FIRST (dependency)
:foreach i in=[/interface/bridge/port/find bridge~"codevertex"] do={
  :local iface [/interface/bridge/port/get $i interface]
  /interface/bridge/port/remove $i
  :put ("  Removed bridge port: " . $iface)
}

# Remove IP addresses from bridge
:foreach i in=[/ip/address/find interface~"codevertex"] do={
  :local addr [/ip/address/get $i address]
  /ip/address/remove $i
  :put ("  Removed IP address: " . $addr)
}

# Remove bridge interface LAST
:foreach i in=[/interface/bridge/find name~"codevertex"] do={
  :local bname [/interface/bridge/get $i name]
  /interface/bridge/remove $i
  :put ("  Removed bridge: " . $bname)
}

# ============================================================================
# STEP 9: Verification - Show What Remains
# ============================================================================
:put ""
:put "============================================================================"
:put "CLEANUP COMPLETE - Verification"
:put "============================================================================"

:put ""
:put "Checking for remaining codevertex configurations..."
:put ""

# Verification checks — each runs independently (no shared variable needed)
:if ([:len [/ip/hotspot/find interface~"codevertex"]] > 0) do={ :put "WARNING: Hotspot instances still exist" }
:if ([:len [/ip/dhcp-server/find name~"codevertex"]] > 0) do={ :put "WARNING: DHCP servers still exist" }
:if ([:len [/ip/pool/find name~"codevertex"]] > 0) do={ :put "WARNING: IP pools still exist" }
:if ([:len [/interface/bridge/find name~"codevertex"]] > 0) do={ :put "WARNING: Bridges still exist" }
:if ([:len [/ip/firewall/filter/find comment~"codevertex"]] > 0) do={ :put "WARNING: Firewall filter rules still exist" }
:if ([:len [/ip/dns/static/find comment~"codevertex"]] > 0) do={ :put "WARNING: DNS static entries still exist" }
:if ([:len [/ip/firewall/nat/find comment~"codevertex"]] > 0) do={ :put "WARNING: NAT rules still exist" }
:if ([:len [/certificate/find name~"codevertex"]] > 0) do={ :put "WARNING: SSL certificates still exist" }
:if ([:len [/queue/tree/find comment~"codevertex"]] > 0) do={ :put "WARNING: Queue trees still exist" }
:if ([:len [/system/scheduler/find name~"codevertex"]] > 0) do={ :put "WARNING: System scheduler entries still exist (polling agent may still be running)" }
:if ([:len [/system/logging/action/find name~"codevertex"]] > 0) do={ :put "WARNING: System logging actions still exist" }

:put ""
:put "If no warnings above, all codevertex configurations have been removed."
:put "You can now provision the router fresh through the web UI."
:put "Make sure ether1 (WAN) has internet access before provisioning."

:put ""
:put "============================================================================"
:put "Current Configuration Summary"
:put "============================================================================"
:put ""

:put "Interfaces:"
/interface/print brief

:put ""
:put "IP Addresses:"
/ip/address/print brief

:put ""
:put "IP Routes:"
/ip/route/print brief

:put ""
:put "DHCP Servers:"
/ip/dhcp-server/print brief

:put ""
:put "Hotspot:"
/ip/hotspot/print brief

:put ""
:put "Queue Trees:"
/queue/tree/print brief

:put ""
:put "System Scheduler:"
/system/scheduler/print brief

:put ""
:put "============================================================================"
:put "CLEANUP SCRIPT FINISHED"
:put "============================================================================"
:put ""
:put "MANUAL CLEANUP COMMANDS (if script fails)"
:put "============================================================================"
:put "If the script fails, you can run these commands manually step by step:"
:put ""
:put "# Remove Hotspot (server by INTERFACE — name is 'ISP-Hotspot', not codevertex)"
:put "/ip/hotspot/remove [find interface~\"codevertex\"]"
:put "/ip/hotspot/profile/remove [find name~\"codevertex\"]"
:put "/ip/hotspot/walled-garden/remove [find comment~\"codevertex\"]"
:put "/ip/hotspot/walled-garden/ip/remove [find comment~\"codevertex\"]"
:put "/ip/hotspot/user/remove [find comment~\"codevertex\"]"
:put "/ip/dns/static/remove [find comment~\"codevertex-captive-portal-detection\"]"
:put "/ip/firewall/nat/remove [find comment~\"codevertex-dns-redirect\"]"
:put "/certificate/remove [find name~\"codevertex\"]"
:put ""
:put "# Remove DHCP"
:put "/ip/dhcp-server/remove [find name~\"codevertex\"]"
:put "/ip/dhcp-server/network/remove [find comment~\"codevertex\"]"
:put ""
:put "# Remove IP Pool"
:put "/ip/pool/remove [find name~\"codevertex\"]"
:put ""
:put "# Remove PPPoE"
:put "/interface/pppoe-server/server/remove [find service-name~\"codevertex\"]"
:put "/ppp/profile/remove [find name~\"codevertex\"]"
:put "/ppp/secret/remove [find comment~\"codevertex\"]"
:put ""
:put "# Remove Firewall Rules"
:put "/ip/firewall/filter/remove [find comment~\"codevertex\"]"
:put "/ip/firewall/mangle/remove [find comment~\"codevertex\"]"
:put "/ip/firewall/nat/remove [find comment~\"codevertex\"]"
:put ""
:put "# Remove Queue Trees"
:put "/queue/tree/remove [find comment~\"codevertex\"]"
:put "/queue/simple/remove [find comment~\"codevertex\"]"
:put "/queue/type/remove [find name~\"codevertex\"]"
:put ""
:put "# Remove System Configs (agent scheduler is name=codevertex-agent — match by NAME)"
:put "/system/scheduler/remove [find name~\"codevertex\"]"
:put "/system/scheduler/remove [find comment~\"codevertex\"]"
:put "/file/remove [find name=\"cvagent.rsc\"]"
:put "/system/logging/action/remove [find name~\"codevertex\"]"
:put ""
:put "# Remove Bridge (LAST)"
:put "/interface/bridge/port/remove [find bridge~\"codevertex\"]"
:put "/ip/address/remove [find interface~\"codevertex\"]"
:put "/interface/bridge/remove [find name~\"codevertex\"]"
:put ""
:put "============================================================================"