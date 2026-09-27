"""Unit tests for Taskmaster CLI command processor."""

import asyncio
import os
import sys
import tempfile
import pytest

from taskmaster.cli.commands import CommandHandler
from taskmaster.config.models import ProgramConfig, TaskmasterConfig
from taskmaster.core.handler import ServiceHandler
from taskmaster.core.states import ProcessState


@pytest.fixture
def sample_handler():
    cfg = TaskmasterConfig(
        programs={
            "srv_a": ProgramConfig(
                name="srv_a",
                cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
                numprocs=2,
                autostart=False,
                starttime=1,
            ),
            "srv_b": ProgramConfig(
                name="srv_b",
                cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
                numprocs=1,
                autostart=False,
                starttime=1,
            ),
        }
    )
    return ServiceHandler(cfg)


@pytest.mark.asyncio
async def test_cli_help(sample_handler):
    cmd = CommandHandler(sample_handler)

    should_exit, out = await cmd.execute("help")
    assert should_exit is False
    assert "status" in out
    assert "start" in out
    assert "stop" in out
    assert "quit" in out

    _, out_start = await cmd.execute("help start")
    assert "Start specified" in out_start


@pytest.mark.asyncio
async def test_cli_status(sample_handler):
    cmd = CommandHandler(sample_handler)

    _, out = await cmd.execute("status")
    assert "srv_a:0" in out
    assert "srv_a:1" in out
    assert "srv_b" in out
    assert "STOPPED" in out


@pytest.mark.asyncio
async def test_cli_start_stop_restart(sample_handler):
    cmd = CommandHandler(sample_handler)

    # Start srv_b
    should_exit, out = await cmd.execute("start srv_b")
    assert should_exit is False
    assert "srv_b: started" in out

    await asyncio.sleep(1.2)
    _, out_status = await cmd.execute("status srv_b")
    assert "RUNNING" in out_status

    # Restart srv_b
    _, out_restart = await cmd.execute("restart srv_b")
    assert "srv_b: restarted" in out_restart

    # Stop all
    _, out_stop = await cmd.execute("stop all")
    assert "srv_a: stopped" in out_stop
    assert "srv_b: stopped" in out_stop

    _, out_status2 = await cmd.execute("status")
    assert "STOPPED" in out_status2


@pytest.mark.asyncio
async def test_cli_tail():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "tail_test.log")
        with open(log_path, "w", encoding="utf-8") as f:
            for i in range(30):
                f.write(f"log line {i}\n")

        cfg = TaskmasterConfig(
            programs={
                "logger_app": ProgramConfig(
                    name="logger_app",
                    cmd="echo hi",
                    stdout=log_path,
                )
            }
        )
        handler = ServiceHandler(cfg)
        cmd = CommandHandler(handler)

        _, out = await cmd.execute("tail -n 5 logger_app stdout")
        assert "log line 25" in out
        assert "log line 29" in out
        assert "log line 20" not in out


@pytest.mark.asyncio
async def test_cli_quit(sample_handler):
    cmd = CommandHandler(sample_handler)
    should_exit, out = await cmd.execute("quit")
    assert should_exit is True
    assert "Goodbye" in out


def test_cli_completions(sample_handler):
    cmd = CommandHandler(sample_handler)
    comps = cmd.get_completions()
    assert "status" in comps
    assert "start" in comps
    assert "srv_a" in comps
    assert "srv_b" in comps
    assert "all" in comps
