# MikroTik RouterOS v6 vs v7 Command Syntax Comparison

## Comprehensive Reference for Automated Provisioning

This document compiles all researched differences between MikroTik RouterOS v6 and v7 command syntax, focusing on what affects automated provisioning scripts and ISP billing platform integration.

---

## 1. Command Path Format

### The Core Difference

Both RouterOS v6 and v7 accept **two path separator styles** in the CLI:

| Style | Example | Supported In |
|-------|---------|-------------|
| **Space-separated** | `/ip hotspot user add ...` | v6 and v7 |
| **Slash-separated** | `/ip/hotspot/user/add ...` | v6 and v7 |

**Key insight**: Both formats work in both versions. The official MikroTik documentation states: *"each word in the path can be separated by space or by '/'"*. However:

- **v6 documentation and examples** predominantly use the **space-separated** style: `/ip hotspot`, `/interface bridge`, `/ip firewall nat`
- **v7 documentation and examples** increasingly use the **slash-separated** style: `/ip/hotspot`, `/interface/bridge`, `/ip/firewall/nat`
- The **API protocol** has always used slash-separated paths: `/system/resource/print`, `/ip/address/add`

### Recommendation for Provisioning Scripts

Use **slash-separated paths** (`/ip/address/add`) for maximum forward compatibility. Both versions accept this format. The API protocol has always required slash-separated paths regardless of CLI version.

---

## 2. Bridge Configuration

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Create bridge | `/interface bridge add name=bridge1` | `/interface/bridge add name=bridge1` | Path style only |
| Add port | `/interface bridge port add interface=ether2 bridge=bridge1` | `/interface/bridge/port add interface=ether2 bridge=bridge1` | Path style only |
| Print bridges | `/interface bridge print` | `/interface/bridge print` | Path style only |
| Enable VLAN filtering | `/interface bridge set bridge1 vlan-filtering=yes` | `/interface/bridge set bridge1 vlan-filtering=yes` | No change |
| Add VLAN | `/interface bridge vlan add bridge=bridge1 tagged=ether1 vlan-ids=10` | `/interface/bridge/vlan add bridge=bridge1 tagged=ether1 vlan-ids=10` | Path style only |

**No functional command changes** for bridge configuration between v6 and v7. Only path style conventions differ.

---

## 3. Hotspot Setup

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Setup wizard | `/ip hotspot setup` | `/ip/hotspot/setup` | Path style only |
| Add server | `/ip hotspot add name=hs1 interface=bridge1 address-pool=hs-pool` | `/ip/hotspot add name=hs1 interface=bridge1 address-pool=hs-pool` | Path style only |
| Add user | `/ip hotspot user add name=user1 password=pass server=hs1` | `/ip/hotspot/user add name=user1 password=pass server=hs1` | Path style only |
| Add user profile | `/ip hotspot user profile add name=profile1 rate-limit=1M/2M` | `/ip/hotspot/user/profile add name=profile1 rate-limit=1M/2M` | Path style only |
| Server profile | `/ip hotspot profile add name=hsprof1 hotspot-address=10.5.50.1 dns-name=hotspot.example.com` | `/ip/hotspot/profile add ...` | Path style only |

### Hotspot-Related Changes in v7

- **User Manager was completely rewritten** in v7. The old web-based User Manager in v6 was replaced with a new implementation manageable via WinBox and console.
- The migration command: `/user-manager/database/migrate-legacy-db database-path=<path>`
- v7 User Manager path: `/user-manager/` (new top-level menu)
- v6 User Manager was managed via separate web interface, not CLI
- v7 requires firewall rule to accept traffic to Hotspot gateway IP

---

## 4. PPPoE Server

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Add PPPoE server | `/interface pppoe-server server add service-name=myPPPoE interface=ether1` | `/interface/pppoe-server/server add service-name=myPPPoE interface=ether1` | Path style only |
| Add PPPoE client | `/interface pppoe-client add name=pppoe-out1 user=user password=pass interface=ether1` | `/interface/pppoe-client add name=pppoe-out1 user=user password=pass interface=ether1` | Path style only |
| PPP secret | `/ppp secret add name=user1 password=pass service=pppoe profile=default` | `/ppp/secret add name=user1 password=pass service=pppoe profile=default` | Path style only |
| PPP profile | `/ppp profile add name=myprofile local-address=10.0.0.1 remote-address=pppoe-pool rate-limit=2M/4M` | `/ppp/profile add name=myprofile local-address=10.0.0.1 remote-address=pppoe-pool rate-limit=2M/4M` | Path style only |

