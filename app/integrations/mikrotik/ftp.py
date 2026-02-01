"""MikroTik FTP client for uploading hotspot templates and files.

This module provides functionality to upload custom HTML templates and other files
to MikroTik routers via FTP. MikroTik routers have FTP service that can be used to
upload files to the /hotspot directory for captive portal customization.
"""

import asyncio
import ftplib
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.core.errors import ErrorCode, ExternalServiceError

logger = logging.getLogger(__name__)


class MikroTikFTPClient:
    """FTP client for uploading files to MikroTik routers.

    This client handles uploading custom hotspot templates (login.html, alogin.html, etc.)
    to the MikroTik router's /hotspot directory.

    Example:
        client = MikroTikFTPClient()
        await client.upload_hotspot_template(
            router_ip="192.168.88.1",
            username="admin",
            password="password",
            template_path="/path/to/login.html",
            remote_filename="login.html"
        )
    """

    def __init__(self, timeout: int = 30):
        """Initialize the FTP client.

        Args:
            timeout: FTP connection timeout in seconds.
        """
        self.timeout = timeout

    async def upload_file(
        self,
        router_ip: str,
        username: str,
        password: str,
        local_file_path: str,
        remote_filename: str,
        remote_directory: str = "hotspot",
        port: int = 21,
    ) -> bool:
        """Upload a file to the MikroTik router via FTP.

        Args:
            router_ip: Router IP address.
            username: FTP username (usually same as API username).
            password: FTP password (usually same as API password).
            local_file_path: Path to the local file to upload.
            remote_filename: Filename on the router.
            remote_directory: Directory on the router (default: "hotspot").
            port: FTP port (default: 21).

        Returns:
            True if upload was successful.

        Raises:
            ExternalServiceError: If upload fails.
        """
        loop = asyncio.get_event_loop()

        def sync_upload() -> bool:
            ftp = None
            try:
                # Connect to FTP server
                ftp = ftplib.FTP(timeout=self.timeout)
                ftp.connect(router_ip, port)
                ftp.login(username, password)

                logger.info(f"Connected to FTP server at {router_ip}:{port}")

                # Change to hotspot directory (create if it doesn't exist)
                try:
                    ftp.cwd(remote_directory)
                except ftplib.error_perm:
                    # Directory might not exist, try to create it
                    try:
                        ftp.mkd(remote_directory)
                        ftp.cwd(remote_directory)
                        logger.info(f"Created directory /{remote_directory} on router")
                    except ftplib.error_perm as e:
                        logger.warning(f"Could not create directory /{remote_directory}: {e}")
                        # Some routers have hotspot directory by default, continue anyway

                # Get local file size for verification
                import os
                local_size = os.path.getsize(local_file_path)
                logger.info(f"Uploading {local_file_path} ({local_size} bytes) to /{remote_directory}/{remote_filename}")

                # Upload file in binary mode
                with open(local_file_path, 'rb') as file:
                    ftp.storbinary(f'STOR {remote_filename}', file)

                # Verify upload by checking file size on remote
                try:
                    remote_size = ftp.size(remote_filename)
                    if remote_size != local_size:
                        logger.warning(
                            f"File size mismatch! Local: {local_size} bytes, Remote: {remote_size} bytes"
                        )
                    else:
                        logger.info(
                            f"✓ Successfully uploaded {remote_filename} to {router_ip}:/{remote_directory}/ "
                            f"({local_size} bytes verified)"
                        )
                except Exception as e:
                    logger.warning(f"Could not verify file size: {e}")

                logger.info(
                    f"Successfully uploaded {local_file_path} to "
                    f"{router_ip}:/{remote_directory}/{remote_filename}"
                )
                return True

            except ftplib.all_errors as e:
                logger.error(f"FTP upload failed to {router_ip}: {e}")
                raise ExternalServiceError(
                    message=f"Failed to upload file via FTP: {e}",
                    code=ErrorCode.EXT_MIKROTIK_CONNECTION_FAILED,
                    service_name="mikrotik_ftp",
                    details={
                        "router_ip": router_ip,
                        "remote_file": f"/{remote_directory}/{remote_filename}",
                        "error": str(e),
                    },
                )
            finally:
                if ftp:
                    try:
                        ftp.quit()
                    except Exception:
                        try:
                            ftp.close()
                        except Exception:
                            pass

        return await loop.run_in_executor(None, sync_upload)

    async def upload_hotspot_template(
        self,
        router_ip: str,
        username: str,
        password: str,
        template_path: str,
        template_name: str,
        port: int = 21,
    ) -> bool:
        """Upload a hotspot template to the MikroTik router.

        This is a convenience method for uploading hotspot HTML templates.

        Args:
            router_ip: Router IP address.
            username: FTP username.
            password: FTP password.
            template_path: Path to the template file on local filesystem.
            template_name: Template filename (e.g., "login.html", "alogin.html").
            port: FTP port (default: 21).

        Returns:
            True if upload was successful.
        """
        return await self.upload_file(
            router_ip=router_ip,
            username=username,
            password=password,
            local_file_path=template_path,
            remote_filename=template_name,
            remote_directory="hotspot",
            port=port,
        )

    async def upload_hotspot_templates_batch(
        self,
        router_ip: str,
        username: str,
        password: str,
        templates: List[Dict[str, str]],
        port: int = 21,
    ) -> Dict[str, bool]:
        """Upload multiple hotspot templates in batch.

        Args:
            router_ip: Router IP address.
            username: FTP username.
            password: FTP password.
            templates: List of template dictionaries with 'path' and 'name' keys.
                Example: [{"path": "/path/to/login.html", "name": "login.html"}]
            port: FTP port (default: 21).

        Returns:
            Dictionary mapping template names to upload success status.
        """
        results = {}

        for template in templates:
            template_path = template.get("path")
            template_name = template.get("name")

            if not template_path or not template_name:
                logger.warning(f"Invalid template entry: {template}")
                results[template_name or "unknown"] = False
                continue

            try:
                success = await self.upload_hotspot_template(
                    router_ip=router_ip,
                    username=username,
                    password=password,
                    template_path=template_path,
                    template_name=template_name,
                    port=port,
                )
                results[template_name] = success
            except Exception as e:
                logger.error(f"Failed to upload {template_name}: {e}")
                results[template_name] = False

        return results

    async def list_hotspot_files(
        self,
        router_ip: str,
        username: str,
        password: str,
        port: int = 21,
    ) -> List[str]:
        """List files in the hotspot directory.

        Args:
            router_ip: Router IP address.
            username: FTP username.
            password: FTP password.
            port: FTP port (default: 21).

        Returns:
            List of filenames in the hotspot directory.
        """
        loop = asyncio.get_event_loop()

        def sync_list() -> List[str]:
            ftp = None
            try:
                ftp = ftplib.FTP(timeout=self.timeout)
                ftp.connect(router_ip, port)
                ftp.login(username, password)

                try:
                    ftp.cwd("hotspot")
                except ftplib.error_perm:
                    logger.warning("Hotspot directory does not exist")
                    return []

                files = ftp.nlst()
                return files

            except ftplib.all_errors as e:
                logger.error(f"FTP list failed: {e}")
                return []
            finally:
                if ftp:
                    try:
                        ftp.quit()
                    except Exception:
                        try:
                            ftp.close()
                        except Exception:
                            pass

        return await loop.run_in_executor(None, sync_list)

    async def delete_hotspot_file(
        self,
        router_ip: str,
        username: str,
        password: str,
        filename: str,
        port: int = 21,
    ) -> bool:
        """Delete a file from the hotspot directory.

        Args:
            router_ip: Router IP address.
            username: FTP username.
            password: FTP password.
            filename: Filename to delete.
            port: FTP port (default: 21).

        Returns:
            True if deletion was successful.
        """
        loop = asyncio.get_event_loop()

        def sync_delete() -> bool:
            ftp = None
            try:
                ftp = ftplib.FTP(timeout=self.timeout)
                ftp.connect(router_ip, port)
                ftp.login(username, password)

                ftp.cwd("hotspot")
                ftp.delete(filename)

                logger.info(f"Deleted /hotspot/{filename} from {router_ip}")
                return True

            except ftplib.all_errors as e:
                logger.error(f"FTP delete failed: {e}")
                return False
            finally:
                if ftp:
                    try:
                        ftp.quit()
                    except Exception:
                        try:
                            ftp.close()
                        except Exception:
                            pass

        return await loop.run_in_executor(None, sync_delete)


def get_mikrotik_ftp_client(timeout: int = 60) -> MikroTikFTPClient:
    """Get a MikroTik FTP client instance.

    Args:
        timeout: FTP connection timeout in seconds (default: 60s for template uploads).

    Returns:
        MikroTikFTPClient instance.
    """
    return MikroTikFTPClient(timeout=timeout)
