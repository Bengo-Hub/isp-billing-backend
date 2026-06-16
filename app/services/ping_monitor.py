"""Real-time device connectivity monitoring service for provisioning.

Performs two-stage verification:
1. ICMP Ping - Confirms device is on the network
2. API Port Check - Confirms bootstrap command was executed and API is enabled
"""

import logging
import asyncio
import socket
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PingMonitor:
    """Monitors device connectivity via ICMP ping and API port check.

    Also keeps a small in-memory register of device check-ins reported by
    devices (router->backend notify) so provisioning sessions started after
    a bootstrap can immediately observe that the device already reported
    itself online.
    """

    def __init__(self):
        self.active_monitors: Dict[str, asyncio.Task] = {}
        self.monitor_results: Dict[str, Dict[str, Any]] = {}
        # Pending device check-ins keyed by ip_address
        self.pending_checkins: Dict[str, Dict[str, Any]] = {}

    async def start_monitoring(
        self,
        session_id: str,
        ip_address: str,
        api_port: int = 8728,
        interval_seconds: float = 2.0,
        max_attempts: int = 30,
        timeout_ms: int = 1000
    ):
        """
        Start two-stage connectivity monitoring for a provisioning session.

        Stage 1: ICMP Ping - Verify device is reachable on network
        Stage 2: API Port Check - Verify API port is open (bootstrap executed)

        If a device previously called the backend notify endpoint (router ->
        backend), that check-in will be recorded in `pending_checkins` and we
        treat the device as already reachable.

        Args:
            session_id: Provisioning session identifier
            ip_address: Target device IP address
            api_port: MikroTik API port (default 8728)
            interval_seconds: Time between check attempts
            max_attempts: Maximum attempts per cycle (default 30)
            timeout_ms: Connection timeout in milliseconds
        """
        if session_id in self.active_monitors:
            logger.warning(f"Monitor already running for session {session_id}")
            return

        # If device already checked in via router->backend notify, mark as ready
        pending = self.pending_checkins.get(ip_address)
        if pending:
            self.monitor_results[session_id] = {
                "attempt": 0,
                "ping_verified": True,
                "api_verified": True,
                "ip_address": ip_address,
                "method": "device-checkin",
                "note": "Device previously reported bootstrap completion",
                "timestamp": pending.get("timestamp")
            }
            # Remove one-time pending checkin (consumed)
            del self.pending_checkins[ip_address]
            logger.info(f"Session {session_id}: Found prior device checkin for {ip_address}; marking as ready")
            await self.mark_online_from_notify(session_id, ip_address)
            return

        # If the router already called home for THIS session (bootstrap notify
        # arrived before the UI opened monitoring — the normal case for a NAT'd
        # router the cloud can't reach), don't start the cloud-ping loop (it would
        # abort on the private RFC1918 IP). Re-emit the online events so the UI
        # flips both stages to success.
        existing = self.monitor_results.get(session_id)
        if existing and existing.get("ping_verified") and existing.get("api_verified"):
            await self.mark_online_from_notify(session_id, existing.get("ip_address"))
            return

        # Create monitoring task
        task = asyncio.create_task(
            self._monitor_loop(
                session_id,
                ip_address,
                api_port,
                interval_seconds,
                max_attempts,
                timeout_ms
            )
        )
        self.active_monitors[session_id] = task
        logger.info(f"Started two-stage monitoring for session {session_id} targeting {ip_address}:{api_port}")

    async def stop_monitoring(self, session_id: str):
        """Stop monitoring for a session."""
        if session_id in self.active_monitors:
            task = self.active_monitors[session_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.active_monitors[session_id]
            logger.info(f"Stopped monitoring for session {session_id}")

    async def _check_api_port(self, ip_address: str, port: int, timeout_ms: int) -> Dict[str, Any]:
        """Check if API port is open using TCP connection.

        Args:
            ip_address: Target IP address
            port: API port to check
            timeout_ms: Timeout in milliseconds

        Returns:
            dict with 'open' (bool), 'latency_ms' (float or None)
        """
        try:
            start_time = time.time()

            # Use asyncio for non-blocking socket connection
            loop = asyncio.get_event_loop()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)

            try:
                await asyncio.wait_for(
                    loop.sock_connect(sock, (ip_address, port)),
                    timeout=timeout_ms / 1000.0
                )
                latency = (time.time() - start_time) * 1000
                sock.close()
                return {"open": True, "latency_ms": round(latency, 1), "port": port}
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                sock.close()
                return {"open": False, "latency_ms": None, "port": port}

        except Exception as e:
            logger.debug(f"API port check error for {ip_address}:{port}: {e}")
            return {"open": False, "latency_ms": None, "port": port, "error": str(e)}

    # ---- Device check-in API (router -> backend) --------------------------------
    def register_device_checkin(self, ip_address: str, info: Optional[Dict[str, Any]] = None) -> None:
        """Record a one-time device check-in (called by provisioning notify).

        This lets future provisioning sessions detect that the router already
        executed the bootstrap and avoid waiting for ICMP/TCP checks.
        """
        self.pending_checkins[ip_address] = info or {"timestamp": datetime.now(timezone.utc).isoformat()}
        logger.info(f"Registered device checkin for {ip_address}: {self.pending_checkins[ip_address]}")

    async def mark_online_from_notify(
        self,
        session_id: str,
        ip_address: Optional[str] = None,
        identity: Optional[str] = None,
    ) -> None:
        """Mark a session's device ONLINE because the router called home.

        The bootstrap notify (or polling-agent check-in) is the AUTHORITATIVE
        "device online" signal for a NAT'd router the cloud-hosted backend can
        never ICMP/TCP from the outside. Records the verified result, stops any
        cloud-ping loop, and pushes the stage_complete (1 & 2) + device_online SSE
        events the provisioning UI consumes so BOTH stages flip to success.
        """
        from app.api.v1.provisioning.stream import manager

        self.monitor_results[session_id] = {
            "ping_verified": True,
            "api_verified": True,
            "ip_address": ip_address,
            "method": "device-notify",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if self.is_monitoring(session_id):
                await self.stop_monitoring(session_id)
        except Exception:
            pass

        ts = datetime.now(timezone.utc).isoformat()
        for stage, name, msg in (
            (1, "Network Reachability", "Device reported in via secure check-in (NAT-safe)"),
            (2, "API Port Check", "Device API confirmed via secure check-in"),
        ):
            try:
                await manager.send_message(session_id, {
                    "type": "stage_complete",
                    "session_id": session_id,
                    "data": {
                        "stage": stage,
                        "stage_name": name,
                        "message": msg,
                        "method": "device-notify",
                        "timestamp": ts,
                    },
                })
            except Exception:
                pass
        try:
            await manager.send_message(session_id, {
                "type": "device_online",
                "session_id": session_id,
                "data": {
                    "message": "Device connected (reported via secure check-in) — ready for configuration",
                    "ping_verified": True,
                    "api_verified": True,
                    "method": "device-notify",
                    "identity": identity,
                    "timestamp": ts,
                },
            })
        except Exception:
            pass
        logger.info(f"Session {session_id}: marked online via device-notify (NAT-safe)")

    async def _monitor_loop(
        self,
        session_id: str,
        ip_address: str,
        api_port: int,
        interval_seconds: float,
        max_attempts: int,
        timeout_ms: int
    ):
        """Internal monitoring loop with two-stage verification."""
        from app.api.v1.provisioning.bootstrap import ping_device
        from app.api.v1.provisioning.stream import manager

        attempt = 0
        retry_cycle = 0
        backoff_seconds = 300  # 5 minutes

        # Stage tracking
        ping_verified = False
        api_verified = False
        consecutive_ping_successes = 0
        consecutive_api_successes = 0

        try:
            # If the target IP is a private / RFC1918 address, the cloud-hosted
            # backend cannot reliably reach it. Inform the frontend and stop
            # monitoring early so the UI can show actionable guidance instead
            # of repeatedly retrying.
            try:
                import ipaddress
                ip_obj = ipaddress.ip_address(ip_address)
                if ip_obj.is_private:
                    # Send a clear message to the frontend explaining why checks will fail
                    await manager.send_message(session_id, {
                        "type": "ping_error",
                        "session_id": session_id,
                        "data": {
                            "message": "Device IP appears to be on a private LAN (RFC1918). Backend cannot reach private addresses from the cloud. Use local provisioning or ensure device is reachable from the control plane.",
                            "ip_address": ip_address,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    })
                    logger.warning(f"Session {session_id}: Target IP {ip_address} is private; aborting server-side monitoring")
                    # Record the result so UI can display it
                    self.monitor_results[session_id] = {
                        "attempt": 0,
                        "ping_verified": False,
                        "api_verified": False,
                        "ip_address": ip_address,
                        "error": "private_address",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    return
            except Exception:
                # If IP parsing fails, continue with monitoring and let checks fail normally
                pass

            while True:  # Continue indefinitely with retry cycles
                cycle_attempts = 0

                while cycle_attempts < max_attempts:
                    attempt += 1
                    cycle_attempts += 1

                    # Store current state
                    self.monitor_results[session_id] = {
                        "attempt": attempt,
                        "cycle_attempt": cycle_attempts,
                        "max_attempts": max_attempts,
                        "retry_cycle": retry_cycle,
                        "ping_verified": ping_verified,
                        "api_verified": api_verified,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ip_address": ip_address,
                        "api_port": api_port
                    }

                    # STAGE 1: ICMP Ping Check
                    if not ping_verified:
                        ping_result = await ping_device(ip_address, timeout_ms)

                        await manager.send_message(session_id, {
                            "type": "ping_result",
                            "session_id": session_id,
                            "data": {
                                "stage": 1,
                                "stage_name": "Network Reachability",
                                "attempt": cycle_attempts,
                                "max_attempts": max_attempts,
                                "retry_cycle": retry_cycle,
                                "status": "success" if ping_result["reachable"] else "failed",
                                "reachable": ping_result["reachable"],
                                "latency_ms": ping_result.get("latency_ms"),
                                "error": None if ping_result["reachable"] else "Device not responding to ping",
                                "timestamp": datetime.now(timezone.utc).strftime('%H:%M:%S'),
                            }
                        })

                        if ping_result["reachable"]:
                            consecutive_ping_successes += 1
                            if consecutive_ping_successes >= 2:
                                ping_verified = True
                                # Notify stage 1 complete
                                await manager.send_message(session_id, {
                                    "type": "stage_complete",
                                    "session_id": session_id,
                                    "data": {
                                        "stage": 1,
                                        "stage_name": "Network Reachability",
                                        "message": "Device is reachable on network",
                                        "latency_ms": ping_result.get("latency_ms"),
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    }
                                })
                                logger.info(f"Session {session_id}: Stage 1 complete - Device reachable")
                        else:
                            consecutive_ping_successes = 0

                    # STAGE 2: API Port Check (only after ping verified)
                    if ping_verified and not api_verified:
                        api_result = await self._check_api_port(ip_address, api_port, timeout_ms)

                        await manager.send_message(session_id, {
                            "type": "api_check_result",
                            "session_id": session_id,
                            "data": {
                                "stage": 2,
                                "stage_name": "API Port Check",
                                "attempt": cycle_attempts,
                                "max_attempts": max_attempts,
                                "status": "success" if api_result["open"] else "failed",
                                "port_open": api_result["open"],
                                "port": api_port,
                                "latency_ms": api_result.get("latency_ms"),
                                "error": None if api_result["open"] else f"API port {api_port} not responding - run bootstrap command",
                                "timestamp": datetime.now(timezone.utc).strftime('%H:%M:%S'),
                            }
                        })

                        if api_result["open"]:
                            consecutive_api_successes += 1
                            if consecutive_api_successes >= 2:
                                api_verified = True
                                # Notify stage 2 complete
                                await manager.send_message(session_id, {
                                    "type": "stage_complete",
                                    "session_id": session_id,
                                    "data": {
                                        "stage": 2,
                                        "stage_name": "API Port Check",
                                        "message": f"API port {api_port} is open and responding",
                                        "latency_ms": api_result.get("latency_ms"),
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    }
                                })
                                logger.info(f"Session {session_id}: Stage 2 complete - API port {api_port} open")
                        else:
                            consecutive_api_successes = 0

                    # Both stages verified - device is ready
                    if ping_verified and api_verified:
                        await manager.send_message(session_id, {
                            "type": "device_online",
                            "session_id": session_id,
                            "data": {
                                "message": "Device connected and API enabled - ready for configuration",
                                "ping_verified": True,
                                "api_verified": True,
                                "api_port": api_port,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        })
                        logger.info(f"Session {session_id}: Both stages verified - device fully ready")
                        return  # Exit monitoring - device is ready

                    # Wait before next check
                    await asyncio.sleep(interval_seconds)

                # Exhausted attempts - back off and retry
                retry_cycle += 1
                status_msg = "Device reachable but API not enabled" if ping_verified else "Device not reachable"

                logger.info(
                    f"Session {session_id}: Completed {max_attempts} attempts (cycle {retry_cycle - 1}). "
                    f"Status: {status_msg}. Backing off for {backoff_seconds}s"
                )

                await manager.send_message(session_id, {
                    "type": "ping_backoff",
                    "session_id": session_id,
                    "data": {
                        "message": f"{status_msg}. Retrying in {backoff_seconds // 60} minutes...",
                        "ping_verified": ping_verified,
                        "api_verified": api_verified,
                        "backoff_seconds": backoff_seconds,
                        "retry_cycle": retry_cycle,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                })

                await asyncio.sleep(backoff_seconds)

                await manager.send_message(session_id, {
                    "type": "ping_retry",
                    "session_id": session_id,
                    "data": {
                        "message": f"Resuming device detection (retry cycle {retry_cycle})...",
                        "retry_cycle": retry_cycle,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                })

        except asyncio.CancelledError:
            logger.info(f"Session {session_id}: Monitoring cancelled")
            raise
        except Exception as e:
            logger.error(f"Session {session_id}: Monitoring error: {e}")
            await manager.send_message(session_id, {
                "type": "ping_error",
                "session_id": session_id,
                "data": {
                    "message": f"Monitoring error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            })
        finally:
            if session_id in self.active_monitors:
                del self.active_monitors[session_id]
            if session_id in self.monitor_results:
                del self.monitor_results[session_id]

    def get_latest_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest monitoring result for a session."""
        return self.monitor_results.get(session_id)

    def is_monitoring(self, session_id: str) -> bool:
        """Check if monitoring is active for a session."""
        return session_id in self.active_monitors


# Global ping monitor instance
ping_monitor = PingMonitor()
