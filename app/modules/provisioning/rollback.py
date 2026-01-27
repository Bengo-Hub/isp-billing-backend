"""Rollback helpers for Codevertex MikroTik provisioning."""

from __future__ import annotations

from typing import List

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provisioning import ProvisioningCommand


async def execute_rollback(db: AsyncSession, router_service, session, logger) -> None:
    """Execute rollback commands in reverse order for a session."""
    try:
        result = await db.execute(
            select(ProvisioningCommand)
            .where(
                and_(
                    ProvisioningCommand.session_id == session.id,
                    ProvisioningCommand.success == True,  # noqa: E712
                    ProvisioningCommand.rollback_command.isnot(None),
                )
            )
            .order_by(desc(ProvisioningCommand.execution_order))
        )
        commands: List[ProvisioningCommand] = result.scalars().all()
        router = await router_service.get_by_id(session.router_id)
        api = router_service.api_cls(router) if hasattr(router_service, "api_cls") else None
        api = api or await router_service.get_api(router)
        await api.connect()
        for command in commands:
            try:
                await api.execute_command(command.rollback_command)
                command.rollback_executed = True
            except Exception as e:  # noqa: BLE001
                logger.error(f"Rollback command failed: {e}")
        await api.disconnect()
        session.rollback_completed = True
        await db.commit()
        logger.info(f"Rollback completed for session {session.session_id}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"Rollback failed for session {session.session_id}: {e}")


