"""Unit and integration tests for supervision, autorestart, and shutdown."""

import asyncio
import signal
import sys
import pytest

from taskmaster.config.models import AutoRestart, ProgramConfig, TaskmasterConfig
from taskmaster.core.handler import ServiceHandler
from taskmaster.core.process import SubProcess
from taskmaster.core.states import ProcessState


@pytest.mark.asyncio
async def test_autorestart_always():
    """Verify that autorestart: always restarts an exited process even on code 0."""
    cfg = ProgramConfig(
        name="always_restart",
        cmd=f"{sys.executable} -c 'import sys, time; time.sleep(2); sys.exit(0)'",
        starttime=1,
        autorestart=AutoRestart.ALWAYS,
    )
    proc = SubProcess("always_restart", 0, cfg)
    await proc.start()
    # At 1.2s: alive for > 1s, but total sleep is 2s -> must be RUNNING!
    await asyncio.sleep(1.2)
    assert proc.state == ProcessState.RUNNING
    initial_pid = proc.pid

    # Wait for process to exit (after 2s total) and restart
    await asyncio.sleep(1.5)
    # The process should have restarted with a new PID
    assert proc.state in (ProcessState.STARTING, ProcessState.RUNNING)
    assert proc.pid != initial_pid

    await proc.stop()


@pytest.mark.asyncio
async def test_autorestart_unexpected():
    """Verify that autorestart: unexpected only restarts if exitcode is unexpected."""
    # 1. Expected exit code: does NOT restart
    cfg_expected = ProgramConfig(
        name="expected_exit",
        cmd=f"{sys.executable} -c 'import sys, time; time.sleep(2); sys.exit(0)'",
        starttime=1,
        autorestart=AutoRestart.UNEXPECTED,
        exitcodes=[0],
    )
    proc1 = SubProcess("expected_exit", 0, cfg_expected)
    await proc1.start()
    await asyncio.sleep(1.2)
    assert proc1.state == ProcessState.RUNNING

    # Wait for completion (exits at 2s)
    await asyncio.sleep(1.5)
    assert proc1.state == ProcessState.EXITED
    assert proc1.returncode == 0

    # 2. Unexpected exit code: DOES restart
    cfg_unexpected = ProgramConfig(
        name="unexpected_exit",
        cmd=f"{sys.executable} -c 'import sys, time; time.sleep(2); sys.exit(42)'",
        starttime=1,
        autorestart=AutoRestart.UNEXPECTED,
        exitcodes=[0],  # 42 is unexpected!
    )
    proc2 = SubProcess("unexpected_exit", 0, cfg_unexpected)
    await proc2.start()
    await asyncio.sleep(1.2)
    assert proc2.state == ProcessState.RUNNING
    old_pid = proc2.pid

    # Wait for exit and autorestart
    await asyncio.sleep(1.5)
    assert proc2.state in (ProcessState.STARTING, ProcessState.RUNNING)
    assert proc2.pid != old_pid
    await proc2.stop()



@pytest.mark.asyncio
async def test_sigkill_fallback():
    """Verify that a process ignoring SIGTERM is forcefully terminated via SIGKILL after stoptime."""
    # Python script that ignores SIGTERM
    script = (
        "import signal, time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "time.sleep(30)"
    )
    cfg = ProgramConfig(
        name="uncooperative",
        cmd=f"{sys.executable} -c '{script}'",
        starttime=1,
        stopsignal=signal.SIGTERM,
        stoptime=1,  # Short 1s timeout before SIGKILL
    )
    proc = SubProcess("uncooperative", 0, cfg)
    await proc.start()
    await asyncio.sleep(1.2)
    assert proc.state == ProcessState.RUNNING

    # Stop should trigger SIGTERM, wait 1s, then send SIGKILL
    t0 = asyncio.get_event_loop().time()
    stopped = await proc.stop()
    t1 = asyncio.get_event_loop().time()

    assert stopped is True
    assert proc.state == ProcessState.STOPPED
    # Duration should be around stoptime (1s)
    assert 0.9 <= (t1 - t0) <= 3.0


@pytest.mark.asyncio
async def test_service_handler_operations():
    """Verify ServiceHandler multi-service control and shutdown."""
    cfg = TaskmasterConfig(
        programs={
            "app1": ProgramConfig(
                name="app1",
                cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
                numprocs=2,
                autostart=True,
                starttime=1,
            ),
            "app2": ProgramConfig(
                name="app2",
                cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
                numprocs=1,
                autostart=False,
                starttime=1,
            ),
        }
    )
    handler = ServiceHandler(cfg)
    assert len(handler.services) == 2

    # Autostart should start app1 only
    await handler.autostart_all()
    await asyncio.sleep(1.2)

    status = handler.get_status()
    assert len(status) == 3  # 2 for app1, 1 for app2
    app1_status = [s for s in status if s["service"] == "app1"]
    app2_status = [s for s in status if s["service"] == "app2"]

    assert all(s["state"] == ProcessState.RUNNING.value for s in app1_status)
    assert all(s["state"] == ProcessState.STOPPED.value for s in app2_status)

    # Start app2
    res = await handler.start(["app2"])
    assert res.get("app2") == "started"
    await asyncio.sleep(1.2)
    app2_running = handler.get_status(["app2"])
    assert app2_running[0]["state"] == ProcessState.RUNNING.value

    # Shutdown all
    await handler.shutdown()
    all_stopped = handler.get_status()
    assert all(s["state"] == ProcessState.STOPPED.value for s in all_stopped)
