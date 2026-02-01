# MikroTik Captive Portal Auto-Redirect Fix

## Problem Statement

When users connect to WiFi served by a MikroTik router provisioned by this system, they do not get:
1. Automatic redirect to the captive portal (buy packages page)
2. "Tap to Connect" notification on Android/iOS devices

This prevents users from easily accessing the package purchase page.

## Root Cause

Modern devices (Android, iOS, Windows) use connectivity check URLs to detect captive portals:

**Android:**
- `connectivitycheck.gstatic.com/generate_204`
- `www.google.com/generate_204`
- `clients3.google.com/generate_204`
- `android.clients.google.com`
- `clients4.google.com`

**iOS:**
- `captive.apple.com/hotspot-detect.html`

**Windows:**
- `www.msftconnecttest.com/connecttest.txt`
- `ipv6.msftconnecttest.com`

**The Issue:**
Modern devices use **HTTPS** for these connectivity checks, which MikroTik hotspot cannot intercept without a valid SSL certificate. Without interception, devices don't detect the captive portal and don't show the "Tap to Connect" notification.

## Solution Implemented

### DNS-Based Captive Portal Detection

Added DNS static entries that redirect connectivity check domains to the hotspot gateway address. This forces devices to send HTTP requests to the hotspot, which can be intercepted.

**Implementation** (`commands.py` lines 466-512):

```python
# DNS static entries for captive portal detection domains
captive_portal_detection_domains = [
    # Android
    "connectivitycheck.gstatic.com",
    "www.google.com",
    "clients3.google.com",
    "android.clients.google.com",
    "clients4.google.com",
    # iOS
    "captive.apple.com",
    # Windows
    "www.msftconnecttest.com",
    "ipv6.msftconnecttest.com",
]

# Add DNS static entries pointing to hotspot gateway
for domain in captive_portal_detection_domains:
    commands.append({
        "type": "api_call",
        "command": f'/ip/dns/static/add name="{domain}" address={gateway} comment=codevertex-captive-portal-detection',
        "description": f"DNS static entry for captive portal detection: {domain}",
        "critical": False,
    })
```

### How It Works

1. **User connects to WiFi** → Device receives DHCP configuration from MikroTik
2. **Device checks connectivity** → Tries to reach `connectivitycheck.gstatic.com` or similar
3. **DNS resolves to hotspot** → Our DNS static entry returns the hotspot gateway IP (e.g., 172.31.1.1)
4. **HTTP request intercepted** → MikroTik hotspot intercepts the HTTP request
5. **Redirect returned** → Hotspot returns HTTP 302 redirect to `login.html`
6. **Captive portal detected** → Device sees unexpected response instead of expected 204/success
7. **"Tap to Connect" shown** → OS shows notification to open captive portal
8. **User taps** → Opens `login.html` which redirects to `/buy/{org_slug}` page
9. **User buys package** → Completes purchase via M-PESA
10. **Hotspot authenticates** → User gets internet access

## Files Modified

### 1. `app/modules/provisioning/commands.py`
- **Lines 466-512**: Replaced old comment with DNS static entry configuration
- **Added**: DNS static entries for Android, iOS, and Windows connectivity check domains

### 2. `app/modules/provisioning/reset.md`
- **Lines 45-50**: Added DNS static entry removal in cleanup script
- **Lines 185-188**: Added DNS static entry verification in cleanup verification

## Testing Instructions

### Prerequisites
1. MikroTik router connected and accessible
2. Frontend running at configured URL (e.g., `http://192.168.100.4:3000`)
3. Backend running with correct `FRONTEND_URL` in `.env`
4. Organization created with slug (e.g., `demo`)

### Step 1: Provision a Router

1. Login to dashboard as admin
2. Navigate to **Routers** page
3. Add a new router or select existing router
4. Click **Provision** and select **Hotspot Service**
5. Configure:
   - **Bridge Name**: `codevertex-bridge`
   - **Hotspot Name**: `codevertex-hotspot`
   - **Gateway**: `172.31.1.1`
   - **Subnet**: `172.31.0.0/16`
   - **DNS Name**: `hotspot.local`
6. Click **Provision** and wait for completion

### Step 2: Verify DNS Static Entries

Connect to router via WinBox or SSH and run:

