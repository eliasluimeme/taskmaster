"""Unit and integration tests for hot configuration reloading."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import pytest

from taskmaster.config.parser import ConfigParser
from taskmaster.config.reconciler import ConfigReconciler
from taskmaster.core.handler import ServiceHandler
from taskmaster.core.states import ProcessState


@pytest.mark.asyncio
async def test_hot_reload_lifecycle():
    """Comprehensive test verifying hot reload behavior across additions, removals, updates, and PID preservation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "taskmaster.yml")

        # Initial configuration: service1 (2 procs), service2 (1 proc)
        initial_yaml = f"""
        programs:
          service1:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 2
            autostart: true
            starttime: 1
            startretries: 3
          service2:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 1
            autostart: true
            starttime: 1
        """
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(initial_yaml)

        config = ConfigParser.load(config_path)
        handler = ServiceHandler(config)
        await handler.autostart_all()
        await asyncio.sleep(1.2)

        # Check initial state
        assert len(handler.services) == 2
        s1 = handler.services["service1"]
        s2 = handler.services["service2"]
        assert all(p.state == ProcessState.RUNNING for p in s1.processes)
        assert all(p.state == ProcessState.RUNNING for p in s2.processes)

        s1_original_pids = [p.pid for p in s1.processes]
        s2_original_pid = s2.processes[0].pid

        # -------------------------------------------------------------
        # 1. Reload with INVALID YAML: must be rejected without affecting running services
        # -------------------------------------------------------------
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("programs:\n  bad_syntax: [broken")

        report_err = await handler.reload()
        assert len(report_err.errors) > 0
        # PIDs and states must remain untouched!
        assert [p.pid for p in s1.processes] == s1_original_pids
        assert s2.processes[0].pid == s2_original_pid
        assert all(p.state == ProcessState.RUNNING for p in s1.processes)

        # -------------------------------------------------------------
        # 2. Reload with IN-PLACE update (monitoring params only)
        # Change startretries from 3 to 5 on service1.
        # Strict Subject Requirement: MUST NOT de-spawn or restart service1!
        # -------------------------------------------------------------
        updated_monitoring_yaml = f"""
        programs:
          service1:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 2
            autostart: true
            starttime: 1
            startretries: 5
          service2:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 1
            autostart: true
            starttime: 1
        """
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(updated_monitoring_yaml)

        report_update = await handler.reload()
        assert "service1" in report_update.updated_in_place
        assert s1.config.startretries == 5
        # Assert PIDs did NOT change!
        assert [p.pid for p in s1.processes] == s1_original_pids

        # -------------------------------------------------------------
        # 3. Reload with SCALING: increase service1 numprocs to 3, remove service2, add service3
        # -------------------------------------------------------------
        reconfigured_yaml = f"""
        programs:
          service1:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 3
            autostart: true
            starttime: 1
            startretries: 5
          service3:
            cmd: "{sys.executable} -c 'import time; time.sleep(20)'"
            numprocs: 1
            autostart: true
            starttime: 1
        """
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(reconfigured_yaml)

        report_recon = await handler.reload()
        await asyncio.sleep(1.2)

        assert "service2" in report_recon.removed
        assert "service3" in report_recon.added
        assert "service1" in report_recon.numprocs_adjusted

        assert "service2" not in handler.services
        assert "service3" in handler.services
        assert len(handler.services["service1"].processes) == 3

        # First 2 PIDs of service1 MUST still be identical!
        assert handler.services["service1"].processes[0].pid == s1_original_pids[0]
        assert handler.services["service1"].processes[1].pid == s1_original_pids[1]
        assert handler.services["service1"].processes[2].pid is not None
        assert handler.services["service3"].processes[0].state == ProcessState.RUNNING

        await handler.shutdown()
