"""Unit and integration tests for SubProcess lifecycle and FSM."""

import asyncio
import os
import signal
import sys
import tempfile
import pytest

from taskmaster.config.models import AutoRestart, ProgramConfig
from taskmaster.core.process import SubProcess
from taskmaster.core.states import ProcessState


@pytest.mark.asyncio
async def test_process_normal_lifecycle():
    """Verify that a long-running process successfully transitions to RUNNING and stops."""
    cfg = ProgramConfig(
        name="test_sleep",
        cmd=f"{sys.executable} -c 'import time; time.sleep(5)'",
        starttime=1,
        stoptime=2,
        stopsignal=signal.SIGTERM,
    )
    proc = SubProcess("test_sleep", 0, cfg)
    assert proc.state == ProcessState.STOPPED

    started = await proc.start()
    assert started is True
    assert proc.state == ProcessState.STARTING
    assert proc.pid is not None

    # Wait for starttime (1s) plus margin
    await asyncio.sleep(1.2)
    assert proc.state == ProcessState.RUNNING
    assert proc.uptime is not None
    assert proc.uptime >= 1.0

    # Stop process
    stopped = await proc.stop()
    assert stopped is True
    assert proc.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_process_early_exit_backoff_and_fatal():
    """Verify that an early exit (< starttime) enters BACKOFF and eventually FATAL."""
    cfg = ProgramConfig(
        name="quick_exit",
        cmd=f"{sys.executable} -c 'import sys; sys.exit(1)'",
        starttime=2,  # requires 2s to be healthy
        startretries=1,  # allow only 1 retry
        autorestart=AutoRestart.NEVER,
    )
    proc = SubProcess("quick_exit", 0, cfg)

    await proc.start()
    # Process exits almost immediately
    await asyncio.sleep(0.3)
    # Should enter BACKOFF after 1st failure
    assert proc.state in (ProcessState.BACKOFF, ProcessState.FATAL)

    # Allow backoff and retry to complete
    await asyncio.sleep(2.0)
    # Since retries were exhausted, it must be FATAL
    assert proc.state == ProcessState.FATAL
    assert proc.retries >= 1


@pytest.mark.asyncio
async def test_process_output_redirection():
    """Verify stdout and stderr redirection in append mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        stdout_path = os.path.join(tmpdir, "test.stdout")
        stderr_path = os.path.join(tmpdir, "test.stderr")

        cfg = ProgramConfig(
            name="echo_test",
            cmd=f"{sys.executable} -c 'import sys; print(\"hello stdout\"); sys.stderr.write(\"hello stderr\\n\")'",
            starttime=0,
            stdout=stdout_path,
            stderr=stderr_path,
        )
        proc = SubProcess("echo_test", 0, cfg)
        await proc.start()
        await asyncio.sleep(0.5)

        assert os.path.exists(stdout_path)
        assert os.path.exists(stderr_path)

        with open(stdout_path, "r", encoding="utf-8") as f:
            assert "hello stdout" in f.read()

        with open(stderr_path, "r", encoding="utf-8") as f:
            assert "hello stderr" in f.read()


@pytest.mark.asyncio
async def test_process_env_and_workingdir():
    """Verify environment variables and working directory are passed to child."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = os.path.join(tmpdir, "out.txt")
        cfg = ProgramConfig(
            name="env_cwd_test",
            cmd=f"{sys.executable} -c 'import os; open(\"out.txt\", \"w\").write(os.environ.get(\"CUSTOM_VAR\", \"\"))'",
            workingdir=tmpdir,
            env={"CUSTOM_VAR": "TASKMASTER_VAL_42"},
            starttime=0,
        )
        proc = SubProcess("env_cwd_test", 0, cfg)
        await proc.start()
        await asyncio.sleep(0.5)

        assert os.path.exists(output_file)
        with open(output_file, "r", encoding="utf-8") as f:
            assert f.read() == "TASKMASTER_VAL_42"