**No functional command changes** for PPPoE configuration.

---

## 5. DHCP Server

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Add IP pool | `/ip pool add name=dhcp-pool ranges=192.168.88.10-192.168.88.254` | `/ip/pool add name=dhcp-pool ranges=192.168.88.10-192.168.88.254` | Path style only |
| Add DHCP server | `/ip dhcp-server add name=dhcp1 interface=bridge1 address-pool=dhcp-pool disabled=no` | `/ip/dhcp-server add name=dhcp1 interface=bridge1 address-pool=dhcp-pool disabled=no` | Path style only |
| Add network | `/ip dhcp-server network add address=192.168.88.0/24 gateway=192.168.88.1 dns-server=8.8.8.8` | `/ip/dhcp-server/network add address=192.168.88.0/24 gateway=192.168.88.1 dns-server=8.8.8.8` | Path style only |
| DHCP client | `/ip dhcp-client add disabled=no interface=ether1` | `/ip/dhcp-client add disabled=no interface=ether1` | Path style only |
| Lease management | `/ip dhcp-server lease print` | `/ip/dhcp-server/lease print` | Path style only |

**No functional command changes** for DHCP configuration.

---

## 6. DNS Configuration

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Set DNS servers | `/ip dns set servers=8.8.8.8,8.8.4.4` | `/ip/dns set servers=8.8.8.8,8.8.4.4` | Path style only |
| Allow remote | `/ip dns set allow-remote-requests=yes` | `/ip/dns set allow-remote-requests=yes` | Path style only |
| Flush cache | `/ip dns cache flush` | `/ip/dns/cache flush` | Path style only |
| Static DNS entry | `/ip dns static add name=example.com address=192.168.1.10` | `/ip/dns/static add name=example.com address=192.168.1.10` | Path style only |
| Print DNS config | `/ip dns print` | `/ip/dns print` | Path style only |

**No functional command changes** for DNS configuration.

---

## 7. Firewall Rules

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Add filter rule | `/ip firewall filter add chain=input connection-state=established,related action=accept` | `/ip/firewall/filter add chain=input connection-state=established,related action=accept` | Path style only |
| Add forward rule | `/ip firewall filter add chain=forward action=accept` | `/ip/firewall/filter add chain=forward action=accept` | Path style only |
| Drop rule | `/ip firewall filter add chain=input action=drop` | `/ip/firewall/filter add chain=input action=drop` | Path style only |
| Mangle | `/ip firewall mangle add chain=prerouting ...` | `/ip/firewall/mangle add chain=prerouting ...` | Path style only |
| Address list | `/ip firewall address-list add list=blocked address=1.2.3.4` | `/ip/firewall/address-list add list=blocked address=1.2.3.4` | Path style only |

### Firewall-Specific Changes in v7

- **Connection tracking**: Connection states are expanded in v7; `fasttrack` is now explicitly referenced
- **Routing marks in firewall rules**: v7 requires routing tables to be pre-defined in `/routing/table` before referencing them in mangle rules
  - v6: `routing-mark="TableName"` (string matching)
  - v7: `routing-mark=[/routing/table find where name="TableName"]` (reference lookup)
  - Workaround for both: `routing-mark~"TableName"` (regex matching with `~` operator)

---

## 8. System Identity

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Set identity | `/system identity set name=MyRouter` | `/system/identity set name=MyRouter` | Path style only |
| Print identity | `/system identity print` | `/system/identity print` | Path style only |

**No functional changes.**

---

