"""Status formatting helpers for Codevertex provisioning sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provisioning import ProvisioningSession, ProvisioningStepLog, ProvisioningStatus


async def build_session_status(db: AsyncSession, session: ProvisioningSession) -> Dict[str, Any]:
    result = await db.execute(
        select(ProvisioningStepLog).where(ProvisioningStepLog.session_id == session.id).order_by(ProvisioningStepLog.step_order)
    )
    steps = result.scalars().all()

    completed_steps = sum(1 for step in steps if step.status == ProvisioningStatus.COMPLETED)
    total_steps = len(steps)

    estimated_remaining = None
    if session.status == ProvisioningStatus.IN_PROGRESS and session.started_at and completed_steps > 0:
        elapsed_minutes = (datetime.utcnow() - session.started_at).total_seconds() / 60
        avg_time_per_step = elapsed_minutes / completed_steps
        remaining_steps = total_steps - completed_steps
        estimated_remaining = int(avg_time_per_step * remaining_steps)

    current_operation = None
    for step in steps:
        if step.status == ProvisioningStatus.IN_PROGRESS and step.output_data:
            current_operation = step.output_data.get("current_operation")
            break

    return {
        "session_id": session.session_id,
        "status": session.status.value,
        "current_step": session.current_step.value,
        "progress_percentage": session.progress_percentage,
        "steps_completed": completed_steps,
        "steps_total": total_steps,
        "estimated_time_remaining_minutes": estimated_remaining,
        "current_operation": current_operation,
        "error_message": session.error_message,
        "can_cancel": session.status in [ProvisioningStatus.PENDING, ProvisioningStatus.IN_PROGRESS],
        "can_retry": session.status == ProvisioningStatus.FAILED,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "steps": [
            {
                "step": step.step.value,
                "status": step.status.value,
                "progress": step.progress_percentage,
                "started_at": step.started_at,
                "completed_at": step.completed_at,
                "duration_seconds": step.duration_seconds,
                "error": step.error_details,
            }
            for step in steps
        ],
    }


