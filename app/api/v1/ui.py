"""UI/UX management API endpoints."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.core.database import get_db
from app.models.user import User
from app.schemas.ui import (
    UserSettings,
    UserSettingsUpdate,
    GlobalSearchRequest,
    GlobalSearchResponse,
    SearchSuggestionResponse,
    BulkOperationRequest,
    BulkOperationResponse,
    BulkOperationStatus,
    ThemeOption,
    LanguageOption,
    UIPreferenceUpdate,
    UIPreferenceResponse,
    DashboardLayoutUpdate,
    SavedSearchCreate,
    SavedSearchResponse,
    QuickFilterCreate,
    QuickFilterResponse,
    UIUsageStats
)
from app.services.ui_service import UIService
from app.core.exceptions import ValidationError

router = APIRouter()


# User Settings Endpoints
@router.get("/settings", response_model=UserSettings)
async def get_user_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettings:
    """Get current user's UI settings."""
    service = UIService(db)
    settings = await service.get_user_settings(current_user.id)
    return settings


@router.patch("/settings", response_model=UserSettings)
async def update_user_settings(
    settings_data: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserSettings:
    """Update current user's UI settings."""
    service = UIService(db)
    
    try:
        settings = await service.update_user_settings(
            current_user.id,
            settings_data.dict(exclude_unset=True)
        )
        return settings
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/themes", response_model=List[ThemeOption])
async def get_available_themes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ThemeOption]:
    """Get available UI themes."""
    service = UIService(db)
    themes = await service.get_available_themes()
    
    return [
        ThemeOption(
            value=theme["value"],
            label=theme["label"],
            description=theme["description"],
            preview_colors={
                "primary": "#3b82f6" if theme["value"] == "light" else "#60a5fa",
                "background": "#ffffff" if theme["value"] == "light" else "#1f2937",
                "text": "#1f2937" if theme["value"] == "light" else "#f9fafb"
            }
        )
        for theme in themes
    ]


@router.post("/themes/{theme_name}")
async def set_user_theme(
    theme_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Set user's theme preference."""
    service = UIService(db)
    
    try:
        # Validate theme
        if theme_name not in [t.value for t in ThemeType]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid theme: {theme_name}"
            )
        
        await service.update_user_settings(current_user.id, {"theme": theme_name})
        
        return {"message": f"Theme updated to {theme_name}", "theme": theme_name}
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/languages", response_model=List[LanguageOption])
async def get_available_languages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LanguageOption]:
    """Get available UI languages."""
    service = UIService(db)
    languages = await service.get_available_languages()
    
    return [
        LanguageOption(
            value=lang["value"],
            label=lang["label"],
            native=lang["native"],
            flag=f"flag-{lang['value']}"
        )
        for lang in languages
    ]


