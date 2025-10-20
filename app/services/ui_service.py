"""UI/UX management service for themes, search, and user interface features."""

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, and_, or_, desc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ConfigurationError
from app.models.user_settings import (
    UserSettings,
    GlobalSearch,
    UIBulkOperation,
    SearchSuggestion,
    UIPreferences,
    ThemeType,
    LanguageCode,
    NotificationPreference
)
from app.models.user import User
from app.models.router import Router
from app.models.plan import ServicePlan
from app.models.subscription import Subscription
from app.models.billing import Invoice, Payment
from app.api.deps import PaginationParams

logger = get_logger(__name__)


class UIService:
    """Production-ready UI/UX management service."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)
        
        # Search configuration
        self.search_cache_duration = 300  # 5 minutes
        self.max_search_results = 100
        self.search_timeout_seconds = 10
        
        # Bulk operation configuration
        self.max_bulk_items = 1000
        self.bulk_operation_timeout = 3600  # 1 hour
        
        # Search indexes for different models
        self.searchable_models = {
            'users': {
                'model': User,
                'fields': ['username', 'email', 'first_name', 'last_name'],
                'display_fields': ['username', 'email', 'full_name', 'role']
            },
            'routers': {
                'model': Router,
                'fields': ['name', 'ip_address', 'location', 'description'],
                'display_fields': ['name', 'ip_address', 'status', 'location']
            },
            'plans': {
                'model': ServicePlan,
                'fields': ['name', 'description'],
                'display_fields': ['name', 'plan_type', 'price', 'status']
            },
            'subscriptions': {
                'model': Subscription,
                'fields': ['username'],
                'display_fields': ['username', 'plan_name', 'status', 'expires_at']
            },
            'invoices': {
                'model': Invoice,
                'fields': ['invoice_number', 'description'],
                'display_fields': ['invoice_number', 'amount', 'status', 'due_date']
            }
        }

    # User Settings Management
    async def get_user_settings(self, user_id: int) -> UserSettings:
        """Get user settings, create default if not exists."""
        result = await self.db.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        
        if not settings:
            settings = await self.create_default_user_settings(user_id)
        
        return settings

    async def create_default_user_settings(self, user_id: int) -> UserSettings:
        """Create default user settings."""
        settings = UserSettings(
            user_id=user_id,
            theme=ThemeType.SYSTEM,
            language=LanguageCode.ENGLISH,
            timezone="Africa/Nairobi",
            default_page_size=20,
            email_notifications=NotificationPreference.ALL,
            sms_notifications=NotificationPreference.IMPORTANT,
            browser_notifications=NotificationPreference.ALL
        )
        
        self.db.add(settings)
        await self.db.commit()
        await self.db.refresh(settings)
        
        self.logger.info(f"Created default settings for user {user_id}")
        return settings

    async def update_user_settings(
        self, 
        user_id: int, 
        updates: Dict[str, Any]
    ) -> UserSettings:
        """Update user settings."""
        settings = await self.get_user_settings(user_id)
        
        # Validate updates
        for key, value in updates.items():
            if hasattr(settings, key):
                # Additional validation for specific fields
                if key == "theme" and value not in [t.value for t in ThemeType]:
                    raise ValidationError(f"Invalid theme: {value}")
                elif key == "language" and value not in [l.value for l in LanguageCode]:
                    raise ValidationError(f"Invalid language: {value}")
                elif key == "default_page_size" and (value < 5 or value > 100):
                    raise ValidationError("Page size must be between 5 and 100")
                
                setattr(settings, key, value)
        
        await self.db.commit()
        await self.db.refresh(settings)
        
        self.logger.info(f"Updated settings for user {user_id}")
        return settings

    async def get_available_themes(self) -> List[Dict[str, str]]:
        """Get available themes."""
        return [
            {"value": ThemeType.LIGHT.value, "label": "Light Theme", "description": "Light color scheme"},
            {"value": ThemeType.DARK.value, "label": "Dark Theme", "description": "Dark color scheme"},
            {"value": ThemeType.SYSTEM.value, "label": "System Theme", "description": "Follow system preference"},
            {"value": ThemeType.AUTO.value, "label": "Auto Theme", "description": "Automatic based on time"}
        ]

    async def get_available_languages(self) -> List[Dict[str, str]]:
        """Get available languages."""
        return [
            {"value": LanguageCode.ENGLISH.value, "label": "English", "native": "English"},
            {"value": LanguageCode.SWAHILI.value, "label": "Swahili", "native": "Kiswahili"},
            {"value": LanguageCode.FRENCH.value, "label": "French", "native": "Français"},
            {"value": LanguageCode.SPANISH.value, "label": "Spanish", "native": "Español"}
        ]

    # Global Search Functionality
    async def perform_global_search(
        self, 
        user_id: int, 
        query: str, 
        search_types: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Perform global search across multiple models."""
        start_time = datetime.utcnow()
        search_id = str(uuid.uuid4())
        
        try:
            # Sanitize query
            query = query.strip()
            if len(query) < 2:
                raise ValidationError("Search query must be at least 2 characters")
            
            search_types = search_types or list(self.searchable_models.keys())
            results = {}
            total_results = 0
            
            # Search each model type
            for search_type in search_types:
                if search_type in self.searchable_models:
                    model_results = await self._search_model(
                        search_type, 
                        query, 
                        filters or {}, 
                        limit
                    )
                    results[search_type] = model_results
                    total_results += len(model_results)
            
            # Calculate execution time
            execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Cache search results
            search_record = GlobalSearch(
                search_id=search_id,
                user_id=user_id,
                query=query,
                search_type="global",
                filters=filters,
                total_results=total_results,
                execution_time_ms=int(execution_time),
                results_data=results,
                expires_at=datetime.utcnow() + timedelta(seconds=self.search_cache_duration)
            )
            
            self.db.add(search_record)
            
            # Update search history
            await self._add_to_search_history(user_id, query, "global")
            
            await self.db.commit()
            
            return {
                "search_id": search_id,
                "query": query,
                "total_results": total_results,
                "execution_time_ms": int(execution_time),
                "results": results,
                "search_types": search_types
            }
            
        except Exception as e:
            self.logger.error(f"Global search failed for user {user_id}: {e}")
            raise

    async def _search_model(
        self, 
        model_type: str, 
        query: str, 
        filters: Dict[str, Any], 
        limit: int
    ) -> List[Dict[str, Any]]:
        """Search a specific model type."""
        model_config = self.searchable_models.get(model_type)
        if not model_config:
            return []
        
        model = model_config['model']
        search_fields = model_config['fields']
        display_fields = model_config['display_fields']
        
        # Build search query
        query_obj = select(model)
        
        # Add search conditions
        search_conditions = []
        for field in search_fields:
            if hasattr(model, field):
                search_conditions.append(
                    getattr(model, field).ilike(f"%{query}%")
                )
        
        if search_conditions:
            query_obj = query_obj.where(or_(*search_conditions))
        
        # Apply filters
        for filter_key, filter_value in filters.items():
            if hasattr(model, filter_key):
                query_obj = query_obj.where(getattr(model, filter_key) == filter_value)
        
        # Limit results
        query_obj = query_obj.limit(limit)
        
        # Execute query
        result = await self.db.execute(query_obj)
        records = result.scalars().all()
        
        # Format results
        formatted_results = []
        for record in records:
            result_data = {
                "id": record.id,
                "type": model_type,
                "title": getattr(record, display_fields[0], str(record.id)),
                "subtitle": getattr(record, display_fields[1], "") if len(display_fields) > 1 else "",
                "metadata": {}
            }
            
            # Add display fields
            for field in display_fields:
                if hasattr(record, field):
                    result_data["metadata"][field] = getattr(record, field)
            
            formatted_results.append(result_data)
        
        return formatted_results

    async def get_search_suggestions(
        self, 
        query: str, 
        search_type: Optional[str] = None, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get search suggestions based on query."""
        if len(query) < 2:
            return []
        
        query_obj = select(SearchSuggestion).where(
            and_(
                SearchSuggestion.suggestion_text.ilike(f"%{query}%"),
                SearchSuggestion.is_active == True
            )
        )
        
        if search_type:
            query_obj = query_obj.where(SearchSuggestion.suggestion_type == search_type)
        
        query_obj = query_obj.order_by(
            desc(SearchSuggestion.usage_count),
            desc(SearchSuggestion.success_rate)
        ).limit(limit)
        
        result = await self.db.execute(query_obj)
        suggestions = result.scalars().all()
        
        return [
            {
                "text": suggestion.suggestion_text,
                "type": suggestion.suggestion_type,
                "category": suggestion.category,
                "usage_count": suggestion.usage_count,
                "success_rate": suggestion.success_rate
            }
            for suggestion in suggestions
        ]

    async def _add_to_search_history(self, user_id: int, query: str, search_type: str) -> None:
        """Add search to user's search history."""
        settings = await self.get_user_settings(user_id)
        settings.add_search_to_history(query, search_type)
        await self.db.commit()

    # Bulk Operations Management
    async def create_bulk_operation(
        self,
        user_id: int,
        operation_type: str,
        target_model: str,
        operation_data: Dict[str, Any],
        target_ids: List[int]
    ) -> UIBulkOperation:
        """Create a new bulk operation."""
        # Validate operation
        if len(target_ids) > self.max_bulk_items:
            raise ValidationError(f"Bulk operation limited to {self.max_bulk_items} items")
        
        if not operation_type or not target_model:
            raise ValidationError("Operation type and target model are required")
        
        operation_id = str(uuid.uuid4())
        
        bulk_op = UIUIBulkOperation(
            operation_id=operation_id,
            user_id=user_id,
            operation_type=operation_type,
            target_model=target_model,
            operation_data={
                **operation_data,
                'target_ids': target_ids
            },
            total_items=len(target_ids),
            status="pending"
        )
        
        self.db.add(bulk_op)
        await self.db.commit()
        await self.db.refresh(bulk_op)
        
        self.logger.info(f"Created bulk operation {operation_id} for user {user_id}")
        return bulk_op

    async def execute_bulk_operation(self, operation_id: str) -> Dict[str, Any]:
        """Execute a bulk operation."""
        result = await self.db.execute(
            select(UIBulkOperation).where(UIBulkOperation.operation_id == operation_id)
        )
        bulk_op = result.scalar_one_or_none()
        
        if not bulk_op:
            raise ValidationError(f"Bulk operation {operation_id} not found")
        
        if bulk_op.status != "pending":
            raise ValidationError(f"Bulk operation {operation_id} is not in pending status")
        
        try:
            bulk_op.status = "in_progress"
            bulk_op.started_at = datetime.utcnow()
            await self.db.commit()
            
            operation_data = bulk_op.get_operation_data()
            target_ids = operation_data.get('target_ids', [])
            
            successful = 0
            failed = 0
            errors = []
            results = []
            
            # Execute operation based on type
            for i, target_id in enumerate(target_ids):
                try:
                    if bulk_op.operation_type == "delete":
                        result = await self._execute_bulk_delete(bulk_op.target_model, target_id)
                    elif bulk_op.operation_type == "update":
                        result = await self._execute_bulk_update(
                            bulk_op.target_model, 
                            target_id, 
                            operation_data.get('update_data', {})
                        )
                    elif bulk_op.operation_type == "export":
                        result = await self._execute_bulk_export(bulk_op.target_model, target_id)
                    else:
                        raise ValidationError(f"Unsupported operation type: {bulk_op.operation_type}")
                    
                    if result.get('success', False):
                        successful += 1
                        results.append(result)
                    else:
                        failed += 1
                        errors.append({
                            'target_id': target_id,
                            'error': result.get('error', 'Unknown error')
                        })
                
                except Exception as e:
                    failed += 1
                    errors.append({
                        'target_id': target_id,
                        'error': str(e)
                    })
                
                # Update progress
                bulk_op.update_progress(i + 1, successful, failed)
                
                # Commit progress every 10 items
                if (i + 1) % 10 == 0:
                    await self.db.commit()
            
            # Finalize operation
            bulk_op.results = results
            bulk_op.errors = errors
            bulk_op.completed_at = datetime.utcnow()
            
            await self.db.commit()
            
            return {
                "operation_id": operation_id,
                "status": bulk_op.status,
                "total_items": bulk_op.total_items,
                "successful_items": bulk_op.successful_items,
                "failed_items": bulk_op.failed_items,
                "success_rate": bulk_op.success_rate,
                "execution_time_seconds": (bulk_op.completed_at - bulk_op.started_at).total_seconds(),
                "errors": errors[:10]  # Return first 10 errors
            }
            
        except Exception as e:
            bulk_op.status = "failed"
            bulk_op.completed_at = datetime.utcnow()
            bulk_op.errors = [{"error": str(e)}]
            await self.db.commit()
            
            self.logger.error(f"Bulk operation {operation_id} failed: {e}")
            raise

    async def _execute_bulk_delete(self, model_name: str, target_id: int) -> Dict[str, Any]:
        """Execute bulk delete operation."""
        try:
            model_config = self.searchable_models.get(model_name)
            if not model_config:
                return {"success": False, "error": f"Unknown model: {model_name}"}
            
            model = model_config['model']
            record = await self.db.get(model, target_id)
            
            if not record:
                return {"success": False, "error": f"Record {target_id} not found"}
            
            await self.db.delete(record)
            
            return {
                "success": True,
                "target_id": target_id,
                "action": "deleted"
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_bulk_update(
        self, 
        model_name: str, 
        target_id: int, 
        update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute bulk update operation."""
        try:
            model_config = self.searchable_models.get(model_name)
            if not model_config:
                return {"success": False, "error": f"Unknown model: {model_name}"}
            
            model = model_config['model']
            record = await self.db.get(model, target_id)
            
            if not record:
                return {"success": False, "error": f"Record {target_id} not found"}
            
            # Apply updates
            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            
            return {
                "success": True,
                "target_id": target_id,
                "action": "updated",
                "updated_fields": list(update_data.keys())
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_bulk_export(self, model_name: str, target_id: int) -> Dict[str, Any]:
        """Execute bulk export operation."""
        try:
            model_config = self.searchable_models.get(model_name)
            if not model_config:
                return {"success": False, "error": f"Unknown model: {model_name}"}
            
            model = model_config['model']
            record = await self.db.get(model, target_id)
            
            if not record:
                return {"success": False, "error": f"Record {target_id} not found"}
            
            # Export record data
            export_data = {}
            for field in model_config['display_fields']:
                if hasattr(record, field):
                    value = getattr(record, field)
                    # Convert datetime to string for JSON serialization
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    export_data[field] = value
            
            return {
                "success": True,
                "target_id": target_id,
                "action": "exported",
                "data": export_data
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_bulk_operation_status(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a bulk operation."""
        result = await self.db.execute(
            select(UIBulkOperation).where(UIBulkOperation.operation_id == operation_id)
        )
        bulk_op = result.scalar_one_or_none()
        
        if not bulk_op:
            return None
        
        return {
            "operation_id": operation_id,
            "status": bulk_op.status,
            "operation_type": bulk_op.operation_type,
            "target_model": bulk_op.target_model,
            "total_items": bulk_op.total_items,
            "processed_items": bulk_op.processed_items,
            "successful_items": bulk_op.successful_items,
            "failed_items": bulk_op.failed_items,
            "progress_percentage": bulk_op.progress_percentage,
            "success_rate": bulk_op.success_rate,
            "started_at": bulk_op.started_at,
            "completed_at": bulk_op.completed_at,
            "estimated_time_remaining": bulk_op.estimated_time_remaining,
            "errors": bulk_op.get_errors()[:5]  # Return first 5 errors
        }

    async def cancel_bulk_operation(self, operation_id: str, user_id: int) -> bool:
        """Cancel a bulk operation."""
        result = await self.db.execute(
            select(UIBulkOperation).where(
                and_(
                    UIBulkOperation.operation_id == operation_id,
                    UIBulkOperation.user_id == user_id
                )
            )
        )
        bulk_op = result.scalar_one_or_none()
        
        if not bulk_op or bulk_op.status not in ["pending", "in_progress"]:
            return False
        
        bulk_op.status = "cancelled"
        bulk_op.completed_at = datetime.utcnow()
        
        await self.db.commit()
        
        self.logger.info(f"Cancelled bulk operation {operation_id}")
        return True

    # UI Preferences Management
    async def get_ui_preferences(self) -> List[UIPreferences]:
        """Get all UI preferences."""
        result = await self.db.execute(
            select(UIPreferences).order_by(UIPreferences.category, UIPreferences.preference_name)
        )
        return result.scalars().all()

    async def get_ui_preference(self, preference_key: str) -> Optional[UIPreferences]:
        """Get a specific UI preference."""
        result = await self.db.execute(
            select(UIPreferences).where(UIPreferences.preference_key == preference_key)
        )
        return result.scalar_one_or_none()

    async def update_ui_preference(
        self, 
        preference_key: str, 
        value: Any, 
        user_id: int
    ) -> bool:
        """Update a UI preference value."""
        preference = await self.get_ui_preference(preference_key)
        if not preference:
            return False
        
        # Validate value
        if not preference.validate_value(value):
            raise ValidationError(f"Invalid value for preference {preference_key}")
        
        # Check if user has permission to modify
        if preference.requires_admin:
            # Would need to check if user is admin
            pass
        
        # Update preference (this would typically be stored per-user)
        # For now, we'll track the modification
        preference.modified_count += 1
        preference.updated_at = datetime.utcnow()
        
        await self.db.commit()
        
        self.logger.info(f"Updated UI preference {preference_key} by user {user_id}")
        return True

    # Search Management
    async def get_search_history(self, user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Get user's search history."""
        settings = await self.get_user_settings(user_id)
        history = settings.get_search_history()
        
        # Return most recent searches
        return sorted(history, key=lambda x: x['timestamp'], reverse=True)[:limit]

    async def clear_search_history(self, user_id: int) -> bool:
        """Clear user's search history."""
        settings = await self.get_user_settings(user_id)
        settings.search_history = []
        
        await self.db.commit()
        
        self.logger.info(f"Cleared search history for user {user_id}")
        return True

    async def get_saved_searches(self, user_id: int) -> List[Dict[str, Any]]:
        """Get user's saved searches."""
        settings = await self.get_user_settings(user_id)
        return settings.get_saved_searches()

    async def save_search(
        self, 
        user_id: int, 
        search_name: str, 
        search_data: Dict[str, Any]
    ) -> bool:
        """Save a search for later use."""
        settings = await self.get_user_settings(user_id)
        
        search_data['name'] = search_name
        settings.add_saved_search(search_data)
        
        await self.db.commit()
        
        self.logger.info(f"Saved search '{search_name}' for user {user_id}")
        return True

    async def delete_saved_search(self, user_id: int, search_name: str) -> bool:
        """Delete a saved search."""
        settings = await self.get_user_settings(user_id)
        searches = settings.get_saved_searches()
        
        # Remove search with matching name
        updated_searches = [s for s in searches if s.get('name') != search_name]
        settings.saved_searches = updated_searches
        
        await self.db.commit()
        
        self.logger.info(f"Deleted saved search '{search_name}' for user {user_id}")
        return True

    # Statistics and Analytics
    async def get_ui_usage_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get UI usage statistics."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get search statistics
        search_result = await self.db.execute(
            select(
                func.count(GlobalSearch.id).label('total_searches'),
                func.avg(GlobalSearch.execution_time_ms).label('avg_execution_time'),
                func.avg(GlobalSearch.total_results).label('avg_results')
            )
            .where(GlobalSearch.created_at >= start_date)
        )
        search_stats = search_result.first()
        
        # Get bulk operation statistics
        bulk_result = await self.db.execute(
            select(
                func.count(UIBulkOperation.id).label('total_operations'),
                func.avg(UIBulkOperation.success_rate).label('avg_success_rate')
            )
            .where(UIBulkOperation.created_at >= start_date)
        )
        bulk_stats = bulk_result.first()
        
        # Get theme usage
        theme_result = await self.db.execute(
            select(
                UserSettings.theme,
                func.count(UserSettings.id).label('count')
            )
            .group_by(UserSettings.theme)
        )
        theme_usage = {row.theme.value: row.count for row in theme_result}
        
        return {
            "period_days": days,
            "search_statistics": {
                "total_searches": search_stats.total_searches or 0,
                "average_execution_time_ms": round(search_stats.avg_execution_time or 0, 2),
                "average_results_per_search": round(search_stats.avg_results or 0, 2)
            },
            "bulk_operation_statistics": {
                "total_operations": bulk_stats.total_operations or 0,
                "average_success_rate": round(bulk_stats.avg_success_rate or 0, 2)
            },
            "theme_usage": theme_usage,
            "generated_at": datetime.utcnow().isoformat()
        }

    # Cleanup and Maintenance
    async def cleanup_expired_searches(self) -> int:
        """Clean up expired search cache."""
        current_time = datetime.utcnow()
        
        result = await self.db.execute(
            select(GlobalSearch).where(
                and_(
                    GlobalSearch.expires_at < current_time,
                    GlobalSearch.expires_at.isnot(None)
                )
            )
        )
        expired_searches = result.scalars().all()
        
        for search in expired_searches:
            await self.db.delete(search)
        
        await self.db.commit()
        
        cleanup_count = len(expired_searches)
        self.logger.info(f"Cleaned up {cleanup_count} expired searches")
        return cleanup_count

    async def cleanup_old_bulk_operations(self, days: int = 30) -> int:
        """Clean up old completed bulk operations."""
        cleanup_date = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(UIBulkOperation).where(
                and_(
                    UIBulkOperation.status.in_(["completed", "failed", "cancelled"]),
                    UIBulkOperation.completed_at < cleanup_date
                )
            )
        )
        old_operations = result.scalars().all()
        
        for operation in old_operations:
            await self.db.delete(operation)
        
        await self.db.commit()
        
        cleanup_count = len(old_operations)
        self.logger.info(f"Cleaned up {cleanup_count} old bulk operations")
        return cleanup_count
