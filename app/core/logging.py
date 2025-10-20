"""Logging configuration."""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from app.core.config import settings


def setup_logging() -> None:
    """Setup application logging configuration."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format=_get_log_format(),
        handlers=_get_log_handlers(),
    )
    
    # Configure specific loggers
    _configure_loggers()


def _get_log_format() -> str:
    """Get log format based on configuration."""
    if settings.log_format == "json":
        return "%(asctime)s %(name)s %(levelname)s %(message)s"
    else:
        return "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _get_log_handlers() -> list:
    """Get log handlers based on configuration."""
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if settings.log_file:
        # Create logs directory if it doesn't exist
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(settings.log_file)
        handlers.append(file_handler)
    
    return handlers


def _configure_loggers() -> None:
    """Configure specific loggers."""
    # Reduce noise from external libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    
    # Set application logger
    app_logger = logging.getLogger("app")
    app_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Get logger instance."""
    return logging.getLogger(f"app.{name}")


class LoggerMixin:
    """Mixin class to add logging capabilities to any class."""
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        return get_logger(self.__class__.__name__)
