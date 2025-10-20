"""Provisioning-related Celery tasks."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

from celery import current_task
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.provisioning import (
    ProvisioningSession,
    ProvisioningStatus,
    ProvisioningStep,
    ProvisioningPriority
)
from app.services.provisioning_service import ProvisioningService

logger = get_logger(__name__)


@celery_app.task(bind=True)
def execute_provisioning_workflow(self, session_id: str):
    """Execute a complete provisioning workflow in the background."""
    logger.info(f"Starting provisioning workflow for session {session_id}")
    
    try:
        async def _execute_workflow():
            async with AsyncSessionLocal() as db:
                service = ProvisioningService(db)
                
                # Get the session
                session = await service.get_session_by_id(session_id)
                if not session:
                    raise Exception(f"Provisioning session {session_id} not found")
                
                if session.status != ProvisioningStatus.PENDING:
                    raise Exception(f"Session {session_id} is not in pending status")
                
                # Start the provisioning process
                success = await service.start_provisioning(session_id)
                
                if not success:
                    raise Exception(f"Failed to start provisioning for session {session_id}")
                
                return {"status": "started", "session_id": session_id}
        
        # Run the async function
        result = asyncio.run(_execute_workflow())
        
        logger.info(f"Provisioning workflow started successfully for session {session_id}")
        return result
        
    except Exception as exc:
        logger.error(f"Provisioning workflow failed for session {session_id}: {exc}")
        
        # Update session status to failed
        async def _mark_failed():
            async with AsyncSessionLocal() as db:
                service = ProvisioningService(db)
                await service.update_session(session_id, {
                    "status": ProvisioningStatus.FAILED,
                    "error_message": str(exc),
                    "completed_at": datetime.utcnow()
                })
        
        asyncio.run(_mark_failed())
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def monitor_provisioning_sessions(self):
    """Monitor active provisioning sessions and handle timeouts."""
    logger.info("Monitoring provisioning sessions")
    
    try:
        async def _monitor_sessions():
            async with AsyncSessionLocal() as db:
                service = ProvisioningService(db)
                
                # Get active sessions that have timed out
                timeout_threshold = datetime.utcnow()
                
                result = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        and_(
                            ProvisioningSession.status == ProvisioningStatus.IN_PROGRESS,
                            ProvisioningSession.timeout_at < timeout_threshold
                        )
                    )
                )
                timed_out_sessions = result.scalars().all()
                
                timeout_count = 0
                for session in timed_out_sessions:
                    try:
                        # Mark session as timed out
                        session.status = ProvisioningStatus.TIMEOUT
                        session.error_message = "Provisioning session timed out"
                        session.completed_at = datetime.utcnow()
                        
                        # Execute rollback if needed
                        if session.get_config_item('rollback_on_timeout', True):
                            session.rollback_required = True
                            # Schedule rollback task
                            rollback_provisioning_session.delay(session.session_id)
                        
                        timeout_count += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to handle timeout for session {session.session_id}: {e}")
                
                await db.commit()
                
                # Get sessions that need priority processing
                result = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        and_(
                            ProvisioningSession.status == ProvisioningStatus.PENDING,
                            ProvisioningSession.priority.in_([
                                ProvisioningPriority.HIGH,
                                ProvisioningPriority.URGENT
                            ]),
                            ProvisioningSession.scheduled_at <= datetime.utcnow()
                        )
                    )
                    .order_by(ProvisioningSession.priority.desc(), ProvisioningSession.created_at.asc())
                    .limit(5)  # Process up to 5 high-priority sessions
                )
                priority_sessions = result.scalars().all()
                
                priority_count = 0
                for session in priority_sessions:
                    try:
                        # Start high-priority provisioning
                        execute_provisioning_workflow.delay(session.session_id)
                        priority_count += 1
                    except Exception as e:
                        logger.error(f"Failed to start priority session {session.session_id}: {e}")
                
                return {
                    "timed_out_sessions": timeout_count,
                    "priority_sessions_started": priority_count
                }
        
        result = asyncio.run(_monitor_sessions())
        
        logger.info(f"Session monitoring completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Session monitoring failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)  # Retry in 5 minutes


@celery_app.task(bind=True)
def rollback_provisioning_session(self, session_id: str):
    """Execute rollback for a failed or cancelled provisioning session."""
    logger.info(f"Starting rollback for provisioning session {session_id}")
    
    try:
        async def _execute_rollback():
            async with AsyncSessionLocal() as db:
                service = ProvisioningService(db)
                
                session = await service.get_session_by_id(session_id)
                if not session:
                    raise Exception(f"Provisioning session {session_id} not found")
                
                if not session.rollback_required or session.rollback_completed:
                    logger.info(f"Rollback not required or already completed for session {session_id}")
                    return {"status": "skipped", "reason": "not_required"}
                
                # Execute the rollback
                await service._execute_rollback(session)
                
                return {"status": "completed", "session_id": session_id}
        
        result = asyncio.run(_execute_rollback())
        
        logger.info(f"Rollback completed for session {session_id}")
        return result
        
    except Exception as exc:
        logger.error(f"Rollback failed for session {session_id}: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task(bind=True)
def cleanup_old_provisioning_sessions(self):
    """Clean up old completed provisioning sessions and logs."""
    logger.info("Cleaning up old provisioning sessions")
    
    try:
        async def _cleanup_sessions():
            async with AsyncSessionLocal() as db:
                # Clean up sessions older than 30 days
                cleanup_date = datetime.utcnow() - timedelta(days=30)
                
                # Get old completed sessions
                result = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        and_(
                            ProvisioningSession.status.in_([
                                ProvisioningStatus.COMPLETED,
                                ProvisioningStatus.FAILED,
                                ProvisioningStatus.CANCELLED,
                                ProvisioningStatus.TIMEOUT
                            ]),
                            ProvisioningSession.completed_at < cleanup_date
                        )
                    )
                )
                old_sessions = result.scalars().all()
                
                cleanup_count = 0
                for session in old_sessions:
                    try:
                        # Delete the session (cascade will handle related records)
                        await db.delete(session)
                        cleanup_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete session {session.session_id}: {e}")
                
                await db.commit()
                
                return {"cleaned_up_sessions": cleanup_count}
        
        result = asyncio.run(_cleanup_sessions())
        
        logger.info(f"Cleanup completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Cleanup failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)  # Retry in 1 hour


@celery_app.task(bind=True)
def generate_provisioning_report(self, period_days: int = 7):
    """Generate provisioning statistics report."""
    logger.info(f"Generating provisioning report for {period_days} days")
    
    try:
        async def _generate_report():
            async with AsyncSessionLocal() as db:
                service = ProvisioningService(db)
                
                # Get provisioning statistics
                stats = await service.get_provisioning_stats(days=period_days)
                
                # Add additional metrics
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=period_days)
                
                # Get session distribution by service type
                result = await db.execute(
                    select(
                        ProvisioningSession.service_type,
                        func.count(ProvisioningSession.id).label('count')
                    )
                    .where(ProvisioningSession.created_at >= start_date)
                    .group_by(ProvisioningSession.service_type)
                )
                service_type_stats = {row.service_type.value if row.service_type else 'unknown': row.count for row in result}
                
                # Get average duration by step
                from app.models.provisioning import ProvisioningStepLog
                result = await db.execute(
                    select(
                        ProvisioningStepLog.step,
                        func.avg(ProvisioningStepLog.duration_seconds).label('avg_duration')
                    )
                    .where(
                        and_(
                            ProvisioningStepLog.created_at >= start_date,
                            ProvisioningStepLog.duration_seconds.isnot(None)
                        )
                    )
                    .group_by(ProvisioningStepLog.step)
                )
                step_duration_stats = {
                    row.step.value: round(row.avg_duration, 2) if row.avg_duration else 0
                    for row in result
                }
                
                report = {
                    **stats,
                    "service_type_distribution": service_type_stats,
                    "average_step_duration_seconds": step_duration_stats,
                    "report_generated_at": datetime.utcnow().isoformat()
                }
                
                return report
        
        result = asyncio.run(_generate_report())
        
        logger.info(f"Provisioning report generated: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Report generation failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def process_scheduled_provisioning(self):
    """Process scheduled provisioning sessions."""
    logger.info("Processing scheduled provisioning sessions")
    
    try:
        async def _process_scheduled():
            async with AsyncSessionLocal() as db:
                # Get scheduled sessions that are ready to start
                current_time = datetime.utcnow()
                
                result = await db.execute(
                    select(ProvisioningSession)
                    .where(
                        and_(
                            ProvisioningSession.status == ProvisioningStatus.PENDING,
                            ProvisioningSession.scheduled_at <= current_time,
                            ProvisioningSession.scheduled_at.isnot(None)
                        )
                    )
                    .order_by(ProvisioningSession.priority.desc(), ProvisioningSession.scheduled_at.asc())
                    .limit(10)  # Process up to 10 scheduled sessions at once
                )
                scheduled_sessions = result.scalars().all()
                
                started_count = 0
                for session in scheduled_sessions:
                    try:
                        # Start the provisioning workflow
                        execute_provisioning_workflow.delay(session.session_id)
                        started_count += 1
                        
                        logger.info(f"Started scheduled provisioning session {session.session_id}")
                        
                    except Exception as e:
                        logger.error(f"Failed to start scheduled session {session.session_id}: {e}")
                        
                        # Mark session as failed
                        session.status = ProvisioningStatus.FAILED
                        session.error_message = f"Failed to start scheduled session: {str(e)}"
                        session.completed_at = datetime.utcnow()
                
                await db.commit()
                
                return {"started_sessions": started_count}
        
        result = asyncio.run(_process_scheduled())
        
        logger.info(f"Scheduled provisioning processing completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Scheduled provisioning processing failed: {exc}")
        raise self.retry(exc=exc, countdown=300, max_retries=3)


@celery_app.task(bind=True)
def update_provisioning_templates_stats(self):
    """Update usage statistics for provisioning templates."""
    logger.info("Updating provisioning template statistics")
    
    try:
        async def _update_template_stats():
            async with AsyncSessionLocal() as db:
                from app.models.provisioning import ProvisioningTemplate
                
                # Get all active templates
                result = await db.execute(
                    select(ProvisioningTemplate)
                    .where(ProvisioningTemplate.is_active == True)
                )
                templates = result.scalars().all()
                
                updated_count = 0
                for template in templates:
                    try:
                        # Count total usage
                        usage_result = await db.execute(
                            select(func.count(ProvisioningSession.id))
                            .where(
                                and_(
                                    ProvisioningSession.service_type == template.service_type,
                                    # Could add more specific template matching logic here
                                )
                            )
                        )
                        total_usage = usage_result.scalar() or 0
                        
                        # Count successful usage
                        success_result = await db.execute(
                            select(func.count(ProvisioningSession.id))
                            .where(
                                and_(
                                    ProvisioningSession.service_type == template.service_type,
                                    ProvisioningSession.status == ProvisioningStatus.COMPLETED
                                )
                            )
                        )
                        successful_usage = success_result.scalar() or 0
                        
                        # Calculate success rate
                        success_rate = (successful_usage / total_usage * 100) if total_usage > 0 else 0
                        
                        # Update template stats
                        template.usage_count = total_usage
                        template.success_rate = round(success_rate, 2)
                        
                        updated_count += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to update stats for template {template.id}: {e}")
                
                await db.commit()
                
                return {"updated_templates": updated_count}
        
        result = asyncio.run(_update_template_stats())
        
        logger.info(f"Template statistics update completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"Template statistics update failed: {exc}")
        raise self.retry(exc=exc, countdown=3600, max_retries=3)  # Retry in 1 hour


# Periodic task setup (these would be configured in celery beat schedule)
@celery_app.task
def setup_periodic_provisioning_tasks():
    """Setup periodic tasks for provisioning system."""
    
    # Monitor sessions every 5 minutes
    monitor_provisioning_sessions.apply_async(countdown=300)
    
    # Process scheduled sessions every minute
    process_scheduled_provisioning.apply_async(countdown=60)
    
    # Cleanup old sessions daily
    cleanup_old_provisioning_sessions.apply_async(countdown=86400)
    
    # Update template stats every 6 hours
    update_provisioning_templates_stats.apply_async(countdown=21600)
    
    # Generate daily report
    generate_provisioning_report.apply_async(countdown=86400, kwargs={"period_days": 1})
    
    return {"status": "periodic_tasks_scheduled"}
