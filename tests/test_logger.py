"""Unit tests for Taskmaster logger and audit subsystem."""

import os
from pathlib import Path
import tempfile
import pytest

from taskmaster.utils.logger import TaskmasterLogger


def test_logger_setup_and_write():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "test.log")
        logger = TaskmasterLogger.setup(log_file=log_file, level="DEBUG", console=False)
        
        logger.info("Test informational log")
        logger.warning("Test warning log")
        logger.error("Test error log")
        
        # Flush handlers
        for handler in logger.handlers:
            handler.flush()

        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[INFO]" in content
        assert "Test informational log" in content
        assert "[WARNING]" in content
        assert "Test warning log" in content
        assert "[ERROR]" in content
        assert "Test error log" in content


def test_logger_level_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "filtered.log")
        logger = TaskmasterLogger.setup(log_file=log_file, level="WARNING", console=False)
        
        logger.debug("This debug log should be ignored")
        logger.info("This info log should be ignored")
        logger.warning("This warning log should appear")

        for handler in logger.handlers:
            handler.flush()

        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "This debug log should be ignored" not in content
        assert "This info log should be ignored" not in content
        assert "This warning log should appear" in content


def test_namespaced_logger():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "namespaced.log")
        TaskmasterLogger.setup(log_file=log_file, level="DEBUG", console=False)
        
        worker_logger = TaskmasterLogger.get_logger("worker:1")
        worker_logger.info("Worker process event")

        for handler in worker_logger.handlers:
            handler.flush()
        # Also flush root handlers
        for handler in TaskmasterLogger.get_logger().handlers:
            handler.flush()

        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[taskmaster.worker:1]" in content
        assert "Worker process event" in content
