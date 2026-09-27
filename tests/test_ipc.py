"""Unit and integration tests for UNIX domain socket IPC (Client/Server mode)."""

import asyncio
import os
import sys
import tempfile
import pytest

from taskmaster.config.models import ProgramConfig, TaskmasterConfig
from taskmaster.core.handler import ServiceHandler
from taskmaster.ipc.client import IPCClient
from taskmaster.ipc.server import IPCServer


@pytest.mark.asyncio
async def test_ipc_client_server_communication():
    """Verify that IPCClient connects to IPCServer and executes commands over UNIX socket."""
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "taskmaster_test.sock")

        cfg = TaskmasterConfig(
            programs={
                "demo_prog": ProgramConfig(
                    name="demo_prog",
                    cmd=f"{sys.executable} -c 'import time; time.sleep(10)'",
                    numprocs=1,
                    autostart=False,
                    starttime=1,
                )
            }
        )
        handler = ServiceHandler(cfg)
        server = IPCServer(handler, socket_path=socket_path)
        await server.start()

        client = IPCClient(socket_path=socket_path)

        # 1. Test status command
        should_exit, out_status = await client.send_command("status")
        assert should_exit is False
        assert "demo_prog" in out_status
        assert "STOPPED" in out_status

        # 2. Test start command
        _, out_start = await client.send_command("start demo_prog")
        assert "demo_prog: started" in out_start
        await asyncio.sleep(1.2)

        _, out_status2 = await client.send_command("status")
        assert "RUNNING" in out_status2

        # 3. Test stop command
        _, out_stop = await client.send_command("stop demo_prog")
        assert "demo_prog: stopped" in out_stop

        # Stop server
        await server.stop()
        assert not os.path.exists(socket_path)


@pytest.mark.asyncio
async def test_ipc_client_when_server_not_running():
    """Verify clean error reporting when daemon socket is unreachable."""
    client = IPCClient(socket_path="/tmp/nonexistent_socket_12345.sock")
    should_exit, out = await client.send_command("status")
    assert should_exit is False
    assert "Error: Cannot connect" in out
