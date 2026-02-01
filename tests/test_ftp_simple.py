"""Simple FTP connection test with hardcoded credentials."""

import ftplib

# From your screenshot and bootstrap logs
ROUTER_IP = "192.168.100.7"
USERNAME = "codevertex_api_user"
# Password from bootstrap script - should match what's in the database
# This is the default from config.py unless you changed it
PASSWORD = "changeme_in_production"  # Default from settings

print("=" * 80)
print("Simple FTP Connection Test")
print("=" * 80)
print(f"\nRouter: {ROUTER_IP}")
print(f"Username: {USERNAME}")
print(f"Password: {'*' * len(PASSWORD)}")

ftp = None
try:
    print("\n[1] Creating FTP connection...")
    ftp = ftplib.FTP(timeout=30)

    print(f"[2] Connecting to {ROUTER_IP}:21...")
    response = ftp.connect(ROUTER_IP, 21)
    print(f"    Response: {response}")

    print(f"[3] Logging in as '{USERNAME}'...")
    response = ftp.login(USERNAME, PASSWORD)
    print(f"    Response: {response}")

    print(f"[4] Getting welcome message...")
    welcome = ftp.getwelcome()
    print(f"    Welcome: {welcome}")

    print(f"[5] Listing root directory...")
    files = ftp.nlst()
    print(f"    Found {len(files)} items:")
    for f in files[:10]:
        print(f"      - {f}")

    print(f"\n[6] Checking /hotspot directory...")
    try:
        ftp.cwd("hotspot")
        print("    [OK] /hotspot exists")
        hotspot_files = ftp.nlst()
        print(f"    Found {len(hotspot_files)} files:")
        for f in hotspot_files:
            try:
                size = ftp.size(f)
                print(f"      - {f} ({size} bytes)")
            except:
                print(f"      - {f}")
    except ftplib.error_perm as e:
        print(f"    [FAIL] Cannot access /hotspot: {e}")

    print("\n" + "=" * 80)
    print("[SUCCESS] FTP connection working!")
    print("=" * 80)

except ftplib.error_perm as e:
    print(f"\n[FAIL] FTP Permission Error: {e}")
    print("\nThis means:")
    print("  - Wrong username or password")
    print("  - FTP user doesn't have permissions")
    print("\nTry these passwords:")
    print("  1. changeme_in_production (default)")
    print("  2. The password you set during provisioning")
    print("  3. admin (if using admin user)")

except ConnectionRefusedError as e:
    print(f"\n[FAIL] Connection Refused: {e}")
    print("\nThis means:")
    print("  - FTP service is not running")
    print("  - Firewall is blocking the connection")

except OSError as e:
    print(f"\n[FAIL] OS Error: {e}")

except Exception as e:
    print(f"\n[FAIL] Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

finally:
    if ftp:
        try:
            ftp.quit()
            print("\n[OK] Connection closed")
        except:
            try:
                ftp.close()
            except:
                pass
