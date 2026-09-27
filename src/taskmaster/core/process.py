"""Individual child process controller and Supervisor state machine."""

import asyncio
import os
from pathlib import Path
import shlex
import signal
import time
from typing import Callable, List, Optional

from taskmaster.config.models import AutoRestart, ProgramConfig
from taskmaster.core.states import ProcessState
from taskmaster.utils.logger import TaskmasterLogger


class SubProcess:
    """Manages an individual child process instance within a service group."""

    def __init__(
        self,
        service_name: str,
        index: int,
        config: ProgramConfig,
        on_state_change: Optional[Callable[["SubProcess", ProcessState, ProcessState], None]] = None,
    ) -> None:
        self.service_name = service_name
        self.index = index
        self.name = f"{service_name}:{index}" if config.numprocs > 1 else service_name
        self.config = config
        self.on_state_change = on_state_change

        self.logger = TaskmasterLogger.get_logger(self.name)
        self.state: ProcessState = ProcessState.STOPPED

        self._process: Optional[asyncio.subprocess.Process] = None
        self.pid: Optional[int] = None
        self.returncode: Optional[int] = None
        self.start_time: Optional[float] = None
        self.stop_time: Optional[float] = None
        self.retries: int = 0

        self._health_task: Optional[asyncio.Task] = None
        self._wait_task: Optional[asyncio.Task] = None
        self._backoff_task: Optional[asyncio.Task] = None
        self._stdout_file = None
        self._stderr_file = None
        self._manual_stop: bool = False

    def set_state(self, new_state: ProcessState) -> None:
        """Transitions state and triggers callbacks/logging."""
        old_state = self.state
        if old_state != new_state:
            self.state = new_state
            self.logger.info(f"State transitioned: {old_state.value} -> {new_state.value}")
            if self.on_state_change:
                try:
                    self.on_state_change(self, old_state, new_state)
                except Exception as exc:
                    self.logger.error(f"Error in state change callback: {exc}")

    @property
    def uptime(self) -> Optional[float]:
        """Calculates running duration in seconds."""
        if self.state in (ProcessState.RUNNING, ProcessState.STARTING, ProcessState.STOPPING) and self.start_time:
            return round(time.time() - self.start_time, 1)
        return None

    def _prepare_stream(self, path_str: Optional[str]) -> Any:
        """Open output log stream in append mode using raw OS file descriptor."""
        if not path_str or path_str.upper() in ("DEVNULL", "DISCARD"):
            return asyncio.subprocess.DEVNULL
        
        target = Path(path_str).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return os.open(str(target), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)

    async def start(self) -> bool:
        """Start the child process according to configuration."""
        if self.state in (ProcessState.STARTING, ProcessState.RUNNING):
            self.logger.warning(f"Process already active in state {self.state.value}")
            return False

        self._manual_stop = False
        cmd_args = shlex.split(self.config.cmd)
        if not cmd_args:
            self.logger.error(f"Empty command in configuration: '{self.config.cmd}'")
            self.set_state(ProcessState.FATAL)
            return False

        # Validate working directory
        cwd = self.config.workingdir
        if cwd:
            cwd_path = Path(cwd).expanduser().resolve()
            if not cwd_path.is_dir():
                self.logger.error(f"Working directory does not exist: '{cwd}'")
                self.set_state(ProcessState.FATAL)
                return False
            cwd = str(cwd_path)

        # Merge environment variables
        env = os.environ.copy()
        if self.config.env:
            env.update(self.config.env)

        # Open streams
        try:
            self._stdout_file = self._prepare_stream(self.config.stdout)
            self._stderr_file = self._prepare_stream(self.config.stderr)
        except Exception as exc:
            self.logger.error(f"Failed to prepare stdout/stderr files: {exc}")
            self.set_state(ProcessState.FATAL)
            return False

        # Spawn child process
        try:
            kwargs = {
                "cwd": cwd,
                "env": env,
                "stdout": self._stdout_file,
                "stderr": self._stderr_file,
                "umask": self.config.umask,
            }
            if self.config.user:
                kwargs["user"] = self.config.user

            self._process = await asyncio.create_subprocess_exec(*cmd_args, **kwargs)
            self.pid = self._process.pid
            self.start_time = time.time()
            self.returncode = None
            self.set_state(ProcessState.STARTING)
            self.logger.info(f"Spawned process with PID {self.pid}")

            # Cancel existing tasks if any
            if self._health_task and not self._health_task.done():
                self._health_task.cancel()

            self._health_task = asyncio.create_task(self._health_check())
            return True

        except Exception as exc:
            self.logger.error(f"Failed to spawn process '{self.config.cmd}': {exc}")
            self._cleanup_files()
            self.set_state(ProcessState.FATAL)
            return False

    async def _health_check(self) -> None:
        """Monitors child during starttime period to confirm successful startup."""
        starttime = self.config.starttime

        try:
            if starttime > 0:
                # Poll child process during starttime
                poll_interval = 0.1
                elapsed = 0.0
                while elapsed < starttime:
                    await asyncio.sleep(min(poll_interval, starttime - elapsed))
                    elapsed += poll_interval
                    if self._process is None or self._process.returncode is not None:
                        break

            # Check if process is still alive
            if self._process and self._process.returncode is None:
                # Successfully survived starttime!
                self.set_state(ProcessState.RUNNING)
                self.retries = 0
                self._wait_task = asyncio.create_task(self._monitor_running_process())
            else:
                # Early termination before starttime elapsed
                exit_code = self._process.returncode if self._process else -1
                self.returncode = exit_code
                self.logger.warning(
                    f"Process exited prematurely before starttime ({starttime}s) with code {exit_code}"
                )
                self._cleanup_files()
                self._handle_early_exit()

        except asyncio.CancelledError:
            pass

    def _handle_early_exit(self) -> None:
        """Handle process death during STARTING phase."""
        if self._manual_stop:
            self.set_state(ProcessState.STOPPED)
            return

        self.retries += 1
        if self.retries <= self.config.startretries:
            self.set_state(ProcessState.BACKOFF)
            delay = min(self.retries * 1.0, 15.0)
            self.logger.info(
                f"Entering backoff. Retrying spawn in {delay}s (attempt {self.retries}/{self.config.startretries})"
            )
            self._backoff_task = asyncio.create_task(self._delayed_restart(delay))
        else:
            self.logger.error(
                f"Max start retries ({self.config.startretries}) exhausted. Entering FATAL state."
            )
            self.set_state(ProcessState.FATAL)

    async def _delayed_restart(self, delay: float) -> None:
        """Sleeps backoff duration and triggers start."""
        try:
            await asyncio.sleep(delay)
            if self.state == ProcessState.BACKOFF and not self._manual_stop:
                await self.start()
        except asyncio.CancelledError:
            pass

    async def _monitor_running_process(self) -> None:
        """Awaits process termination while in RUNNING state."""
        if not self._process:
            return

        try:
            await self._process.wait()
            self.returncode = self._process.returncode
            self.stop_time = time.time()
            self._cleanup_files()

            if self.state == ProcessState.STOPPING or self._manual_stop:
                self.set_state(ProcessState.STOPPED)
                return

            self.logger.info(f"Process terminated with exit code {self.returncode}")
            self.set_state(ProcessState.EXITED)
            self._handle_autorestart()

        except asyncio.CancelledError:
            pass

    def _handle_autorestart(self) -> None:
        """Evaluates autorestart policy upon process exit."""
        if self._manual_stop:
            return

        policy = self.config.autorestart
        should_restart = False

        if policy == AutoRestart.ALWAYS:
            self.logger.info("Autorestart policy is 'always': initiating restart.")
            should_restart = True
        elif policy == AutoRestart.UNEXPECTED:
            if self.returncode not in self.config.exitcodes:
                self.logger.warning(
                    f"Unexpected exit code {self.returncode} (expected: {self.config.exitcodes}). Initiating autorestart."
                )
                should_restart = True
            else:
                self.logger.info(
                    f"Expected exit code {self.returncode}. No autorestart needed."
                )
        else:
            self.logger.info("Autorestart policy is 'never': remaining in EXITED state.")

        if should_restart:
            asyncio.create_task(self.start())

    async def stop(self) -> bool:
        """Gracefully stop process using configured stopsignal and stoptime."""
        self._manual_stop = True

        # Cancel pending restarts
        if self._backoff_task and not self._backoff_task.done():
            self._backoff_task.cancel()
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

        if self.state not in (ProcessState.STARTING, ProcessState.RUNNING):
            self.logger.debug(f"Process not running (current state: {self.state.value})")
            if self.state != ProcessState.FATAL:
                self.set_state(ProcessState.STOPPED)
            return True

        if not self._process or self._process.returncode is not None:
            self.set_state(ProcessState.STOPPED)
            return True

        self.set_state(ProcessState.STOPPING)
        sig = self.config.stopsignal
        self.logger.info(f"Sending stopsignal {sig.name} to PID {self.pid}")

        try:
            self._process.send_signal(sig)
        except ProcessLookupError:
            self.set_state(ProcessState.STOPPED)
            return True

        stoptime = self.config.stoptime
        try:
            await asyncio.wait_for(self._process.wait(), timeout=max(stoptime, 0.1))
            self.logger.info(f"Process {self.pid} stopped gracefully.")
        except asyncio.TimeoutError:
            self.logger.warning(
                f"Process {self.pid} did not terminate within {stoptime}s. Sending SIGKILL forcefully."
            )
            try:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass

        self.returncode = self._process.returncode
        self.stop_time = time.time()
        self._cleanup_files()
        self.set_state(ProcessState.STOPPED)
        return True

    async def restart(self) -> bool:
        """Gracefully stop and then start process."""
        await self.stop()
        return await self.start()

    def _cleanup_files(self) -> None:
        """Close opened log files and file descriptors."""
        for handle in (self._stdout_file, self._stderr_file):
            if handle is not None:
                if isinstance(handle, int) and handle > 2:
                    try:
                        os.close(handle)
                    except OSError:
                        pass
                elif hasattr(handle, "close"):
                    try:
                        handle.close()
                    except Exception:
                        pass
        self._stdout_file = None
        self._stderr_file = None

    def update_config(self, new_config: ProgramConfig) -> None:
        """Update monitoring configuration in-place."""
        self.config = new_config
