"""Gateway management service for testing and monitoring SMS, Email, and Payment gateways."""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ExternalServiceError, ConfigurationError
from app.models.configuration import Configuration, ConfigType
from app.modules.system import ConfigurationService
from app.modules.notifications import NotificationService
from app.modules.billing.mpesa import MpesaService

logger = get_logger(__name__)


class GatewayStatus:
    """Gateway status constants."""
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    TESTING = "testing"
    MAINTENANCE = "maintenance"


class GatewayType:
    """Gateway type constants."""
    SMS = "sms"
    EMAIL = "email"
    PAYMENT = "payment"


class GatewayManagementService:
    """Production-ready gateway management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.config_service = ConfigurationService(db)
        self.notification_service = NotificationService(db)
        self.logger = get_logger(__name__)
        
        # Test configuration
        self.test_timeout_seconds = 30
        self.test_retry_attempts = 3
        self.test_retry_delay = 2
        
        # Monitoring configuration
        self.status_check_interval = 300  # 5 minutes
        self.error_threshold = 5  # consecutive failures
        
        # Gateway configurations.
        # NOTE (Phase C1): SMS + EMAIL gateways removed — SMS / email / WhatsApp
        # delivery is centralized on notifications-api now. Only the PAYMENT
        # (M-PESA) gateway tester remains (and M-PESA itself routes via treasury-api).
        self.gateway_configs = {
            GatewayType.PAYMENT: {
                "mpesa": {
                    "name": "MPESA Daraja",
                    "test_endpoint": "https://sandbox.safaricom.co.ke/oauth/v1/generate",
                    "required_fields": ["consumer_key", "consumer_secret", "passkey", "shortcode"],
                    "test_method": self._test_mpesa_gateway
                }
            }
        }

    async def test_gateway(
        self, 
        gateway_type: str, 
        provider: str, 
        test_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Test a specific gateway configuration."""
        start_time = time.time()
        
        try:
            # Validate gateway type and provider
            if gateway_type not in self.gateway_configs:
                raise ValidationError(f"Invalid gateway type: {gateway_type}")
            
            if provider not in self.gateway_configs[gateway_type]:
                raise ValidationError(f"Invalid provider for {gateway_type}: {provider}")
            
            gateway_config = self.gateway_configs[gateway_type][provider]
            
            # Get configuration (use provided config or load from database)
            if test_config:
                config = test_config
            else:
                config = await self._load_gateway_config(gateway_type, provider)
            
            # Validate required fields
            missing_fields = []
            for field in gateway_config["required_fields"]:
                if field not in config or not config[field]:
                    missing_fields.append(field)
            
            if missing_fields:
                return {
                    "status": GatewayStatus.ERROR,
                    "success": False,
                    "error": f"Missing required fields: {', '.join(missing_fields)}",
                    "response_time_ms": 0,
                    "tested_at": datetime.utcnow().isoformat()
                }
            
            # Execute gateway-specific test
            test_method = gateway_config["test_method"]
            test_result = await test_method(config)
            
            end_time = time.time()
            response_time = int((end_time - start_time) * 1000)
            
            # Log test result
            await self._log_gateway_test(
                gateway_type, 
                provider, 
                test_result["success"], 
                test_result.get("error"),
                response_time
            )
            
            return {
                **test_result,
                "response_time_ms": response_time,
                "tested_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            end_time = time.time()
            response_time = int((end_time - start_time) * 1000)
            
            self.logger.error(f"Gateway test failed for {gateway_type}/{provider}: {e}")
            
            return {
                "status": GatewayStatus.ERROR,
                "success": False,
                "error": str(e),
                "response_time_ms": response_time,
                "tested_at": datetime.utcnow().isoformat()
            }

    # NOTE (Phase C1): SMS (Africa's Talking / Twilio) and EMAIL (SMTP / SendGrid /
    # SES) gateway testers were removed — those channels are owned by
    # notifications-api now.

    async def _test_mpesa_gateway(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Test MPESA payment gateway.

        The local M-PESA gateway integration was retired (Phase 2/3) — payment
        processing and connectivity are owned by treasury-api. The local tester
        therefore reports the gateway as handled externally.
        """
        return {
            "status": GatewayStatus.OFFLINE,
            "success": False,
            "message": "M-PESA processing is handled by treasury-api in this deployment.",
            "provider_response": "Local M-PESA gateway retired.",
        }

    async def _load_gateway_config(self, gateway_type: str, provider: str) -> Dict[str, Any]:
        """Load gateway configuration from database."""
        config_key = f"{gateway_type}_{provider}"

        # Load from configuration service
        config = await self.config_service.get_config(config_key, organization_id=None)

        if not config:
            # Fall back to environment variables.
            # NOTE (Phase C1): SMS/EMAIL env fallbacks removed (settings dropped) —
            # those channels are owned by notifications-api now.
            if gateway_type == GatewayType.PAYMENT and provider == "mpesa":
                return {
                    "consumer_key": settings.mpesa_consumer_key,
                    "consumer_secret": settings.mpesa_consumer_secret,
                    "passkey": settings.mpesa_passkey,
                    "shortcode": settings.mpesa_shortcode
                }
        
        return config.get_value() if config else {}

    async def get_gateway_status(self, gateway_type: str, provider: str) -> Dict[str, Any]:
        """Get current status of a gateway."""
        try:
            # Get last test result
            last_test = await self._get_last_test_result(gateway_type, provider)
            
            # Determine current status
            if not last_test:
                status = GatewayStatus.OFFLINE
                message = "No test results available"
            elif last_test["success"]:
                # Check if test is recent (within last hour)
                test_time = datetime.fromisoformat(last_test["tested_at"].replace('Z', '+00:00'))
                if datetime.utcnow() - test_time.replace(tzinfo=None) < timedelta(hours=1):
                    status = GatewayStatus.ONLINE
                    message = "Gateway is operational"
                else:
                    status = GatewayStatus.OFFLINE
                    message = "Status unknown - test required"
            else:
                status = GatewayStatus.ERROR
                message = last_test.get("error", "Unknown error")
            
            # Get configuration status
            config = await self._load_gateway_config(gateway_type, provider)
            config_status = "configured" if config else "not_configured"
            
            return {
                "gateway_type": gateway_type,
                "provider": provider,
                "status": status,
                "message": message,
                "configuration_status": config_status,
                "last_test": last_test,
                "requires_test": status != GatewayStatus.ONLINE
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get gateway status for {gateway_type}/{provider}: {e}")
            return {
                "gateway_type": gateway_type,
                "provider": provider,
                "status": GatewayStatus.ERROR,
                "message": str(e),
                "configuration_status": "error",
                "last_test": None,
                "requires_test": True
            }

    async def get_all_gateway_statuses(self) -> Dict[str, Any]:
        """Get status of all configured gateways."""
        statuses = {}
        
        for gateway_type, providers in self.gateway_configs.items():
            statuses[gateway_type] = {}
            
            for provider, config in providers.items():
                status = await self.get_gateway_status(gateway_type, provider)
                statuses[gateway_type][provider] = status
        
        # Calculate overall health
        total_gateways = sum(len(providers) for providers in self.gateway_configs.values())
        online_gateways = 0
        
        for gateway_type in statuses:
            for provider in statuses[gateway_type]:
                if statuses[gateway_type][provider]["status"] == GatewayStatus.ONLINE:
                    online_gateways += 1
        
        health_percentage = (online_gateways / total_gateways * 100) if total_gateways > 0 else 0
        
        return {
            "gateways": statuses,
            "summary": {
                "total_gateways": total_gateways,
                "online_gateways": online_gateways,
                "health_percentage": round(health_percentage, 2),
                "last_updated": datetime.utcnow().isoformat()
            }
        }

    async def test_all_gateways(self) -> Dict[str, Any]:
        """Test all configured gateways."""
        results = {}
        
        for gateway_type, providers in self.gateway_configs.items():
            results[gateway_type] = {}
            
            for provider in providers:
                test_result = await self.test_gateway(gateway_type, provider)
                results[gateway_type][provider] = test_result
        
        return {
            "test_results": results,
            "tested_at": datetime.utcnow().isoformat()
        }

    async def update_gateway_configuration(
        self, 
        gateway_type: str, 
        provider: str, 
        configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update gateway configuration."""
        try:
            # Validate gateway type and provider
            if gateway_type not in self.gateway_configs:
                raise ValidationError(f"Invalid gateway type: {gateway_type}")
            
            if provider not in self.gateway_configs[gateway_type]:
                raise ValidationError(f"Invalid provider for {gateway_type}: {provider}")
            
            gateway_config = self.gateway_configs[gateway_type][provider]
            
            # Validate required fields
            missing_fields = []
            for field in gateway_config["required_fields"]:
                if field not in configuration or not configuration[field]:
                    missing_fields.append(field)
            
            if missing_fields:
                raise ValidationError(f"Missing required fields: {', '.join(missing_fields)}")
            
            # Save configuration
            config_key = f"{gateway_type}_{provider}"
            await self.config_service.set_configuration(
                key=config_key,
                value=configuration,
                config_type=ConfigType.ENCRYPTED,
                category=f"{gateway_type}_gateways"
            )
            
            # Test the new configuration
            test_result = await self.test_gateway(gateway_type, provider, configuration)
            
            return {
                "message": f"Configuration updated for {gateway_type}/{provider}",
                "test_result": test_result,
                "updated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to update gateway configuration: {e}")
            raise

    async def get_gateway_configuration(self, gateway_type: str, provider: str) -> Dict[str, Any]:
        """Get gateway configuration (masked for security)."""
        try:
            config = await self._load_gateway_config(gateway_type, provider)
            
            if not config:
                return {"configured": False, "fields": []}
            
            # Mask sensitive fields
            masked_config = {}
            for key, value in config.items():
                if any(sensitive in key.lower() for sensitive in ['password', 'secret', 'key', 'token']):
                    masked_config[key] = "*" * 8 if value else ""
                else:
                    masked_config[key] = value
            
            gateway_config = self.gateway_configs[gateway_type][provider]
            
            return {
                "configured": True,
                "configuration": masked_config,
                "required_fields": gateway_config["required_fields"],
                "provider_name": gateway_config["name"]
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get gateway configuration: {e}")
            return {"configured": False, "error": str(e)}

    async def _log_gateway_test(
        self, 
        gateway_type: str, 
        provider: str, 
        success: bool, 
        error: Optional[str] = None,
        response_time: int = 0
    ) -> None:
        """Log gateway test result."""
        try:
            log_key = f"gateway_test_{gateway_type}_{provider}"
            
            test_log = {
                "gateway_type": gateway_type,
                "provider": provider,
                "success": success,
                "error": error,
                "response_time_ms": response_time,
                "tested_at": datetime.utcnow().isoformat()
            }
            
            # Store test result in configuration
            await self.config_service.set_configuration(
                key=log_key,
                value=test_log,
                config_type=ConfigType.JSON,
                category="gateway_tests"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log gateway test: {e}")

    async def _get_last_test_result(self, gateway_type: str, provider: str) -> Optional[Dict[str, Any]]:
        """Get last test result for a gateway."""
        try:
            log_key = f"gateway_test_{gateway_type}_{provider}"
            config = await self.config_service.get_config(log_key, organization_id=None)

            return config if config else None
            
        except Exception as e:
            self.logger.error(f"Failed to get last test result: {e}")
            return None

    async def get_gateway_test_history(
        self, 
        gateway_type: str, 
        provider: str, 
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """Get test history for a gateway."""
        try:
            # This would typically query a dedicated test history table
            # For now, return the last test result
            last_test = await self._get_last_test_result(gateway_type, provider)
            
            return [last_test] if last_test else []
            
        except Exception as e:
            self.logger.error(f"Failed to get gateway test history: {e}")
            return []

    async def monitor_gateway_health(self) -> Dict[str, Any]:
        """Monitor health of all gateways and send alerts if needed."""
        try:
            all_statuses = await self.get_all_gateway_statuses()
            
            # Check for failed gateways
            failed_gateways = []
            
            for gateway_type, providers in all_statuses["gateways"].items():
                for provider, status in providers.items():
                    if status["status"] in [GatewayStatus.ERROR, GatewayStatus.OFFLINE]:
                        failed_gateways.append({
                            "type": gateway_type,
                            "provider": provider,
                            "status": status["status"],
                            "error": status.get("message", "Unknown error")
                        })
            
            # Send alerts for failed gateways
            if failed_gateways:
                await self._send_gateway_alerts(failed_gateways)
            
            return {
                "monitoring_completed": True,
                "failed_gateways": len(failed_gateways),
                "total_gateways": all_statuses["summary"]["total_gateways"],
                "health_percentage": all_statuses["summary"]["health_percentage"],
                "alerts_sent": len(failed_gateways),
                "monitored_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Gateway health monitoring failed: {e}")
            return {
                "monitoring_completed": False,
                "error": str(e),
                "monitored_at": datetime.utcnow().isoformat()
            }

    async def _send_gateway_alerts(self, failed_gateways: List[Dict[str, Any]]) -> None:
        """Send alerts for failed gateways."""
        try:
            # Create alert message
            alert_message = "Gateway Health Alert:\n\n"
            for gateway in failed_gateways:
                alert_message += f"- {gateway['type'].upper()} ({gateway['provider']}): {gateway['status']} - {gateway['error']}\n"
            
            # Send notification to administrators
            # This would use the notification service to send alerts
            self.logger.warning(f"Gateway health alert: {len(failed_gateways)} gateways failed")
            
        except Exception as e:
            self.logger.error(f"Failed to send gateway alerts: {e}")

    async def get_gateway_statistics(self, days: int = 30) -> Dict[str, Any]:
        """Get gateway usage and performance statistics."""
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # This would typically query gateway usage logs
            # For now, return basic statistics
            
            stats = {
                "period_days": days,
                "sms_statistics": {
                    "total_sent": 0,
                    "success_rate": 0,
                    "average_response_time": 0,
                    "cost_analysis": {}
                },
                "email_statistics": {
                    "total_sent": 0,
                    "success_rate": 0,
                    "bounce_rate": 0,
                    "average_response_time": 0
                },
                "payment_statistics": {
                    "total_transactions": 0,
                    "success_rate": 0,
                    "average_response_time": 0,
                    "total_amount": 0
                },
                "generated_at": datetime.utcnow().isoformat()
            }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get gateway statistics: {e}")
            return {
                "error": str(e),
                "generated_at": datetime.utcnow().isoformat()
            }

    async def get_available_gateways(self) -> Dict[str, Any]:
        """Get list of available gateways and their capabilities."""
        gateways = {}
        
        for gateway_type, providers in self.gateway_configs.items():
            gateways[gateway_type] = {}
            
            for provider, config in providers.items():
                gateways[gateway_type][provider] = {
                    "name": config["name"],
                    "required_fields": config["required_fields"],
                    "test_endpoint": config.get("test_endpoint"),
                    "capabilities": self._get_gateway_capabilities(gateway_type, provider)
                }
        
        return {
            "gateways": gateways,
            "total_providers": sum(len(providers) for providers in self.gateway_configs.values())
        }

    def _get_gateway_capabilities(self, gateway_type: str, provider: str) -> List[str]:
        """Get capabilities for a specific gateway."""
        capabilities = {
            # NOTE (Phase C1): SMS/EMAIL capabilities removed (channels owned by
            # notifications-api).
            (GatewayType.PAYMENT, "mpesa"): ["stk_push", "c2b", "b2c", "reversal", "status_query"]
        }
        
        return capabilities.get((gateway_type, provider), [])

    # Maintenance and cleanup methods
    async def cleanup_old_test_logs(self, days: int = 30) -> int:
        """Clean up old gateway test logs."""
        try:
            cleanup_date = datetime.utcnow() - timedelta(days=days)
            
            # Get all gateway test configurations older than specified days
            result = await self.db.execute(
                select(Configuration).where(
                    and_(
                        Configuration.category == "gateway_tests",
                        Configuration.created_at < cleanup_date
                    )
                )
            )
            old_logs = result.scalars().all()
            
            cleanup_count = 0
            for log in old_logs:
                await self.db.delete(log)
                cleanup_count += 1
            
            await self.db.commit()
            
            self.logger.info(f"Cleaned up {cleanup_count} old gateway test logs")
            return cleanup_count
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup old test logs: {e}")
            return 0

    async def validate_gateway_configuration(
        self, 
        gateway_type: str, 
        provider: str, 
        configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate gateway configuration without saving."""
        try:
            # Validate gateway type and provider
            if gateway_type not in self.gateway_configs:
                raise ValidationError(f"Invalid gateway type: {gateway_type}")
            
            if provider not in self.gateway_configs[gateway_type]:
                raise ValidationError(f"Invalid provider for {gateway_type}: {provider}")
            
            gateway_config = self.gateway_configs[gateway_type][provider]
            
            # Check required fields
            validation_errors = []
            for field in gateway_config["required_fields"]:
                if field not in configuration or not configuration[field]:
                    validation_errors.append(f"Missing required field: {field}")
            
            # Perform test if configuration is valid
            test_result = None
            if not validation_errors:
                test_result = await self.test_gateway(gateway_type, provider, configuration)
            
            return {
                "valid": len(validation_errors) == 0,
                "errors": validation_errors,
                "test_result": test_result,
                "validated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "validated_at": datetime.utcnow().isoformat()
            }
