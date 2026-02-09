"""Enhanced notification template service with variable substitution and user type differentiation."""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Template, Environment, BaseLoader, TemplateError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, NotificationError
from app.models.notification import NotificationTemplate, NotificationType
from app.models.user import User
from app.models.subscription import Subscription, SubscriptionType
from app.models.plan import ServicePlan
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class NotificationTemplateService:
    """Enhanced notification template service with advanced features."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)
        self.jinja_env = Environment(loader=BaseLoader())

    def get_available_variables(self) -> Dict[str, List[str]]:
        """Get available template variables by context."""
        return {
            "user": [
                "@username", "@first_name", "@last_name", "@email", "@phone",
                "@full_name", "@user_id", "@registration_date", "@last_login"
            ],
            "subscription": [
                "@subscription_id", "@subscription_type", "@username", "@password",
                "@start_date", "@end_date", "@status", "@auto_renewal", "@router_name"
            ],
            "plan": [
                "@package_name", "@package_type", "@price", "@currency", "@billing_cycle",
                "@download_speed", "@upload_speed", "@data_limit", "@time_limit",
                "@validity_days", "@description"
            ],
            "payment": [
                "@payment_amount", "@payment_method", "@payment_date", "@receipt_number",
                "@transaction_id", "@payment_status", "@invoice_number"
            ],
            "router": [
                "@router_name", "@router_ip", "@router_location", "@router_status",
                "@router_uptime", "@connected_users"
            ],
            "system": [
                "@company_name", "@support_email", "@support_phone", "@website_url",
                "@portal_url", "@org_slug", "@account_number", "@paybill",
                "@current_date", "@current_time", "@expiry_date", "@days_remaining", "@days_left"
            ]
        }

    async def create_enhanced_template(
        self,
        template_data: Dict[str, Any],
        created_by: int
    ) -> NotificationTemplate:
        """Create an enhanced notification template."""
        try:
            # Validate template syntax
            await self._validate_template_syntax(
                template_data.get('body_template', ''),
                template_data.get('html_template'),
                template_data.get('hotspot_template'),
                template_data.get('pppoe_template')
            )

            # Extract variables from templates
            variables = self._extract_template_variables(template_data)
            template_data['variables'] = json.dumps(variables)

            template = NotificationTemplate(
                created_by=created_by,
                **template_data
            )

            self.db.add(template)
            await self.db.commit()
            await self.db.refresh(template)

            self.logger.info(f"Created enhanced notification template: {template.name}")
            return template

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create notification template: {e}")
            raise

    async def render_template(
        self,
        template_id: int,
        context_data: Dict[str, Any],
        user_type: Optional[str] = None,
        output_format: str = "text"
    ) -> Dict[str, str]:
        """Render a notification template with context data."""
        template = await self.get_template_by_id(template_id)
        if not template:
            raise ValidationError(f"Template {template_id} not found")

        try:
            # Get appropriate template content
            if user_type and template.user_type_specific:
                body_content = template.get_template_for_user_type(user_type)
            else:
                body_content = template.body_template

            # Prepare template variables
            template_vars = self._prepare_template_variables(context_data)

            # Render subject
            subject = ""
            if template.subject_template:
                subject_tmpl = self.jinja_env.from_string(template.subject_template)
                subject = subject_tmpl.render(**template_vars)

            # Render body
            body_tmpl = self.jinja_env.from_string(body_content)
            body = body_tmpl.render(**template_vars)

            # Render HTML version if available
            html_body = ""
            if output_format == "html" and template.html_template:
                html_tmpl = self.jinja_env.from_string(template.html_template)
                html_body = html_tmpl.render(**template_vars)
            elif output_format == "html" and template.supports_html:
                # Convert text to basic HTML
                html_body = self._text_to_html(body)

            # Update template usage statistics
            template.usage_count += 1
            await self.db.commit()

            return {
                "subject": subject.strip(),
                "body": body.strip(),
                "html_body": html_body.strip() if html_body else "",
                "variables_used": list(template_vars.keys()),
                "user_type": user_type,
                "template_name": template.name
            }

        except TemplateError as e:
            self.logger.error(f"Template rendering error for template {template_id}: {e}")
            raise NotificationError(f"Template rendering failed: {str(e)}")
        except Exception as e:
            self.logger.error(f"Failed to render template {template_id}: {e}")
            raise

    async def test_template(
        self,
        template_id: int,
        test_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Test a notification template with sample data."""
        template = await self.get_template_by_id(template_id)
        if not template:
            raise ValidationError(f"Template {template_id} not found")

        try:
            # Use provided test data or generate sample data
            if not test_data:
                test_data = self._generate_sample_data()

            # Test rendering for different user types
            test_results = {}
            
            # Test general template
            try:
                result = await self.render_template(
                    template_id=template_id,
                    context_data=test_data,
                    user_type=None,
                    output_format="text"
                )
                test_results["general"] = {"success": True, "result": result}
            except Exception as e:
                test_results["general"] = {"success": False, "error": str(e)}

            # Test user type specific templates if applicable
            if template.user_type_specific:
                for user_type in ["hotspot", "pppoe"]:
                    try:
                        result = await self.render_template(
                            template_id=template_id,
                            context_data=test_data,
                            user_type=user_type,
                            output_format="text"
                        )
                        test_results[user_type] = {"success": True, "result": result}
                    except Exception as e:
                        test_results[user_type] = {"success": False, "error": str(e)}

            # Test HTML rendering if supported
            if template.supports_html:
                try:
                    result = await self.render_template(
                        template_id=template_id,
                        context_data=test_data,
                        user_type=None,
                        output_format="html"
                    )
                    test_results["html"] = {"success": True, "result": result}
                except Exception as e:
                    test_results["html"] = {"success": False, "error": str(e)}

            # Update template test results
            template.last_tested = datetime.utcnow()
            template.test_results = json.dumps(test_results)
            await self.db.commit()

            # Calculate overall success rate
            successful_tests = sum(1 for result in test_results.values() if result["success"])
            total_tests = len(test_results)
            success_rate = (successful_tests / total_tests * 100) if total_tests > 0 else 0

            return {
                "template_id": template_id,
                "template_name": template.name,
                "test_results": test_results,
                "overall_success_rate": round(success_rate, 2),
                "variables_available": template.get_variables(),
                "tested_at": template.last_tested.isoformat()
            }

        except Exception as e:
            self.logger.error(f"Failed to test template {template_id}: {e}")
            raise

    async def preview_template(
        self,
        template_content: str,
        context_data: Dict[str, Any],
        output_format: str = "text"
    ) -> Dict[str, str]:
        """Preview a template without saving it."""
        try:
            # Prepare template variables
            template_vars = self._prepare_template_variables(context_data)

            # Render template
            tmpl = self.jinja_env.from_string(template_content)
            rendered = tmpl.render(**template_vars)

            # Convert to HTML if requested
            html_rendered = ""
            if output_format == "html":
                html_rendered = self._text_to_html(rendered)

            return {
                "rendered_text": rendered.strip(),
                "rendered_html": html_rendered.strip() if html_rendered else "",
                "variables_used": list(template_vars.keys()),
                "character_count": len(rendered),
                "estimated_sms_count": max(1, (len(rendered) + 159) // 160)
            }

        except TemplateError as e:
            raise NotificationError(f"Template preview failed: {str(e)}")
        except Exception as e:
            self.logger.error(f"Failed to preview template: {e}")
            raise

    async def get_template_by_id(self, template_id: int) -> Optional[NotificationTemplate]:
        """Get notification template by ID."""
        return await self.db.get(NotificationTemplate, template_id)

    async def get_templates_by_category(
        self,
        category: str,
        is_active: bool = True
    ) -> List[NotificationTemplate]:
        """Get templates by category."""
        query = select(NotificationTemplate).where(
            and_(
                NotificationTemplate.category == category,
                NotificationTemplate.is_active == is_active
            )
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()

    # Private helper methods
    async def _validate_template_syntax(
        self,
        body_template: str,
        html_template: Optional[str] = None,
        hotspot_template: Optional[str] = None,
        pppoe_template: Optional[str] = None
    ) -> None:
        """Validate template syntax."""
        templates_to_validate = [("body", body_template)]
        
        if html_template:
            templates_to_validate.append(("html", html_template))
        if hotspot_template:
            templates_to_validate.append(("hotspot", hotspot_template))
        if pppoe_template:
            templates_to_validate.append(("pppoe", pppoe_template))

        for template_type, content in templates_to_validate:
            try:
                # Test Jinja2 syntax
                self.jinja_env.from_string(content)
            except TemplateError as e:
                raise ValidationError(f"Invalid {template_type} template syntax: {str(e)}")

    def _extract_template_variables(self, template_data: Dict[str, Any]) -> List[str]:
        """Extract variables from template content."""
        variables = set()
        
        # Extract from all template fields
        template_fields = [
            'subject_template', 'body_template', 'html_template',
            'hotspot_template', 'pppoe_template'
        ]
        
        for field in template_fields:
            content = template_data.get(field)
            if content:
                # Find Jinja2 variables: {{ variable }} and @variable
                jinja_vars = re.findall(r'\{\{\s*(\w+)\s*\}\}', content)
                at_vars = re.findall(r'@(\w+)', content)
                
                variables.update(jinja_vars)
                variables.update(at_vars)

        return sorted(list(variables))

    def _prepare_template_variables(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare template variables from context data."""
        template_vars = {}
        
        # Process user data
        if 'user' in context_data:
            user_data = context_data['user']
            template_vars.update({
                'username': user_data.get('username', ''),
                'first_name': user_data.get('first_name', ''),
                'last_name': user_data.get('last_name', ''),
                'email': user_data.get('email', ''),
                'phone': user_data.get('phone', ''),
                'full_name': f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip(),
                'user_id': user_data.get('id', ''),
                'registration_date': user_data.get('created_at', ''),
                'last_login': user_data.get('last_login', '')
            })

        # Process subscription data
        if 'subscription' in context_data:
            sub_data = context_data['subscription']
            template_vars.update({
                'subscription_id': sub_data.get('id', ''),
                'subscription_type': sub_data.get('subscription_type', ''),
                'start_date': sub_data.get('start_date', ''),
                'end_date': sub_data.get('end_date', ''),
                'status': sub_data.get('status', ''),
                'auto_renewal': sub_data.get('is_auto_renewal', False),
                'router_name': sub_data.get('router_name', '')
            })

        # Process plan data
        if 'plan' in context_data:
            plan_data = context_data['plan']
            template_vars.update({
                'package_name': plan_data.get('name', ''),
                'package_type': plan_data.get('plan_type', ''),
                'price': plan_data.get('price', ''),
                'currency': plan_data.get('currency', ''),
                'billing_cycle': plan_data.get('billing_cycle', ''),
                'download_speed': plan_data.get('download_speed', ''),
                'upload_speed': plan_data.get('upload_speed', ''),
                'data_limit': plan_data.get('data_limit', ''),
                'time_limit': plan_data.get('time_limit', ''),
                'validity_days': plan_data.get('validity_days', ''),
                'description': plan_data.get('description', '')
            })

        # Process payment data
        if 'payment' in context_data:
            payment_data = context_data['payment']
            template_vars.update({
                'payment_amount': payment_data.get('amount', ''),
                'payment_method': payment_data.get('payment_method', ''),
                'payment_date': payment_data.get('payment_date', ''),
                'receipt_number': payment_data.get('mpesa_receipt_number', ''),
                'transaction_id': payment_data.get('transaction_id', ''),
                'payment_status': payment_data.get('status', ''),
                'invoice_number': payment_data.get('invoice_number', '')
            })

        # Process system data
        if 'system' in context_data:
            system_data = context_data['system']
            template_vars.update({
                'company_name': system_data.get('company_name', 'ISP Billing System'),
                'support_email': system_data.get('support_email', 'support@example.com'),
                'support_phone': system_data.get('support_phone', ''),
                'website_url': system_data.get('website_url', ''),
                'portal_url': system_data.get('portal_url', 'https://ispbilling.codevertexitsolutions.com'),
                'org_slug': system_data.get('org_slug', ''),
                'account_number': system_data.get('account_number', ''),
                'paybill': system_data.get('paybill', ''),
                'current_date': datetime.utcnow().strftime('%Y-%m-%d'),
                'current_time': datetime.utcnow().strftime('%H:%M:%S'),
                'expiry_date': system_data.get('expiry_date', ''),
                'days_remaining': system_data.get('days_remaining', ''),
                'days_left': system_data.get('days_remaining', '')  # Alias for compatibility
            })

        # Add any additional custom variables
        if 'custom' in context_data:
            template_vars.update(context_data['custom'])

        return template_vars

    def _generate_sample_data(self) -> Dict[str, Any]:
        """Generate sample data for template testing."""
        return {
            "user": {
                "username": "johndoe",
                "first_name": "John",
                "last_name": "Doe",
                "email": "john.doe@example.com",
                "phone": "+254712345678",
                "id": 123,
                "created_at": "2024-01-15",
                "last_login": "2024-12-16"
            },
            "subscription": {
                "id": 456,
                "subscription_type": "hotspot",
                "username": "johndoe_hs",
                "password": "secure123",
                "start_date": "2024-12-01",
                "end_date": "2024-12-31",
                "status": "active",
                "is_auto_renewal": True,
                "router_name": "Main Router"
            },
            "plan": {
                "name": "Premium 10Mbps",
                "plan_type": "hotspot",
                "price": "2500",
                "currency": "KES",
                "billing_cycle": "monthly",
                "download_speed": "10",
                "upload_speed": "10",
                "data_limit": "50",
                "time_limit": "-1",
                "validity_days": "30",
                "description": "High-speed internet package"
            },
            "payment": {
                "amount": "2500",
                "payment_method": "mpesa",
                "payment_date": "2024-12-16",
                "mpesa_receipt_number": "QGH7XYZ123",
                "transaction_id": "ws_CO_16122024123456",
                "status": "completed",
                "invoice_number": "INV-2024-001"
            },
            "system": {
                "company_name": "FastNet ISP",
                "support_email": "support@fastnet.com",
                "support_phone": "+254700123456",
                "website_url": "https://fastnet.com",
                "expiry_date": "2024-12-31",
                "days_remaining": "15"
            }
        }

    def _text_to_html(self, text: str) -> str:
        """Convert plain text to basic HTML."""
        # Basic text to HTML conversion
        html = text.replace('\n', '<br>\n')
        html = f"<div style='font-family: Arial, sans-serif; line-height: 1.6;'>{html}</div>"
        return html

    async def get_template_usage_analytics(
        self,
        template_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get template usage analytics."""
        template = await self.get_template_by_id(template_id)
        if not template:
            raise ValidationError(f"Template {template_id} not found")

        # Get usage over time (simplified - would track actual usage in production)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        # Get notifications sent using this template
        from app.models.notification import Notification
        result = await self.db.execute(
            select(
                func.date(Notification.created_at).label('date'),
                func.count(Notification.id).label('count'),
                func.sum(
                    func.case(
                        (Notification.status == 'sent', 1),
                        else_=0
                    )
                ).label('successful')
            )
            .where(
                and_(
                    Notification.template_name == template.name,
                    Notification.created_at >= start_date
                )
            )
            .group_by(func.date(Notification.created_at))
            .order_by(func.date(Notification.created_at).desc())
        )
        
        usage_data = []
        total_sent = 0
        total_successful = 0
        
        for row in result:
            usage_data.append({
                "date": row.date.isoformat(),
                "sent": row.count,
                "successful": row.successful,
                "success_rate": (row.successful / row.count * 100) if row.count > 0 else 0
            })
            total_sent += row.count
            total_successful += row.successful

        overall_success_rate = (total_successful / total_sent * 100) if total_sent > 0 else 0

        return {
            "template_id": template_id,
            "template_name": template.name,
            "period_days": days,
            "usage_data": usage_data,
            "summary": {
                "total_sent": total_sent,
                "total_successful": total_successful,
                "overall_success_rate": round(overall_success_rate, 2),
                "current_usage_count": template.usage_count,
                "template_success_rate": float(template.success_rate)
            }
        }

    async def duplicate_template(
        self,
        template_id: int,
        new_name: str,
        created_by: int
    ) -> NotificationTemplate:
        """Duplicate an existing template."""
        original = await self.get_template_by_id(template_id)
        if not original:
            raise ValidationError(f"Template {template_id} not found")

        try:
            # Create duplicate with new name
            duplicate_data = {
                "name": new_name,
                "notification_type": original.notification_type,
                "subject_template": original.subject_template,
                "body_template": original.body_template,
                "html_template": original.html_template,
                "user_type_specific": original.user_type_specific,
                "hotspot_template": original.hotspot_template,
                "pppoe_template": original.pppoe_template,
                "description": f"Copy of {original.description}" if original.description else None,
                "supports_html": original.supports_html,
                "supports_markdown": original.supports_markdown,
                "css_styles": original.css_styles,
                "category": original.category,
                "tags": original.tags,
                "version": "1.0"
            }

            duplicate = await self.create_enhanced_template(duplicate_data, created_by)
            
            self.logger.info(f"Duplicated template {original.name} as {new_name}")
            return duplicate

        except Exception as e:
            self.logger.error(f"Failed to duplicate template {template_id}: {e}")
            raise

    async def get_template_variables_for_type(
        self,
        notification_type: NotificationType
    ) -> List[str]:
        """Get recommended variables for notification type."""
        variable_map = {
            NotificationType.BILLING: [
                "@username", "@full_name", "@invoice_number", "@payment_amount",
                "@due_date", "@package_name", "@company_name"
            ],
            NotificationType.SUBSCRIPTION: [
                "@username", "@package_name", "@start_date", "@end_date",
                "@subscription_type", "@router_name", "@price"
            ],
            NotificationType.WELCOME: [
                "@username", "@full_name", "@package_name", "@company_name",
                "@support_email", "@website_url"
            ],
            NotificationType.SMS: [
                "@username", "@package_name", "@expiry_date", "@days_remaining",
                "@payment_amount", "@company_name"
            ],
            NotificationType.EMAIL: [
                "@username", "@full_name", "@email", "@package_name",
                "@company_name", "@support_email", "@website_url"
            ]
        }
        
        return variable_map.get(notification_type, [
            "@username", "@full_name", "@company_name", "@current_date"
        ])