## 9. NAT Rules

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Masquerade | `/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade` | `/ip/firewall/nat add chain=srcnat out-interface=ether1 action=masquerade` | Path style only |
| Dst NAT (port forward) | `/ip firewall nat add chain=dstnat dst-port=80 protocol=tcp in-interface=ether1 action=dst-nat to-addresses=192.168.88.10 to-ports=80` | `/ip/firewall/nat add chain=dstnat dst-port=80 protocol=tcp in-interface=ether1 action=dst-nat to-addresses=192.168.88.10 to-ports=80` | Path style only |

**No functional changes** for basic NAT rules.

---

## 10. IP Address Management

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Add address | `/ip address add address=192.168.88.1/24 interface=ether1` | `/ip/address add address=192.168.88.1/24 interface=ether1` | Path style only |
| Print addresses | `/ip address print` | `/ip/address print` | Path style only |
| Remove address | `/ip address remove [find where address="192.168.88.1/24"]` | `/ip/address remove [find where address="192.168.88.1/24"]` | Path style only |

**No functional changes.**

---

## 11. User Management

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Add user | `/user add name=newuser password=pass group=full` | `/user add name=newuser password=pass group=full` | No change |
| Set password | `/user set admin password=NewPass` | `/user set admin password=NewPass` | No change |
| Print users | `/user print` | `/user print` | No change |
| Active sessions | `/user active print` | `/user/active print` | Path style only |

**No functional changes.**

---

## 12. Services Management

| Operation | v6 Syntax | v7 Syntax | Changed? |
|-----------|-----------|-----------|----------|
| Print services | `/ip service print` | `/ip/service print` | Path style only |
| Disable services | `/ip service disable telnet,ftp,www,api` | `/ip/service disable telnet,ftp,www,api` | Path style only |
| Set port | `/ip service set ssh port=2222` | `/ip/service set ssh port=2222` | Path style only |

**No functional changes.**

---

## 13. API Protocol Differences

### Traditional Socket API (Port 8728/8729)

| Aspect | v6 (pre-6.43) | v6 (post-6.43) | v7 |
|--------|---------------|----------------|-----|
| **Path format** | `/system/resource/print` (slash-separated) | Same | Same |
| **Login method** | MD5 challenge-response (2-step) | Plain text (1-step) | Plain text (1-step) |
| **Empty responses** | Not distinguished | Not distinguished | `!empty` reply (v7.18+) |
| **Protocol structure** | Word-length encoding + sentences | Same | Same |

### Authentication Flow Comparison

**Pre-6.43 (MD5 Challenge-Response)**:
```
Client -> Router: /login
Router -> Client: !done =ret=<challenge_hex>
Client -> Router: /login =name=admin =response=00<md5(0x00 + password + challenge)>
Router -> Client: !done
```

**Post-6.43 / v7 (Plain Text)**:
```
Client -> Router: /login =name=admin =password=<plaintext_password>
Router -> Client: !done
```

### REST API (v7 Only - New Feature)

RouterOS v7.1beta4 introduced a **REST API** as a JSON wrapper over the console API:

| Feature | Traditional API | REST API (v7+) |
|---------|----------------|----------------|
| Protocol | Custom binary socket (TCP 8728/8729) | HTTP/HTTPS |
| Path format | `/system/resource/print` | `GET /rest/system/resource` |
| Authentication | Custom login sentence | HTTP Basic Auth |
| Data format | Custom word encoding | JSON |
| HTTP methods | N/A | GET=print, PUT=add, PATCH=set, DELETE=remove, POST=arbitrary |

REST API URL examples:
- `https://<router>/rest/system/resource` -> system info
- `https://<router>/rest/ip/address` -> IP addresses
- `https://<router>/rest/ip/firewall/nat` -> NAT rules
- `https://<router>/rest/interface` -> interfaces

---

## 14. `/system/resource` Output Differences

### Version String Format

| Version | `/system resource get version` output |
|---------|--------------------------------------|
| v6.x | `6.48.3` (version number only) |
| v7.x | `7.11.2 (stable)` (version + stability channel) |

### Version Detection in Scripts

```routeros
# Method 1: String character check
:global versionStr [/system resource get version]
:if ([:pick $versionStr 0] < 7) do={
    /log info "RouterOS v6.x detected"
} else={
    /log info "RouterOS v7.x detected"
}

# Method 2: Numeric conversion (recommended)
:if ([:tonum [:pick [/system resource get version] 0 1]] > 6) do={
    /log info "This runs if RouterOS is 7.x+"
}
```

