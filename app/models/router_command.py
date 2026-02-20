"""Router command queue model for polling agent architecture."""

from datetime import datetime, timedelta
from enum import Enum as PyEnum
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class CommandStatus(str, PyEnum):
    """Command lifecycle status."""

    PENDING = "pending"
    SENT = "sent"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"


class RouterCommand(Base):
    """Command queue for router polling agent.

    Commands are queued by the backend and picked up by routers
    during their next poll cycle. Results are reported back via
    the agent report endpoint.
    """

    __tablename__ = "router_commands"

    # Primary key (UUID for distributed safety)
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # Target router
    router_id = Column(Integer, ForeignKey("routers.id"), nullable=False, index=True)

    # Command definition
    action = Column(String(50), nullable=False)  # create_user, disable_user, enable_user, disconnect, set_queue, run_script
    params = Column(JSON, nullable=False, default=dict)  # Action-specific parameters
    priority = Column(Integer, default=5)  # 1=critical, 5=normal, 9=low

    # Lifecycle
    status = Column(String(20), default=CommandStatus.PENDING, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)  # When included in poll response
    completed_at = Column(DateTime, nullable=True)  # When result reported
    expires_at = Column(
        DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=1),
        nullable=True,
    )

    # Result
    result_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)

    # Context (what triggered this command)
    source = Column(String(50), nullable=True)  # subscription_sync, manual, billing_cycle
    source_id = Column(String(100), nullable=True)  # e.g., subscription_id

    # Relationships
    router = relationship("Router", back_populates="commands")

    def __repr__(self) -> str:
        return (
            f"<RouterCommand(id={self.id}, router_id={self.router_id}, "
            f"action='{self.action}', status='{self.status}')>"
        )
