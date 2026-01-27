"""Real-time ICMP ping monitoring service for device provisioning."""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class PingMonitor:
    """Monitors device connectivity via ICMP ping and broadcasts results."""
    
    def __init__(self):
        self.active_monitors: Dict[str, asyncio.Task] = {}
        self.ping_results: Dict[str, Dict[str, Any]] = {}
    
    async def start_monitoring(
        self,
        session_id: str,
        ip_address: str,
        interval_seconds: float = 2.0,
        max_attempts: int = 30,
        timeout_ms: int = 1000
    ):
        """
        Start continuous ping monitoring for a provisioning session.
        
        Args:
            session_id: Provisioning session identifier
            ip_address: Target device IP address
            interval_seconds: Time between ping attempts
            max_attempts: Maximum number of ping attempts (default 30)
            timeout_ms: Ping timeout in milliseconds
        """
        if session_id in self.active_monitors:
            logger.warning(f"Ping monitor already running for session {session_id}")
            return
        
        # Create monitoring task
        task = asyncio.create_task(
            self._monitor_loop(
                session_id,
                ip_address,
                interval_seconds,
                max_attempts,
                timeout_ms
            )
        )
        self.active_monitors[session_id] = task
        logger.info(f"Started ping monitoring for session {session_id} targeting {ip_address}")
    
    async def stop_monitoring(self, session_id: str):
        """Stop ping monitoring for a session."""
        if session_id in self.active_monitors:
            task = self.active_monitors[session_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.active_monitors[session_id]
            logger.info(f"Stopped ping monitoring for session {session_id}")
    
    async def _monitor_loop(
        self,
        session_id: str,
        ip_address: str,
        interval_seconds: float,
        max_attempts: int,
        timeout_ms: int
    ):
        """Internal monitoring loop that performs continuous pings with retry backoff."""
        from app.api.v1.provisioning.bootstrap import ping_device
        from app.api.v1.provisioning.stream import manager
        
        attempt = 0
        consecutive_successes = 0
        retry_cycle = 0
        backoff_seconds = 300  # 5 minutes
        
        try:
            while True:  # Continue indefinitely with retry cycles
                # Reset attempt counter for each cycle
                cycle_attempts = 0
                
                while cycle_attempts < max_attempts:
                    attempt += 1
                    cycle_attempts += 1
                    
                    # Perform the ping
                    ping_result = await ping_device(ip_address, timeout_ms)
                    
                    # Store result
                    self.ping_results[session_id] = {
                        "attempt": attempt,
                        "cycle_attempt": cycle_attempts,
                        "max_attempts": max_attempts,
                        "retry_cycle": retry_cycle,
                        "reachable": ping_result["reachable"],
                        "latency_ms": ping_result.get("latency_ms"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ip_address": ip_address
                    }
                    
                    # Broadcast the ping result
                    ping_message = {
                        "type": "ping_result",
                        "session_id": session_id,
                        "data": {
                            "attempt": cycle_attempts,
                            "max_attempts": max_attempts,
                            "retry_cycle": retry_cycle,
                            "status": "success" if ping_result["reachable"] else "failed",
                            "reachable": ping_result["reachable"],
                            "latency_ms": ping_result.get("latency_ms"),
                            "error": None if ping_result["reachable"] else "Device not responding",
                            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                        }
                    }
                    
                    await manager.send_message(session_id, ping_message)
                    
                    # If device becomes reachable, count consecutive successes
                    if ping_result["reachable"]:
                        consecutive_successes += 1
                        logger.info(
                            f"Session {session_id}: Device reachable "
                            f"(latency: {ping_result.get('latency_ms')}ms, "
                            f"attempt {cycle_attempts}/{max_attempts}, cycle {retry_cycle})"
                        )
                        
                        # After 3 consecutive successful pings, consider device online
                        if consecutive_successes >= 3:
                            await manager.send_message(session_id, {
                                "type": "device_online",
                                "session_id": session_id,
                                "data": {
                                    "message": "Device is now online and reachable",
                                    "latency_ms": ping_result.get("latency_ms"),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            })
                            logger.info(f"Session {session_id}: Device confirmed online after {consecutive_successes} successful pings")
                            return  # Exit monitoring - device is online
                    else:
                        consecutive_successes = 0
                        logger.debug(
                            f"Session {session_id}: Device not reachable "
                            f"(attempt {cycle_attempts}/{max_attempts}, cycle {retry_cycle})"
                        )
                    
                    # Wait before next ping
                    await asyncio.sleep(interval_seconds)
                
                # Exhausted attempts in this cycle - back off and retry
                retry_cycle += 1
                logger.info(
                    f"Session {session_id}: Completed {max_attempts} attempts (cycle {retry_cycle - 1}). "
                    f"Backing off for {backoff_seconds}s before retry cycle {retry_cycle}"
                )
                
                # Send backoff notification
                await manager.send_message(session_id, {
                    "type": "ping_backoff",
                    "session_id": session_id,
                    "data": {
                        "message": f"Device not found after {max_attempts} attempts. Retrying in {backoff_seconds // 60} minutes...",
                        "backoff_seconds": backoff_seconds,
                        "retry_cycle": retry_cycle,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                })
                
                # Wait for backoff period
                await asyncio.sleep(backoff_seconds)
                
                # Send retry notification
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
            logger.info(f"Session {session_id}: Ping monitoring cancelled")
            raise
        except Exception as e:
            logger.error(f"Session {session_id}: Ping monitoring error: {e}")
            await manager.send_message(session_id, {
                "type": "ping_error",
                "session_id": session_id,
                "data": {
                    "message": f"Ping monitoring error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            })
        finally:
            # Cleanup
            if session_id in self.active_monitors:
                del self.active_monitors[session_id]
            if session_id in self.ping_results:
                del self.ping_results[session_id]
    
    def get_latest_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest ping result for a session."""
        return self.ping_results.get(session_id)
    
    def is_monitoring(self, session_id: str) -> bool:
        """Check if monitoring is active for a session."""
        return session_id in self.active_monitors


# Global ping monitor instance
ping_monitor = PingMonitor()
