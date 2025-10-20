"""Notification and support ticket models."""

from enum import Enum as PyEnum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Integer,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class NotificationType(str, PyEnum):
    """Notification type enumeration."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    BILLING = "billing"
    SUBSCRIPTION = "subscription"
    WELCOME = "welcome"


class NotificationPriority(str, PyEnum):
    """Notification priority enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(str, PyEnum):
    """Notification status enumeration."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"
    READ = "read"


class TicketStatus(str, PyEnum):
    """Support ticket status enumeration."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TicketPriority(str, PyEnum):
    """Support ticket priority enumeration."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Notification(Base):
    """Notification model."""

    __tablename__ = "notifications"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Notification details
    notification_type = Column(Enum(NotificationType), nullable=False)
    status = Column(Enum(NotificationStatus), default=NotificationStatus.PENDING, nullable=False)
    
    # Content
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    template_name = Column(String(100), nullable=True)
    template_data = Column(Text, nullable=True)  # JSON data
    
    # Delivery information
    recipient = Column(String(200), nullable=False)  # email, phone, etc.
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    
    # Error handling
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    
    # Additional information
    external_id = Column(String(100), nullable=True)  # External service ID
    extra_data = Column(Text, nullable=True)  # JSON metadata

    # Relationships
    user = relationship("User", back_populates="notifications")

    def __repr__(self) -> str:
        """String representation."""
        return f"<Notification(id={self.id}, user_id={self.user_id}, type='{self.notification_type}')>"


class SupportTicket(Base):
    """Support ticket model."""

    __tablename__ = "support_tickets"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Ticket details
    ticket_number = Column(String(50), unique=True, index=True, nullable=False)
    subject = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM, nullable=False)
    
    # Category and tags
    category = Column(String(50), nullable=True)
    tags = Column(String(200), nullable=True)  # Comma-separated tags
    
    # Resolution
    resolution = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    
    # Additional information
    attachments = Column(Text, nullable=True)  # JSON array of file paths
    extra_data = Column(Text, nullable=True)  # JSON metadata

    # Relationships
    user = relationship("User", back_populates="tickets", foreign_keys=[user_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    messages = relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """String representation."""
        return f"<SupportTicket(id={self.id}, number='{self.ticket_number}', status='{self.status}')>"


class TicketMessage(Base):
    """Support ticket message model."""

    __tablename__ = "ticket_messages"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    ticket_id = Column(Integer, ForeignKey("support_tickets.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Message details
    message = Column(Text, nullable=False)
    is_internal = Column(Boolean, default=False, nullable=False)  # Internal note
    
    # Attachments
    attachments = Column(Text, nullable=True)  # JSON array of file paths
    
    # Additional information
    ip_address = Column(String(45), nullable=True)

    # Relationships
    ticket = relationship("SupportTicket", back_populates="messages")
    user = relationship("User", backref="ticket_messages")

    def __repr__(self) -> str:
        """String representation."""
        return f"<TicketMessage(id={self.id}, ticket_id={self.ticket_id}, user_id={self.user_id})>"


class NotificationTemplate(Base):
    """Enhanced notification template model with advanced features."""

    __tablename__ = "notification_templates"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Template details
    name = Column(String(100), unique=True, nullable=False)
    notification_type = Column(Enum(NotificationType), nullable=False)
    subject_template = Column(String(200), nullable=True)
    body_template = Column(Text, nullable=False)
    
    # Enhanced template features
    html_template = Column(Text, nullable=True)  # HTML version for emails
    user_type_specific = Column(Boolean, default=False, nullable=False)
    hotspot_template = Column(Text, nullable=True)  # Specific template for hotspot users
    pppoe_template = Column(Text, nullable=True)  # Specific template for PPPoE users
    
    # Template configuration
    is_active = Column(Boolean, default=True, nullable=False)
    variables = Column(Text, nullable=True)  # JSON array of required variables
    description = Column(Text, nullable=True)
    
    # Rich text and formatting
    supports_html = Column(Boolean, default=False, nullable=False)
    supports_markdown = Column(Boolean, default=False, nullable=False)
    css_styles = Column(Text, nullable=True)  # CSS for HTML templates
    
    # Template metadata
    category = Column(String(50), nullable=True)
    tags = Column(String(500), nullable=True)  # Comma-separated tags
    version = Column(String(20), default="1.0", nullable=False)
    
    # Usage statistics
    usage_count = Column(Integer, default=0, nullable=False)
    success_rate = Column(Numeric(5, 2), default=0, nullable=False)
    
    # Template validation
    last_tested = Column(DateTime, nullable=True)
    test_results = Column(Text, nullable=True)  # JSON test results
    
    # Author information
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], backref="created_notification_templates")
    updater = relationship("User", foreign_keys=[last_updated_by], backref="updated_notification_templates")

    def __repr__(self) -> str:
        """String representation."""
        return f"<NotificationTemplate(id={self.id}, name='{self.name}', type='{self.notification_type}')>"

    def get_variables(self) -> List[str]:
        """Get template variables as list."""
        if not self.variables:
            return []
        import json
        try:
            return json.loads(self.variables)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_template_for_user_type(self, user_type: str) -> str:
        """Get appropriate template based on user type."""
        if not self.user_type_specific:
            return self.body_template
        
        if user_type.lower() == "hotspot" and self.hotspot_template:
            return self.hotspot_template
        elif user_type.lower() == "pppoe" and self.pppoe_template:
            return self.pppoe_template
        
        return self.body_template

    def get_tags_list(self) -> List[str]:
        """Get tags as list."""
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