# Global Search Endpoints
@router.post("/search", response_model=GlobalSearchResponse)
async def perform_global_search(
    search_request: GlobalSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalSearchResponse:
    """Perform global search across all models."""
    service = UIService(db)
    
    try:
        results = await service.perform_global_search(
            user_id=current_user.id,
            query=search_request.query,
            search_types=search_request.search_types,
            filters=search_request.filters,
            limit=search_request.limit
        )
        
        # Add suggestions if requested
        suggestions = None
        if search_request.include_suggestions:
            suggestions = await service.get_search_suggestions(
                search_request.query,
                limit=5
            )
        
        return GlobalSearchResponse(
            **results,
            suggestions=suggestions
        )
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/search/suggestions", response_model=List[SearchSuggestionResponse])
async def get_search_suggestions(
    query: str = Query(..., min_length=1, max_length=100),
    search_type: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SearchSuggestionResponse]:
    """Get search suggestions for autocomplete."""
    service = UIService(db)
    
    suggestions = await service.get_search_suggestions(
        query=query,
        search_type=search_type,
        limit=limit
    )
    
    return [SearchSuggestionResponse(**suggestion) for suggestion in suggestions]


@router.get("/search/history", response_model=List[Dict[str, Any]])
async def get_search_history(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Get user's search history."""
    service = UIService(db)
    history = await service.get_search_history(current_user.id, limit)
    return history


@router.delete("/search/history")
async def clear_search_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Clear user's search history."""
    service = UIService(db)
    success = await service.clear_search_history(current_user.id)
    
    if success:
        return {"message": "Search history cleared successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear search history"
        )


# Saved Searches Endpoints
@router.get("/searches/saved", response_model=List[SavedSearchResponse])
async def get_saved_searches(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[SavedSearchResponse]:
    """Get user's saved searches."""
    service = UIService(db)
    searches = await service.get_saved_searches(current_user.id)
    
    return [SavedSearchResponse(**search) for search in searches]


@router.post("/searches/saved", response_model=Dict[str, str])
async def save_search(
    search_data: SavedSearchCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Save a search for later use."""
    service = UIService(db)
    
    try:
        success = await service.save_search(
            user_id=current_user.id,
            search_name=search_data.name,
            search_data=search_data.dict(exclude={'name'})
        )
        
        if success:
            return {"message": f"Search '{search_data.name}' saved successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save search"
            )
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/searches/saved/{search_name}")
async def delete_saved_search(
    search_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Delete a saved search."""
    service = UIService(db)
    
    success = await service.delete_saved_search(current_user.id, search_name)
    
    if success:
        return {"message": f"Search '{search_name}' deleted successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Saved search '{search_name}' not found"
        )


# Bulk Operations Endpoints
@router.post("/bulk-operations", response_model=BulkOperationResponse)
async def create_bulk_operation(
    operation_request: BulkOperationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkOperationResponse:
    """Create and optionally execute a bulk operation."""
    service = UIService(db)
    
    try:
        # Validate destructive operations require confirmation
        destructive_ops = ['delete', 'suspend', 'deactivate']
        if operation_request.operation_type in destructive_ops and not operation_request.confirm_operation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Confirmation required for {operation_request.operation_type} operation"
            )
        
        # Create bulk operation
        bulk_op = await service.create_bulk_operation(
            user_id=current_user.id,
            operation_type=operation_request.operation_type,
            target_model=operation_request.target_model,
            operation_data=operation_request.operation_data or {},
            target_ids=operation_request.target_ids
        )
        
        # Execute in background
        background_tasks.add_task(service.execute_bulk_operation, bulk_op.operation_id)
        
        return BulkOperationResponse(
            operation_id=bulk_op.operation_id,
            status=bulk_op.status,
            operation_type=bulk_op.operation_type,
            target_model=bulk_op.target_model,
            total_items=bulk_op.total_items,
            processed_items=bulk_op.processed_items,
            successful_items=bulk_op.successful_items,
            failed_items=bulk_op.failed_items,
            progress_percentage=bulk_op.progress_percentage,
            success_rate=bulk_op.success_rate,
            started_at=bulk_op.started_at,
            completed_at=bulk_op.completed_at,
            estimated_time_remaining=bulk_op.estimated_time_remaining,
            errors=[]
        )
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/bulk-operations/{operation_id}", response_model=BulkOperationResponse)
async def get_bulk_operation_status(
    operation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BulkOperationResponse:
    """Get status of a bulk operation."""
    service = UIService(db)
    
    status_data = await service.get_bulk_operation_status(operation_id)
    if not status_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bulk operation {operation_id} not found"
        )
    
    return BulkOperationResponse(**status_data)


@router.post("/bulk-operations/{operation_id}/cancel")
async def cancel_bulk_operation(
    operation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Cancel a bulk operation."""
    service = UIService(db)
    
    success = await service.cancel_bulk_operation(operation_id, current_user.id)
    
    if success:
        return {"message": f"Bulk operation {operation_id} cancelled successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel bulk operation {operation_id}"
        )


# Dashboard and Layout Endpoints
@router.get("/dashboard/layout", response_model=Dict[str, Any])
async def get_dashboard_layout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get user's dashboard layout."""
    service = UIService(db)
    settings = await service.get_user_settings(current_user.id)
    
    layout = settings.get_dashboard_layout()
    if not layout:
        # Return default layout
        layout = {
            "widgets": [
                {"id": "revenue", "position": {"x": 0, "y": 0, "w": 6, "h": 3}},
                {"id": "users", "position": {"x": 6, "y": 0, "w": 6, "h": 3}},
                {"id": "routers", "position": {"x": 0, "y": 3, "w": 4, "h": 4}},
                {"id": "recent_activity", "position": {"x": 4, "y": 3, "w": 8, "h": 4}}
            ],
            "columns": 12,
            "row_height": 60
        }
    
    return {"layout": layout}


@router.post("/dashboard/layout")
async def update_dashboard_layout(
    layout_data: DashboardLayoutUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Update user's dashboard layout."""
    service = UIService(db)
    
    try:
        settings = await service.get_user_settings(current_user.id)
        settings.set_dashboard_layout(layout_data.layout)
        
        await db.commit()
        
        return {"message": "Dashboard layout updated successfully"}
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Quick Filters Endpoints
@router.get("/filters/quick", response_model=List[QuickFilterResponse])
async def get_quick_filters(
    page: Optional[str] = Query(None, description="Filter by page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[QuickFilterResponse]:
    """Get user's quick filters."""
    service = UIService(db)
    settings = await service.get_user_settings(current_user.id)
    
    filters = settings.get_quick_filters()
    
    if page:
        filters = [f for f in filters if f.get('page') == page]
    
    return [QuickFilterResponse(**filter_data) for filter_data in filters]


@router.post("/filters/quick", response_model=Dict[str, str])
async def create_quick_filter(
    filter_data: QuickFilterCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Create a new quick filter."""
    service = UIService(db)
    
    try:
        settings = await service.get_user_settings(current_user.id)
        settings.add_quick_filter(filter_data.dict())
        
        await db.commit()
        
        return {"message": f"Quick filter '{filter_data.name}' created successfully"}
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# UI Preferences Endpoints
@router.get("/preferences", response_model=List[UIPreferenceResponse])
async def get_ui_preferences(
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[UIPreferenceResponse]:
    """Get UI preferences."""
    service = UIService(db)
    preferences = await service.get_ui_preferences()
    
    if category:
        preferences = [p for p in preferences if p.category == category]
    
    return [
        UIPreferenceResponse(
            preference_key=pref.preference_key,
            preference_name=pref.preference_name,
            category=pref.category,
            current_value=pref.get_default_value(),
            default_value=pref.get_default_value(),
            allowed_values=pref.get_allowed_values(),
            value_type=pref.value_type,
            description=pref.description,
            is_user_configurable=pref.is_user_configurable,
            requires_admin=pref.requires_admin
        )
        for pref in preferences
    ]


@router.post("/preferences", response_model=Dict[str, str])
async def update_ui_preference(
    preference_data: UIPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    """Update a UI preference."""
    service = UIService(db)
    
    try:
        success = await service.update_ui_preference(
            preference_key=preference_data.preference_key,
            value=preference_data.value,
            user_id=current_user.id
        )
        
        if success:
            return {"message": f"Preference '{preference_data.preference_key}' updated successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preference '{preference_data.preference_key}' not found"
            )
    
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# Statistics Endpoints
@router.get("/stats", response_model=UIUsageStats)
async def get_ui_usage_stats(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> UIUsageStats:
    """Get UI usage statistics (admin only)."""
    service = UIService(db)
    
    stats = await service.get_ui_usage_stats(days=days)
    return UIUsageStats(**stats)


# Maintenance Endpoints
@router.post("/maintenance/cleanup-searches", response_model=Dict[str, int])
async def cleanup_expired_searches(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, int]:
    """Clean up expired search cache (admin only)."""
    service = UIService(db)
    
    cleanup_count = await service.cleanup_expired_searches()
    return {"cleaned_up_searches": cleanup_count}


@router.post("/maintenance/cleanup-bulk-operations", response_model=Dict[str, int])
async def cleanup_old_bulk_operations(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, int]:
    """Clean up old bulk operations (admin only)."""
    service = UIService(db)
    
    cleanup_count = await service.cleanup_old_bulk_operations(days=days)
    return {"cleaned_up_operations": cleanup_count}


# Utility Endpoints
@router.get("/search-types", response_model=List[Dict[str, str]])
async def get_available_search_types(
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, str]]:
    """Get available search types."""
    return [
        {"value": "users", "label": "Users", "description": "Search users by name, email, username"},
        {"value": "routers", "label": "Routers", "description": "Search routers by name, IP, location"},
        {"value": "plans", "label": "Service Plans", "description": "Search plans by name, description"},
        {"value": "subscriptions", "label": "Subscriptions", "description": "Search subscriptions by username"},
        {"value": "invoices", "label": "Invoices", "description": "Search invoices by number, description"}
    ]


@router.get("/bulk-operation-types", response_model=List[Dict[str, str]])
async def get_bulk_operation_types(
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, str]]:
    """Get available bulk operation types."""
    return [
        {"value": "delete", "label": "Delete", "description": "Delete selected items", "destructive": True},
        {"value": "update", "label": "Update", "description": "Update selected items", "destructive": False},
        {"value": "export", "label": "Export", "description": "Export selected items", "destructive": False},
        {"value": "activate", "label": "Activate", "description": "Activate selected items", "destructive": False},
        {"value": "deactivate", "label": "Deactivate", "description": "Deactivate selected items", "destructive": False},
        {"value": "suspend", "label": "Suspend", "description": "Suspend selected items", "destructive": True},
        {"value": "resume", "label": "Resume", "description": "Resume selected items", "destructive": False}
    ]