```bash
/ip/dns/static/print where comment~"codevertex-captive-portal-detection"
```

**Expected Output:**
```
# NAME                             ADDRESS        TTL COMMENT
0 connectivitycheck.gstatic.com    172.31.1.1     1d  codevertex-captive-portal-detection
1 www.google.com                   172.31.1.1     1d  codevertex-captive-portal-detection
2 clients3.google.com              172.31.1.1     1d  codevertex-captive-portal-detection
3 android.clients.google.com       172.31.1.1     1d  codevertex-captive-portal-detection
4 clients4.google.com              172.31.1.1     1d  codevertex-captive-portal-detection
5 captive.apple.com                172.31.1.1     1d  codevertex-captive-portal-detection
6 www.msftconnecttest.com          172.31.1.1     1d  codevertex-captive-portal-detection
7 ipv6.msftconnecttest.com         172.31.1.1     1d  codevertex-captive-portal-detection
```

### Step 3: Verify Hotspot Templates

```bash
/file/print where name~"login.html"
```

**Expected:** Should show `login.html` in `/hotspot/` directory

View template content:
```bash
/file/print file=hotspot/login.html
```

Should contain redirect to: `http://192.168.100.4:3000/buy/{org_slug}`

### Step 4: Test Captive Portal Detection

#### On Android Device:

1. **Forget WiFi network** (if previously connected)
2. **Scan for networks** → Find your hotspot SSID
3. **Connect to WiFi** → Enter password if WPA2 protected
4. **Wait 2-5 seconds** → Should see notification

**Expected Notification:**
```
[WiFi Name]
Sign in to network
Tap to use this network
```

5. **Tap notification** → Should open browser/in-app browser
6. **Should redirect to** → `http://192.168.100.4:3000/buy/demo`
7. **Should see** → Buy packages page with available packages

#### On iOS Device:

1. **Forget WiFi network** (if previously connected)
2. **Connect to WiFi**
3. **Wait for popup** → Should automatically show captive portal web sheet

**Expected:**
- Captive portal web sheet opens automatically
- Shows buy packages page
- URL bar shows `http://192.168.100.4:3000/buy/demo`

#### On Windows PC:

1. **Connect to WiFi**
2. **Wait for notification** → "Additional sign-in required"
3. **Click notification** → Opens captive portal in browser

### Step 5: Test Package Purchase Flow

1. **Select a package** (e.g., "Daily Unlimited")
2. **Enter phone number** (Kenyan format: 0722000000)
3. **Click "Subscribe Now"**
4. **M-PESA STK push** → Check phone for payment prompt
5. **Enter M-PESA PIN** → Complete payment
6. **Wait for confirmation** → Should show success page with voucher code
7. **Verify internet access** → Try opening google.com

## Troubleshooting

### Issue: No "Tap to Connect" Notification

**Check:**
1. DNS static entries exist:
   ```bash
   /ip/dns/static/print where comment~"codevertex-captive-portal-detection"
   ```
   If empty, re-provision the router

2. Hotspot is running:
   ```bash
   /ip/hotspot/print
   ```
   Should show hotspot with `disabled=no`

3. Device previously connected:
   - Forget the WiFi network on device
   - Reconnect from scratch

4. DNS server configured:
   ```bash
   /ip/dns/print
   ```
   Should show `servers` with at least one DNS (e.g., 8.8.8.8)

### Issue: Redirect Goes to Wrong URL

**Check:**
1. Frontend URL in backend `.env`:
   ```bash
   FRONTEND_URL=http://192.168.100.4:3000
   ```

2. Organization slug is correct:
   ```sql
   SELECT slug FROM organizations WHERE id = 1;
   ```

3. Template uploaded correctly:
   ```bash
   /file/print file=hotspot/login.html
   ```
   Should contain correct redirect URL

**Fix:** Re-upload templates via provisioning:
- Use the "Re-provision" button in dashboard
- Or manually upload via FTP

### Issue: Browser Shows "Can't Reach This Page"

**Check:**
1. Walled garden includes frontend server:
   ```bash
   /ip/hotspot/walled-garden/print
   ```
   Should include `192.168.100.4` or frontend host

2. Walled garden IP entries:
   ```bash
   /ip/hotspot/walled-garden/ip/print
   ```
   Should include frontend server IP