### `/system/health` Breaking Change

| Aspect | v6 | v7 |
|--------|----|----|
| Access method | Single get: `:put [/system health get]` | Iterate collection: `:foreach id in=[/system/health/find] do={...}` |
| Data model | Monolithic object with properties | List of sensor entries with `.id` |
| Voltage values | Requires division by 10 | Direct correct values |

### Other `/system/resource` Fields

The core fields (uptime, version, cpu-load, free-memory, total-memory, architecture-name, board-name, platform, cpu, cpu-count, cpu-frequency) remain consistent between v6 and v7. The v7 version string includes the stability channel label.

---

## 15. Major Structural Changes (Affect Provisioning)

### Routing (Complete Redesign)

| Feature | v6 | v7 |
|---------|----|----|
| Static routes | `/ip route add ...` | `/ip/route add ...` (same, but routing table must be pre-defined) |
| Route tables | Implicit, created by reference | Must be explicitly created: `/routing/table add name=myTable fib` |
| OSPF | Separate `/routing ospf` (v2) and `/ipv6 ospf` (v3) | Merged: `/routing/ospf` for both |
| BGP | `/routing bgp instance add ...` + `/routing bgp peer add ...` | `/routing/bgp/connection add ...` + `/routing/bgp/template add ...` (instances removed) |
| Routing filters | Rule-based configuration | Script-like `if .. then` syntax |
| Route monitoring | `/ip route print` | `/routing/route` (shows all families + filtered routes) |

### Wireless (New Packages)

| Package | v6 | v7 |
|---------|----|----|
| Legacy | `/interface wireless` | `/interface wireless` (still works) |
| WiFi (new) | N/A | `/interface/wifi` |
| WiFiWave2 | N/A | `/interface/wifiwave2` |

### Container Support (v7 Only)

- Enable: `/system/device-mode/update container=yes`
- Manage: `/container/` menu

### VRF Support (v7 Enhanced)

- `/ip/vrf` and `/routing/table` provide native VRF support

---

## 16. How ISP Billing Platforms Detect and Adapt

### Version Detection via API

ISP billing systems typically:

1. **Connect via API** (socket or REST)
2. **Query**: `/system/resource/print` to get the `version` field
3. **Parse** the major version number from the version string
4. **Branch** command generation based on detected version

### Known Platforms Supporting Both v6 and v7

| Platform | Approach |
|----------|----------|
| **Centipid** | Supports v6 and v7; uses API access with standard RouterOS configurations (PPPoE, Hotspot, DHCP, VLAN) |
| **ISPApp** | Cloud-based fleet management; bulk commands, firmware upgrades, plan speed management |
| **ISPBox/ISPNexus** | Native RouterOS integration; automated provisioning via API |
| **Nuance** (open source) | Billing system for small/medium ISPs with MikroTik integration |

### Script Compatibility Pattern

For scripts that must run on both v6 and v7:

```routeros
# Problem: v7 may have different syntax for some features
# Solution: Use :parse to defer execution and avoid compile-time syntax errors

:local version [:tonum [:pick [/system resource get version] 0 1]]

:if ($version >= 7) do={
    :do { [:parse "/routing/table add name=myTable fib"] } on-error={}
    :do { [:parse "/ip/route add dst-address=0.0.0.0/0 gateway=1.2.3.4 routing-table=myTable"] } on-error={}
} else={
    :do { [:parse "/ip route add dst-address=0.0.0.0/0 gateway=1.2.3.4 routing-mark=myTable"] } on-error={}
}
```

The `:parse` function is critical because RouterOS validates all code branches at compile time, even unreachable ones. Without `:parse`, a v7-only command in a v6-targeted branch would cause a syntax error on v6.

---

## 17. Summary for Provisioning Script Authors

### What Has NOT Changed (Safe to Use Same Commands)

For the vast majority of ISP provisioning tasks, **the commands themselves are identical** between v6 and v7:

