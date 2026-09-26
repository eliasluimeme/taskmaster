"""Unit tests for Service process group manager."""

import asyncio
import sys
import pytest

from taskmaster.config.models import ProgramConfig
from taskmaster.core.service import Service
from taskmaster.core.states import ProcessState


@pytest.mark.asyncio
async def test_service_pool_creation_and_autostart():
    """Verify numprocs creates matching instances and autostart launches them."""
    cfg = ProgramConfig(
        name="multi_worker",
        cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
        numprocs=3,
        autostart=True,
        starttime=1,
    )
    svc = Service(cfg)
    assert len(svc.processes) == 3
    assert [p.name for p in svc.processes] == ["multi_worker:0", "multi_worker:1", "multi_worker:2"]

    await svc.autostart_if_needed()
    await asyncio.sleep(1.2)

    status = svc.get_status()
    assert len(status) == 3
    for s in status:
        assert s["state"] == ProcessState.RUNNING.value
        assert s["pid"] is not None

    await svc.stop()
    for p in svc.processes:
        assert p.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_service_adjust_numprocs_scale_up_and_down():
    """Verify adjusting numprocs without interrupting existing running instances."""
    cfg = ProgramConfig(
        name="scalable_service",
        cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
        numprocs=2,
        autostart=True,
        starttime=1,
    )
    svc = Service(cfg)
    await svc.start()
    await asyncio.sleep(1.2)

    # Initial 2 PIDs
    initial_pids = [p.pid for p in svc.processes]
    assert len(initial_pids) == 2
    assert all(pid is not None for pid in initial_pids)

    # Scale UP from 2 to 4
    await svc.adjust_numprocs(4)
    await asyncio.sleep(1.2)
    assert len(svc.processes) == 4
    # The first 2 PIDs must remain exactly the same!
    assert svc.processes[0].pid == initial_pids[0]
    assert svc.processes[1].pid == initial_pids[1]
    assert svc.processes[2].pid is not None
    assert svc.processes[3].pid is not None

    # Scale DOWN from 4 to 1
    await svc.adjust_numprocs(1)
    assert len(svc.processes) == 1
    # Process 0 must still be running with original PID!
    assert svc.processes[0].pid == initial_pids[0]
    assert svc.processes[0].state == ProcessState.RUNNING

    await svc.stop()
