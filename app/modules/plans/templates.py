"""Advanced package management service with templates and bulk operations."""

import secrets
import string
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ConfigurationError
from app.models.package_template import (
    PackageTemplate,
    PackageAssignment,
    BulkOperation,
    PackageGuide,
    QuickSetup,
    PackageCategoryConfig,
    PackageRating,
    PackageCategory,
    PackageTemplateStatus,
    BulkOperationStatus
)
from app.models.plan import ServicePlan, PlanType, PlanStatus, BillingCycle
from app.models.router import Router
from app.models.user import User
from .service import PlanService
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class PackageTemplateService:
    """Advanced package management service with templates and bulk operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.plan_service = PlanService(db)
        self.logger = get_logger(__name__)

    def _generate_template_code(self, name: str, category: PackageCategory) -> str:
        """Generate unique template code."""
        # Create code from name and category
        name_part = ''.join(c.upper() for c in name if c.isalnum())[:6]
        category_part = category.value.upper()[:3]
        random_part = ''.join(secrets.choice(string.digits) for _ in range(3))
        
        return f"{category_part}-{name_part}-{random_part}"

    async def create_package_template(
        self,
        template_data: Dict[str, Any],
        created_by: int
    ) -> PackageTemplate:
        """Create a new package template."""
        try:
            # Generate unique template code
            template_code = self._generate_template_code(
                template_data['name'], 
                template_data['category']
            )
            
            # Ensure template code is unique
            while await self._template_code_exists(template_code):
                template_code = self._generate_template_code(
                    template_data['name'], 
                    template_data['category']
                )

            # Set default configuration based on category
            if 'configuration_template' not in template_data:
                template_data['configuration_template'] = await self._get_default_configuration(
                    template_data['category']
                )

            # Set default features based on category
            if 'features_template' not in template_data:
                template_data['features_template'] = await self._get_default_features(
                    template_data['category']
                )

            template = PackageTemplate(
                template_code=template_code,
                created_by=created_by,
                **template_data
            )

            self.db.add(template)
            await self.db.commit()
            await self.db.refresh(template)

            self.logger.info(f"Created package template {template_code}: {template_data['name']}")
            return template

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create package template: {e}")
            raise

    async def get_package_templates(
        self,
        pagination: PaginationParams,
        category: Optional[PackageCategory] = None,
        status: Optional[PackageTemplateStatus] = None,
        search: Optional[str] = None,
        is_featured: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Get package templates with filtering and pagination."""
        query = select(PackageTemplate)

        # Apply filters
        if category:
            query = query.where(PackageTemplate.category == category)
        if status:
            query = query.where(PackageTemplate.status == status)
        if is_featured is not None:
            query = query.where(PackageTemplate.is_featured == is_featured)
        if search:
            search_term = f"%{search}%"
            query = query.where(
                or_(
                    PackageTemplate.name.ilike(search_term),
                    PackageTemplate.description.ilike(search_term),
                    PackageTemplate.tags.ilike(search_term)
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        # Get templates with pagination
        query = query.order_by(
            PackageTemplate.sort_order.asc(),
            desc(PackageTemplate.is_featured),
            desc(PackageTemplate.created_at)
        )
        query = query.offset(pagination.offset).limit(pagination.size)
        
        result = await self.db.execute(query)
        templates = result.scalars().all()

        return {
            "items": templates,
            "total": total,
            "page": pagination.page,
            "size": pagination.size,
            "pages": (total + pagination.size - 1) // pagination.size
        }

    async def create_packages_from_template(
        self,
        template_id: int,
        router_ids: List[int],
        created_by: int,
        customizations: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create service plans from a template for multiple routers."""
        template = await self.get_template_by_id(template_id)
        if not template:
            raise ValidationError(f"Template {template_id} not found")

        try:
            # Create bulk operation record
            operation_id = str(uuid.uuid4())
            bulk_operation = BulkOperation(
                operation_id=operation_id,
                operation_type="create_packages_from_template",
                operation_name=f"Create packages from template: {template.name}",
                total_items=len(router_ids),
                operation_data={
                    "template_id": template_id,
                    "router_ids": router_ids,
                    "customizations": customizations or {}
                },
                created_by=created_by
            )

            self.db.add(bulk_operation)
            await self.db.commit()
            await self.db.refresh(bulk_operation)

            # Process packages creation
            created_plans = []
            successful = 0
            failed = 0

            for i, router_id in enumerate(router_ids):
                try:
                    # Verify router exists
                    router = await self.db.get(Router, router_id)
                    if not router:
                        bulk_operation.add_result(
                            str(router_id), 
                            False, 
                            error=f"Router {router_id} not found"
                        )
                        failed += 1
                        continue

                    # Create service plan from template
                    plan_data = {
                        "name": f"{template.name} - {router.name}",
                        "description": f"Generated from template: {template.description}",
                        "plan_type": template.plan_type,
                        "price": template.price_template,
                        "currency": template.currency,
                        "billing_cycle": template.billing_cycle,
                        "download_speed": template.download_speed,
                        "upload_speed": template.upload_speed,
                        "data_limit": template.data_limit,
                        "time_limit": template.time_limit,
                        "validity_days": template.validity_days,
                        "config": template.get_configuration_template()
                    }

                    # Apply customizations
                    if customizations:
                        plan_data.update(customizations)

                    # Create the plan
                    plan = await self.plan_service.create_plan(plan_data)
                    
                    # Create package assignment
                    assignment = PackageAssignment(
                        template_id=template_id,
                        plan_id=plan.id,
                        router_id=router_id,
                        assignment_name=f"{template.name} -> {router.name}",
                        assigned_by=created_by,
                        custom_configuration=customizations
                    )

                    self.db.add(assignment)
                    created_plans.append(plan.id)
                    
                    bulk_operation.add_result(
                        str(router_id),
                        True,
                        data={"plan_id": plan.id, "assignment_id": assignment.id}
                    )
                    successful += 1

                except Exception as e:
                    bulk_operation.add_result(
                        str(router_id),
                        False,
                        error=str(e)
                    )
                    failed += 1

                # Update progress
                bulk_operation.update_progress(
                    processed=i + 1,
                    successful=successful,
                    failed=failed,
                    current_item=f"Router {router_id}"
                )

            # Finalize bulk operation
            bulk_operation.status = BulkOperationStatus.COMPLETED if failed == 0 else BulkOperationStatus.COMPLETED
            bulk_operation.completed_at = datetime.utcnow()

            # Update template usage statistics
            template.usage_count += 1
            if failed == 0:
                # Update success rate
                total_usage = template.usage_count
                current_success_rate = float(template.success_rate)
                new_success_rate = ((current_success_rate * (total_usage - 1)) + 100) / total_usage
                template.success_rate = round(new_success_rate, 2)

            await self.db.commit()

            self.logger.info(f"Created {successful} packages from template {template.name}")

            return {
                "operation_id": operation_id,
                "created_plans": created_plans,
                "successful": successful,
                "failed": failed,
                "total": len(router_ids)
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to create packages from template {template_id}: {e}")
            raise

    async def assign_package_to_devices(
        self,
        template_id: int,
        router_ids: List[int],
        assignment_config: Dict[str, Any],
        assigned_by: int
    ) -> Dict[str, Any]:
        """Assign a package template to multiple devices."""
        template = await self.get_template_by_id(template_id)
        if not template:
            raise ValidationError(f"Template {template_id} not found")

        try:
            assignments_created = []
            successful = 0
            failed = 0

            for router_id in router_ids:
                try:
                    # Verify router exists
                    router = await self.db.get(Router, router_id)
                    if not router:
                        failed += 1
                        continue

                    # Check if assignment already exists
                    existing = await self.db.execute(
                        select(PackageAssignment).where(
                            and_(
                                PackageAssignment.template_id == template_id,
                                PackageAssignment.router_id == router_id,
                                PackageAssignment.is_active == True
                            )
                        )
                    )
                    
                    if existing.scalar_one_or_none():
                        failed += 1  # Already assigned
                        continue

                    # Create assignment
                    assignment = PackageAssignment(
                        template_id=template_id,
                        router_id=router_id,
                        assignment_name=assignment_config.get('name', f"{template.name} -> {router.name}"),
                        assigned_by=assigned_by,
                        auto_create_users=assignment_config.get('auto_create_users', True),
                        custom_configuration=assignment_config.get('custom_configuration')
                    )

                    self.db.add(assignment)
                    assignments_created.append(assignment)
                    successful += 1

                except Exception as e:
                    self.logger.error(f"Failed to assign template to router {router_id}: {e}")
                    failed += 1

            await self.db.commit()

            return {
                "assignments_created": len(assignments_created),
                "successful": successful,
                "failed": failed,
                "total": len(router_ids)
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to assign package template {template_id}: {e}")
            raise

    async def get_quick_setups(
        self,
        scenario: Optional[str] = None,
        difficulty: Optional[str] = None,
        is_recommended: Optional[bool] = None
    ) -> List[QuickSetup]:
        """Get quick setup configurations."""
        query = select(QuickSetup).where(QuickSetup.is_active == True)

        if scenario:
            query = query.where(QuickSetup.scenario == scenario)
        if difficulty:
            query = query.where(QuickSetup.difficulty_level == difficulty)
        if is_recommended is not None:
            query = query.where(QuickSetup.is_recommended == is_recommended)

        query = query.order_by(
            desc(QuickSetup.is_recommended),
            QuickSetup.difficulty_level,
            desc(QuickSetup.success_rate)
        )

        result = await self.db.execute(query)
        return result.scalars().all()

    async def execute_quick_setup(
        self,
        setup_id: int,
        executed_by: int,
        customizations: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a quick setup configuration."""
        setup = await self.db.get(QuickSetup, setup_id)
        if not setup:
            raise ValidationError(f"Quick setup {setup_id} not found")

        try:
            packages_config = setup.get_packages_config()
            router_config = setup.get_router_config()
            
            # Create bulk operation
            operation_id = str(uuid.uuid4())
            bulk_operation = BulkOperation(
                operation_id=operation_id,
                operation_type="execute_quick_setup",
                operation_name=f"Quick setup: {setup.name}",
                total_items=len(packages_config),
                operation_data={
                    "setup_id": setup_id,
                    "packages_config": packages_config,
                    "router_config": router_config,
                    "customizations": customizations or {}
                },
                created_by=executed_by
            )

            self.db.add(bulk_operation)
            await self.db.commit()

            # Execute setup steps
            created_items = []
            successful = 0
            failed = 0

            for i, package_config in enumerate(packages_config):
                try:
                    # Apply customizations
                    if customizations:
                        package_config.update(customizations)

                    # Create service plan
                    plan = await self.plan_service.create_plan(package_config)
                    created_items.append({"type": "plan", "id": plan.id, "name": plan.name})
                    successful += 1

                    bulk_operation.add_result(
                        f"package_{i}",
                        True,
                        data={"plan_id": plan.id, "name": plan.name}
                    )

                except Exception as e:
                    bulk_operation.add_result(
                        f"package_{i}",
                        False,
                        error=str(e)
                    )
                    failed += 1

                # Update progress
                bulk_operation.update_progress(
                    processed=i + 1,
                    successful=successful,
                    failed=failed,
                    current_item=f"Creating package {i+1}/{len(packages_config)}"
                )

            # Update setup statistics
            setup.usage_count += 1
            if failed == 0:
                # Update success rate
                total_usage = setup.usage_count
                current_success_rate = float(setup.success_rate)
                new_success_rate = ((current_success_rate * (total_usage - 1)) + 100) / total_usage
                setup.success_rate = round(new_success_rate, 2)

            # Finalize operation
            bulk_operation.status = BulkOperationStatus.COMPLETED
            bulk_operation.completed_at = datetime.utcnow()

            await self.db.commit()

            return {
                "operation_id": operation_id,
                "created_items": created_items,
                "successful": successful,
                "failed": failed,
                "total": len(packages_config)
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to execute quick setup {setup_id}: {e}")
            raise

    async def get_package_categories(self) -> List[Dict[str, Any]]:
        """Get package categories with configuration."""
        result = await self.db.execute(
            select(PackageCategoryConfig)
            .where(PackageCategoryConfig.is_visible == True)
            .order_by(PackageCategoryConfig.sort_order)
        )
        category_configs = result.scalars().all()

        categories = []
        for config in category_configs:
            # Get template count for category
            template_count = await self.db.execute(
                select(func.count(PackageTemplate.id))
                .where(
                    and_(
                        PackageTemplate.category == config.category,
                        PackageTemplate.status == PackageTemplateStatus.ACTIVE
                    )
                )
            )
            count = template_count.scalar() or 0

            categories.append({
                "category": config.category.value,
                "display_name": config.display_name,
                "description": config.description,
                "icon": config.icon,
                "color": config.color,
                "template_count": count,
                "supports_hotspot": config.supports_hotspot,
                "supports_pppoe": config.supports_pppoe,
                "min_price": float(config.min_price),
                "max_price": float(config.max_price) if config.max_price else None,
                "suggested_prices": [float(p) for p in config.get_suggested_prices()]
            })

        return categories

    async def bulk_create_packages(
        self,
        packages_data: List[Dict[str, Any]],
        created_by: int,
        use_template: Optional[int] = None
    ) -> Dict[str, Any]:
        """Bulk create multiple packages."""
        try:
            # Create bulk operation record
            operation_id = str(uuid.uuid4())
            bulk_operation = BulkOperation(
                operation_id=operation_id,
                operation_type="bulk_create_packages",
                operation_name=f"Bulk create {len(packages_data)} packages",
                total_items=len(packages_data),
                operation_data={
                    "packages_data": packages_data,
                    "template_id": use_template
                },
                created_by=created_by
            )

            self.db.add(bulk_operation)
            await self.db.commit()

            # Get template if specified
            template = None
            if use_template:
                template = await self.get_template_by_id(use_template)

            # Process packages
            created_plans = []
            successful = 0
            failed = 0

            for i, package_data in enumerate(packages_data):
                try:
                    # Apply template defaults if template is specified
                    if template:
                        template_data = {
                            "plan_type": template.plan_type,
                            "download_speed": template.download_speed,
                            "upload_speed": template.upload_speed,
                            "data_limit": template.data_limit,
                            "time_limit": template.time_limit,
                            "validity_days": template.validity_days,
                            "currency": template.currency,
                            "billing_cycle": template.billing_cycle,
                            "config": template.get_configuration_template()
                        }
                        # Merge with provided data (provided data takes precedence)
                        package_data = {**template_data, **package_data}

                    # Create the plan
                    plan = await self.plan_service.create_plan(package_data)
                    created_plans.append(plan.id)
                    successful += 1

                    bulk_operation.add_result(
                        f"package_{i}",
                        True,
                        data={"plan_id": plan.id, "name": plan.name}
                    )

                except Exception as e:
                    bulk_operation.add_result(
                        f"package_{i}",
                        False,
                        error=str(e)
                    )
                    failed += 1

                # Update progress
                bulk_operation.update_progress(
                    processed=i + 1,
                    successful=successful,
                    failed=failed,
                    current_item=f"Creating package {i+1}/{len(packages_data)}"
                )

            # Finalize operation
            bulk_operation.status = BulkOperationStatus.COMPLETED
            bulk_operation.completed_at = datetime.utcnow()

            await self.db.commit()

            return {
                "operation_id": operation_id,
                "created_plans": created_plans,
                "successful": successful,
                "failed": failed,
                "total": len(packages_data)
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to bulk create packages: {e}")
            raise

    async def get_bulk_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get bulk operation status."""
        result = await self.db.execute(
            select(BulkOperation).where(BulkOperation.operation_id == operation_id)
        )
        operation = result.scalar_one_or_none()
        
        if not operation:
            return None

        return {
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "operation_name": operation.operation_name,
            "status": operation.status.value,
            "progress_percentage": float(operation.progress_percentage),
            "total_items": operation.total_items,
            "processed_items": operation.processed_items,
            "successful_items": operation.successful_items,
            "failed_items": operation.failed_items,
            "current_item": operation.current_item,
            "started_at": operation.started_at,
            "completed_at": operation.completed_at,
            "estimated_completion": operation.estimated_completion,
            "error_message": operation.error_message,
            "can_retry": operation.can_retry,
            "results": operation.get_results_data()
        }

    async def get_package_guides(
        self,
        category: Optional[PackageCategory] = None,
        guide_type: Optional[str] = None,
        difficulty: Optional[str] = None
    ) -> List[PackageGuide]:
        """Get package guides and documentation."""
        query = select(PackageGuide).where(PackageGuide.is_published == True)

        if category:
            query = query.where(PackageGuide.category == category)
        if guide_type:
            query = query.where(PackageGuide.guide_type == guide_type)
        if difficulty:
            query = query.where(PackageGuide.difficulty_level == difficulty)

        query = query.order_by(
            desc(PackageGuide.is_featured),
            desc(PackageGuide.helpful_votes),
            desc(PackageGuide.created_at)
        )

        result = await self.db.execute(query)
        return result.scalars().all()

    # Template management methods
    async def get_template_by_id(self, template_id: int) -> Optional[PackageTemplate]:
        """Get package template by ID."""
        return await self.db.get(PackageTemplate, template_id)

    async def update_template(self, template_id: int, updates: Dict[str, Any]) -> Optional[PackageTemplate]:
        """Update a package template."""
        template = await self.get_template_by_id(template_id)
        if not template:
            return None

        try:
            for key, value in updates.items():
                if hasattr(template, key):
                    setattr(template, key, value)

            await self.db.commit()
            await self.db.refresh(template)
            return template

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to update template {template_id}: {e}")
            raise

    async def delete_template(self, template_id: int) -> bool:
        """Delete a package template."""
        template = await self.get_template_by_id(template_id)
        if not template:
            return False

        try:
            # Check if template has active assignments
            result = await self.db.execute(
                select(func.count(PackageAssignment.id))
                .where(
                    and_(
                        PackageAssignment.template_id == template_id,
                        PackageAssignment.is_active == True
                    )
                )
            )
            active_assignments = result.scalar() or 0

            if active_assignments > 0:
                # Don't delete, just mark as archived
                template.status = PackageTemplateStatus.ARCHIVED
                await self.db.commit()
                return True
            else:
                # Safe to delete
                await self.db.delete(template)
                await self.db.commit()
                return True

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to delete template {template_id}: {e}")
            return False

    # Helper methods
    async def _template_code_exists(self, template_code: str) -> bool:
        """Check if template code already exists."""
        result = await self.db.execute(
            select(func.count(PackageTemplate.id)).where(PackageTemplate.template_code == template_code)
        )
        return result.scalar() > 0

    async def _get_default_configuration(self, category: PackageCategory) -> Dict[str, Any]:
        """Get default configuration for package category."""
        config_map = {
            PackageCategory.HOTSPOT: {
                "service_type": "hotspot",
                "interface": "ether2",
                "ip_pool": "172.31.0.0/16",
                "dns_servers": ["8.8.8.8", "8.8.4.4"],
                "enable_anti_sharing": True,
                "session_timeout": "1d",
                "idle_timeout": "5m"
            },
            PackageCategory.PPPOE: {
                "service_type": "pppoe",
                "interface": "ether2",
                "ip_pool": "172.31.0.0/16",
                "dns_servers": ["8.8.8.8", "8.8.4.4"],
                "mtu": 1500,
                "mru": 1500
            },
            PackageCategory.DATA_PLANS: {
                "service_type": "both",
                "data_tracking": True,
                "fup_enabled": True,
                "speed_limiting": True
            },
            PackageCategory.FREE_TRIAL: {
                "service_type": "hotspot",
                "trial_duration_hours": 24,
                "bandwidth_limit": "1M/1M",
                "data_limit_mb": 100
            }
        }
        
        return config_map.get(category, {})

    async def _get_default_features(self, category: PackageCategory) -> Dict[str, Any]:
        """Get default features for package category."""
        feature_map = {
            PackageCategory.HOTSPOT: {
                "captive_portal": True,
                "bandwidth_limiting": True,
                "time_limiting": True,
                "data_limiting": True,
                "user_isolation": False,
                "walled_garden": True
            },
            PackageCategory.PPPOE: {
                "bandwidth_limiting": True,
                "time_limiting": True,
                "data_limiting": True,
                "static_ip": False,
                "radius_auth": True,
                "accounting": True
            },
            PackageCategory.DATA_PLANS: {
                "data_tracking": True,
                "fup_support": True,
                "speed_boost": False,
                "rollover": False
            },
            PackageCategory.FREE_TRIAL: {
                "limited_access": True,
                "upgrade_prompts": True,
                "usage_notifications": True
            }
        }
        
        return feature_map.get(category, {})
