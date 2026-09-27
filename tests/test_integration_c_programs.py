"""Integration tests using compiled C mock programs to mirror 42 defense testing."""

import asyncio
import os
from pathlib import Path
import tempfile
import pytest

from taskmaster.config.models import AutoRestart, ProgramConfig, TaskmasterConfig
from taskmaster.core.handler import ServiceHandler
from taskmaster.core.states import ProcessState

PROGRAMS_DIR = Path(__file__).parent / "programs"


@pytest.fixture(scope="module", autouse=True)
def ensure_binaries():
    """Ensure C binaries are compiled before running integration tests."""
    crasher = PROGRAMS_DIR / "crasher"
    if not crasher.exists():
        import subprocess
        subprocess.run(["make", "-C", str(PROGRAMS_DIR)], check=True)


@pytest.mark.asyncio
async def test_c_sleeper_normal_flow():
    sleeper_bin = str(PROGRAMS_DIR / "sleeper")
    cfg = TaskmasterConfig(
        programs={
            "c_sleeper": ProgramConfig(
                name="c_sleeper",
                cmd=f"{sleeper_bin} 10",
                starttime=1,
                stoptime=2,
            )
        }
    )
    handler = ServiceHandler(cfg)
    try:
        await handler.start(["c_sleeper"])
        await asyncio.sleep(1.2)

        status = handler.get_status(["c_sleeper"])
        assert status[0]["state"] == ProcessState.RUNNING.value
        assert status[0]["pid"] is not None

        await handler.stop(["c_sleeper"])
        status_stopped = handler.get_status(["c_sleeper"])
        assert status_stopped[0]["state"] == ProcessState.STOPPED.value
    finally:
        await handler.shutdown()


@pytest.mark.asyncio
async def test_c_sigignorer_sigkill_fallback():
    sigignorer_bin = str(PROGRAMS_DIR / "sigignorer")
    cfg = TaskmasterConfig(
        programs={
            "c_sigignorer": ProgramConfig(
                name="c_sigignorer",
                cmd=sigignorer_bin,
                starttime=1,
                stoptime=1,  # 1s before force kill
            )
        }
    )
    handler = ServiceHandler(cfg)
    try:
        await handler.start(["c_sigignorer"])
        await asyncio.sleep(1.2)

        status = handler.get_status(["c_sigignorer"])
        assert status[0]["state"] == ProcessState.RUNNING.value

        t0 = asyncio.get_event_loop().time()
        await handler.stop(["c_sigignorer"])
        t1 = asyncio.get_event_loop().time()

        status_stopped = handler.get_status(["c_sigignorer"])
        assert status_stopped[0]["state"] == ProcessState.STOPPED.value
        assert 0.9 <= (t1 - t0) <= 3.0
    finally:
        await handler.shutdown()


@pytest.mark.asyncio
async def test_c_crasher_fatal_state():
    crasher_bin = str(PROGRAMS_DIR / "crasher")
    cfg = TaskmasterConfig(
        programs={
            "c_crasher": ProgramConfig(
                name="c_crasher",
                cmd=f"{crasher_bin} 42",
                starttime=2,  # requires 2s to be healthy
                startretries=1,  # allow only 1 retry
                autorestart=AutoRestart.NEVER,
            )
        }
    )
    handler = ServiceHandler(cfg)
    try:
        await handler.start(["c_crasher"])
        await asyncio.sleep(2.5)

        status = handler.get_status(["c_crasher"])
        assert status[0]["state"] == ProcessState.FATAL.value
    finally:
        await handler.shutdown()


@pytest.mark.asyncio
async def test_c_flooder_output_streams():
    flooder_bin = str(PROGRAMS_DIR / "flooder")
    with tempfile.TemporaryDirectory() as tmpdir:
        stdout_file = os.path.join(tmpdir, "flooder.stdout")
        stderr_file = os.path.join(tmpdir, "flooder.stderr")

        cfg = TaskmasterConfig(
            programs={
                "c_flooder": ProgramConfig(
                    name="c_flooder",
                    cmd=flooder_bin,
                    starttime=0,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
            }
        )
        handler = ServiceHandler(cfg)
        try:
            await handler.start(["c_flooder"])
            await asyncio.sleep(1.0)
            await handler.stop(["c_flooder"])

            assert os.path.exists(stdout_file)
            assert os.path.exists(stderr_file)

            with open(stdout_file, "r", encoding="utf-8") as f:
                stdout_lines = f.readlines()
                assert len(stdout_lines) >= 150
                assert "[STDOUT] Flooding" in stdout_lines[0]

            with open(stderr_file, "r", encoding="utf-8") as f:
                stderr_lines = f.readlines()
                assert len(stderr_lines) >= 150
                assert "[STDERR] Flooding" in stderr_lines[0]
        finally:
            await handler.shutdown()


@pytest.mark.asyncio
async def test_c_umask_enforcement():
    umask_bin = str(PROGRAMS_DIR / "umask_checker")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "created_file.txt")
        cfg = TaskmasterConfig(
            programs={
                "c_umask": ProgramConfig(
                    name="c_umask",
                    cmd=f"{umask_bin} {test_file}",
                    umask=0o077,  # octal 077 -> only user permissions (0600)
                    starttime=0,
                )
            }
        )
        handler = ServiceHandler(cfg)
        try:
            await handler.start(["c_umask"])
            await asyncio.sleep(0.5)
            await handler.stop(["c_umask"])

            assert os.path.exists(test_file)
            mode = os.stat(test_file).st_mode & 0o777
            assert mode == 0o600
        finally:
            await handler.shutdown()


@pytest.mark.asyncio
async def test_c_env_checker():
    env_bin = str(PROGRAMS_DIR / "env_checker")
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = os.path.join(tmpdir, "env.out")
        cfg = TaskmasterConfig(
            programs={
                "c_env": ProgramConfig(
                    name="c_env",
                    cmd=f"{env_bin} SPECIAL_42_KEY",
                    env={"SPECIAL_42_KEY": "TASKMASTER_SUCCESS"},
                    stdout=out_file,
                    starttime=0,
                )
            }
        )
        handler = ServiceHandler(cfg)
        try:
            await handler.start(["c_env"])
            await asyncio.sleep(0.5)
            await handler.stop(["c_env"])

            assert os.path.exists(out_file)
            with open(out_file, "r", encoding="utf-8") as f:
                content = f.read()
                assert "SPECIAL_42_KEY=TASKMASTER_SUCCESS" in content
        finally:
            await handler.shutdown()