- IP address management (`/ip/address`)
- Bridge configuration (`/interface/bridge`)
- DHCP server/client (`/ip/dhcp-server`, `/ip/dhcp-client`)
- PPPoE server/client (`/interface/pppoe-server`, `/ppp/secret`, `/ppp/profile`)
- Hotspot setup (`/ip/hotspot`)
- DNS configuration (`/ip/dns`)
- Firewall filter/NAT rules (`/ip/firewall/filter`, `/ip/firewall/nat`)
- System identity (`/system/identity`)
- User management (`/user`)
- IP services (`/ip/service`)
- IP pools (`/ip/pool`)
- Queues (`/queue/simple`, `/queue/tree`)

### What HAS Changed (Must Handle Per-Version)

| Area | Impact | Action Required |
|------|--------|----------------|
| **API authentication** | Login method changed at v6.43 | Support both MD5 challenge-response (pre-6.43) and plain text (post-6.43/v7) |
| **REST API** | Only available in v7.1+ | Use for v7+; fall back to socket API for v6 |
| **`!empty` reply** | New in v7.18 | API clients must handle this reply type |
| **Routing tables** | Must be pre-defined in v7 | Add `/routing/table add` before referencing in mangle/route rules |
| **`routing-mark` in firewall** | String matching changed | Use `~` regex operator for cross-version compatibility |
| **`/system/health`** | Data model changed to collection | Version-aware parsing needed |
| **OSPF/BGP** | Completely restructured | Version-specific configuration required |
| **User Manager** | Rewritten in v7 | Different menu paths, database migration needed |
| **Version string** | v7 includes "(stable)" suffix | Parse carefully when extracting version numbers |
| **Wireless** | New wifi/wifiwave2 packages | Detect and use appropriate interface type |

### Best Practices for Cross-Version Compatibility

1. **Always use slash-separated paths** in API calls (`/ip/address/add`, not `/ip address add`)
2. **Detect version first** via `/system/resource/print` before sending any version-specific commands
3. **Use `:parse`** in scripts to avoid compile-time errors on version-specific syntax
4. **Handle both auth methods** in API clients (plain text for v6.43+/v7, MD5 for older v6)
5. **Test against both versions** since some subtle behavioral differences exist beyond syntax
6. **Prefer REST API** for new v7-only integrations (simpler, JSON-based, HTTP standard)

---

## Sources

- [Moving from ROSv6 to v7 with examples - MikroTik Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/30474256/Moving+from+ROSv6+to+v7+with+examples)
- [Command Line Interface - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/328134/Command+Line+Interface)
- [Console - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/8978498/Console)
- [API - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/47579160/API)
- [REST API - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API)
- [Upgrading to v7 - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/115736772/Upgrading+to+v7)
- [MikroTik RouterOS 7.x Cheat Sheet](https://mikrotikusers.com/mikrotik-routeros-7-x-cheat-sheet/)
- [RouterOS v7 Cheatsheet (GitHub)](https://gist.github.com/3zzy/61e356f0bfcd2918d271836e30d80698)
- [Differentiate between RouterOS v6.x and v7.x - MikroTik Forum](https://forum.mikrotik.com/t/differentiate-between-routeros-v6-x-and-v7-x/160322)
- [API differences v6 & v7 - MikroTik Forum](https://forum.mikrotik.com/t/api-differences-v6-v7/161926)
- [Changed scripting coding between V6 and v7 - MikroTik Forum](https://forum.mikrotik.com/t/changed-scripting-coding-between-v6-and-v7/152004)
- [6.43 change in login process and API libraries - MikroTik Forum](https://forum.mikrotik.com/viewtopic.php?t=136475)
- [Health readings with v7 - MikroTik Forum](https://forum.mikrotik.com/viewtopic.php?t=180414)
- [User Manager - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/2555940/User+Manager)
- [Centipid ISP Billing System](https://www.centipidbilling.com/)
- [ISPApp - Open-source ISP cloud management](https://ispapp.co/)
- [Default firewall for RouterOS v6 and v7 - TARIKIN](https://www.tarikin.vn/default-firewall-for-routeros-v6-and-v7/)
- [NAT - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/3211299/NAT)
- [Firewall - RouterOS Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/250708066/Firewall)
