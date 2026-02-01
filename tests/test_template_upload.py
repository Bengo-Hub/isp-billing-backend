"""Manual test script for MikroTik template upload.

This script manually uploads hotspot templates to a MikroTik router
and verifies the upload by checking file timestamps.
"""

import asyncio
import sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Fix Windows console Unicode issues
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add parent directory to path (backend root)
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import get_db
from app.models.router import Router, RouterStatus
from app.models.organization import Organization
from app.integrations.mikrotik.ftp import get_mikrotik_ftp_client
from app.integrations.mikrotik import get_mikrotik_client
from app.core.config import settings


async def test_template_upload():
    """Test template upload to MikroTik router."""
    print("=" * 80)
    print("MikroTik Template Upload Test")
    print("=" * 80)

    # Get database session
    async for db in get_db():
        try:
            # 1. Find most recent router with organization (provisioned routers)
            print("\n[1] Fetching most recent provisioned router from database...")
            result = await db.execute(
                select(Router)
                .where(Router.status == RouterStatus.ONLINE)
                .where(Router.organization_id.isnot(None))
                .order_by(Router.created_at.desc())
                .limit(1)
            )
            router = result.scalar_one_or_none()

            if not router:
                print("❌ No online routers with organization found. Trying any online router...")
                result = await db.execute(
                    select(Router)
                    .where(Router.status == RouterStatus.ONLINE)
                    .order_by(Router.created_at.desc())
                    .limit(1)
                )
                router = result.scalar_one_or_none()

            if not router:
                print("❌ No online routers found. Trying any router...")
                result = await db.execute(
                    select(Router)
                    .order_by(Router.created_at.desc())
                    .limit(1)
                )
                router = result.scalar_one_or_none()

            if not router:
                print("❌ No routers found in database!")
                return

            print(f"✓ Found router: {router.name}")
            print(f"  - IP: {router.ip_address}")
            print(f"  - Username: {router.username}")
            print(f"  - Status: {router.status}")

            # 2. Get organization for captive portal URL
            print("\n[2] Fetching organization...")

            if router.organization_id:
                org_result = await db.execute(
                    select(Organization)
                    .where(Organization.id == router.organization_id)
                )
                org = org_result.scalar_one_or_none()
            else:
                # Get first organization if router doesn't have one
                print("  ⚠️  Router has no organization, using first organization...")
                org_result = await db.execute(select(Organization).limit(1))
                org = org_result.scalar_one_or_none()

            if not org:
                print("❌ No organizations found in database!")
                return

            print(f"✓ Found organization: {org.name}")
            print(f"  - Slug: {org.slug}")

            # 3. Construct captive portal URL
            base_url = settings.frontend_url or "http://localhost:3000"
            captive_portal_url = f"{base_url.rstrip('/')}/buy/{org.slug}"
            print(f"\n[3] Captive portal URL: {captive_portal_url}")

            # 4. Read and process templates
            print("\n[4] Processing hotspot templates...")
            # Script is in tests/, go up one level to backend root
            template_dir = Path(__file__).parent.parent / "app" / "modules" / "provisioning" / "hotspot_templates"

            if not template_dir.exists():
                print(f"❌ Template directory not found: {template_dir}")
                return

            import tempfile
            processed_templates = []

            template_files = [
                {"source": "login_redirect.html", "target": "login.html"},
                {"source": "alogin.html", "target": "alogin.html"}
            ]

            for template_info in template_files:
                source_path = template_dir / template_info["source"]

                if not source_path.exists():
                    print(f"⚠️  Template not found: {source_path}")
                    continue

                # Read template
                with open(source_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Replace placeholder
                content = content.replace('$(redirect-url)', captive_portal_url)

                # Create temp file
                temp_file = tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    delete=False,
                    suffix='.html'
                )
                temp_file.write(content)
                temp_file.close()

                processed_templates.append({
                    "path": temp_file.name,
                    "name": template_info["target"]
                })
                print(f"  ✓ Processed: {template_info['source']} → {template_info['target']}")

            if not processed_templates:
                print("❌ No templates to upload!")
                return

            # 5. Upload templates via FTP
            print(f"\n[5] Uploading {len(processed_templates)} templates via FTP...")
            print(f"  - Connecting to: {router.ip_address}:21")
            print(f"  - Username: {router.username}")

            ftp_client = get_mikrotik_ftp_client(timeout=60)

            results = await ftp_client.upload_hotspot_templates_batch(
                router_ip=router.ip_address,
                username=router.username,
                password=router.password,
                templates=processed_templates,
                port=21
            )

            # Clean up temp files
            import os
            for template in processed_templates:
                try:
                    os.unlink(template["path"])
                except Exception as e:
                    print(f"⚠️  Failed to delete temp file: {e}")

            # Check results
            print("\n[6] Upload Results:")
            for name, success in results.items():
                status = "✓" if success else "❌"
                print(f"  {status} {name}: {'Success' if success else 'Failed'}")

            all_success = all(results.values())

            # 7. Verify uploads using MikroTik API
            print("\n[7] Verifying uploads via MikroTik API...")
            client = get_mikrotik_client()

            try:
                connection = await client.connect(
                    ip_address=router.ip_address,
                    username=router.username,
                    password=router.password,
                    port=router.port
                )

                # List files in /hotspot directory
                print("  Listing files in /hotspot directory...")
                file_list = await client.execute_command(
                    connection,
                    "/file",
                    "print",
                    {"where": "name~\"hotspot/\""}
                )

                if file_list:
                    print(f"\n  Found {len(file_list)} files in /hotspot/:")
                    for file_info in file_list:
                        name = file_info.get('name', 'unknown')
                        size = file_info.get('size', 'unknown')
                        creation_time = file_info.get('creation-time', 'unknown')
                        print(f"    - {name}")
                        print(f"      Size: {size}")
                        print(f"      Created: {creation_time}")
                else:
                    print("  ⚠️  No files found in /hotspot directory")

                await client.disconnect(router.ip_address, router.port)

            except Exception as e:
                print(f"  ❌ Failed to verify via API: {e}")

            # Summary
            print("\n" + "=" * 80)
            if all_success:
                print("✅ Template upload completed successfully!")
            else:
                print("⚠️  Template upload completed with some failures")
            print("=" * 80)

        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()

        break


if __name__ == "__main__":
    asyncio.run(test_template_upload())