**Fix:** Add to walled garden:
```bash
/ip/hotspot/walled-garden/add dst-host="192.168.100.4" action=allow
/ip/hotspot/walled-garden/ip/add dst-address=192.168.100.4 action=accept
```

### Issue: Payment Fails / API Not Accessible

**Check:**
1. Backend server in walled garden:
   ```bash
   /ip/hotspot/walled-garden/print where dst-host~"192.168.100.4"
   ```

2. CORS configured in backend:
   - Check `app/main.py` lines 273-283
   - Should allow frontend origin

3. Backend API accessible:
   ```bash
   curl http://192.168.100.4:8000/health
   ```

## Configuration Variables

### Backend Environment Variables

Required in `isp-billing-backend/.env`:

```bash
# Frontend URL for captive portal redirect
FRONTEND_URL=http://192.168.100.4:3000

# Backend URL for API calls
BACKEND_URL=http://192.168.100.4:8000

# Enable CORS for captive portal
CORS_ORIGINS=http://192.168.100.4:3000,http://192.168.100.4:3001
```

### Organization Settings

Set via dashboard **Settings** → **Hotspot** tab:

- **Hotspot Template**: Aurora (or other template)
- **Redirect URL**: Auto-generated from `FRONTEND_URL` and organization slug
- **Prune Inactive Users**: 14 days (recommended)

## Technical Reference

### MikroTik Commands Reference

**View Hotspot Configuration:**
```bash
/ip/hotspot/print detail
/ip/hotspot/profile/print detail
```

**View Walled Garden:**
```bash
/ip/hotspot/walled-garden/print
/ip/hotspot/walled-garden/ip/print
```

**View DNS Static Entries:**
```bash
/ip/dns/static/print
```

**View Active Hotspot Users:**
```bash
/ip/hotspot/active/print
```

**Manually Add User (for testing):**
```bash
/ip/hotspot/user/add name=testuser password=test123 profile=default
```

**Manually Authorize MAC (bypass login):**
```bash
/ip/hotspot/host/add mac-address=AA:BB:CC:DD:EE:FF to-address=172.31.1.100
```

### Related Documentation

- [MikroTik Hotspot Documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/56459266/HotSpot+-+Captive+portal)
- [Captive Portal Detection - Android](https://source.android.com/devices/tech/connect/captive-portal)
- [Captive Portal Detection - iOS](https://support.apple.com/en-us/HT210244)
- [RFC 7710 - Captive Portal Identification](https://www.rfc-editor.org/rfc/rfc7710)

## Success Criteria

✅ Android devices show "Tap to Connect" notification within 5 seconds of connecting
✅ iOS devices automatically open captive portal web sheet
✅ Windows devices show "Additional sign-in required" notification
✅ Tapping notification opens buy packages page (`/buy/{org_slug}`)
✅ Users can purchase packages via M-PESA without errors
✅ After payment, users get internet access immediately
✅ Voucher codes are generated and displayed correctly

## Rollback Instructions

If the fix causes issues, you can rollback by:

1. **Remove DNS static entries:**
   ```bash
   /ip/dns/static/remove [find comment~"codevertex-captive-portal-detection"]
   ```

2. **Revert code changes:**
   ```bash
   cd isp-billing-backend
   git revert <commit-hash>
   ```

3. **Re-provision router** with old configuration

## Future Enhancements

1. **HTTPS Support**: Add SSL certificate to enable HTTPS captive portal (RFC 7710 compliant)
2. **Customizable Detection URLs**: Allow admins to add custom connectivity check domains
3. **Regional Detection URLs**: Add region-specific connectivity check domains (e.g., China, Russia)
4. **Auto-Detection**: Automatically detect and configure DNS entries based on detected client OS
5. **Dashboard Monitoring**: Show captive portal detection status in router dashboard

## Credits

**References:**
- [MikroTik Forum - Captive Portal Detection](https://forum.mikrotik.com/t/improving-hotspot-captive-portal-detection/125418)
- [Spotipo - Captive Portal Troubleshooting](https://www.spotipo.com/post/troubleshooting-captive-portals-7-common-issues-and-how-to-fix-them)
- [Android Captive Portal Detection](https://source.android.com/devices/tech/connect/captive-portal)

**Author:** CodeVertex IT Solutions
**Date:** 2026-02-01
**Version:** 1.0.0
