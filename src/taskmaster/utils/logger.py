"""Logging and operational audit trail for Taskmaster."""

import logging
import os
from pathlib import Path
from typing import Optional


class TaskmasterLogger:
    """Manages file and console logging for Taskmaster."""

    DEFAULT_LOG_FILE = "logs/taskmaster.log"
    DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    _initialized: bool = False
    _log_file_path: Optional[str] = None
    _file_handler: Optional[logging.Handler] = None
    _console_handler: Optional[logging.Handler] = None

    @classmethod
    def setup(
        cls,
        log_file: Optional[str] = None,
        level: str = "INFO",
        console: bool = False,
    ) -> logging.Logger:
        """Configure root Taskmaster logger."""
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        root_logger = logging.getLogger("taskmaster")
        root_logger.setLevel(numeric_level)

        # Clear existing handlers if already initialized
        if cls._initialized:
            if cls._file_handler and cls._file_handler in root_logger.handlers:
                root_logger.removeHandler(cls._file_handler)
                cls._file_handler.close()
            if cls._console_handler and cls._console_handler in root_logger.handlers:
                root_logger.removeHandler(cls._console_handler)

        target_file = log_file or cls.DEFAULT_LOG_FILE
        log_path = Path(target_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(cls.DEFAULT_FORMAT, datefmt=cls.DATE_FORMAT)

        # File handler (append mode)
        cls._file_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        cls._file_handler.setFormatter(formatter)
        cls._file_handler.setLevel(numeric_level)
        root_logger.addHandler(cls._file_handler)

        # Console handler (if requested, e.g. daemon foreground debug)
        if console:
            cls._console_handler = logging.StreamHandler()
            cls._console_handler.setFormatter(formatter)
            cls._console_handler.setLevel(numeric_level)
            root_logger.addHandler(cls._console_handler)

        cls._log_file_path = str(log_path)
        cls._initialized = True
        return root_logger

    @classmethod
    def get_logger(cls, name: Optional[str] = None) -> logging.Logger:
        """Get a namespaced logger (e.g. taskmaster.worker)."""
        if not cls._initialized:
            cls.setup()
        base_name = "taskmaster"
        return logging.getLogger(f"{base_name}.{name}" if name else base_name)

    @classmethod
    def set_level(cls, level: str) -> None:
        """Dynamically update log level."""
        numeric_level = getattr(logging, level.upper(), logging.INFO)
        root_logger = logging.getLogger("taskmaster")
        root_logger.setLevel(numeric_level)
        if cls._file_handler:
            cls._file_handler.setLevel(numeric_level)
        if cls._console_handler:
            cls._console_handler.setLevel(numeric_level)


# Global default logger instance
logger = TaskmasterLogger.get_logger()
