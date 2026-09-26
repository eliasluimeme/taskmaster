"""Service group manager coordinating multiple subprocess instances."""

import asyncio
from typing import Any, Callable, Dict, List, Optional

from taskmaster.config.models import ProgramConfig
from taskmaster.core.process import SubProcess
from taskmaster.core.states import ProcessState
from taskmaster.utils.logger import TaskmasterLogger


class Service:
    """Manages a configured program and its pool of numprocs child processes."""

    def __init__(
        self,
        config: ProgramConfig,
        on_process_state_change: Optional[Callable[[SubProcess, ProcessState, ProcessState], None]] = None,
    ) -> None:
        self.name = config.name
        self.config = config
        self.on_process_state_change = on_process_state_change
        self.logger = TaskmasterLogger.get_logger(self.name)

        self.processes: List[SubProcess] = []
        self._init_processes(config.numprocs)

    def _init_processes(self, count: int) -> None:
        """Create SubProcess instances for the service pool."""
        start_idx = len(self.processes)
        for i in range(count):
            idx = start_idx + i
            proc = SubProcess(
                service_name=self.name,
                index=idx,
                config=self.config,
                on_state_change=self.on_process_state_change,
            )
            self.processes.append(proc)

    async def start(self) -> None:
        """Start all processes in the service group concurrently."""
        self.logger.info(f"Starting service '{self.name}' ({len(self.processes)} processes)")
        await asyncio.gather(*(proc.start() for proc in self.processes))

    async def stop(self) -> None:
        """Stop all processes in the service group concurrently."""
        self.logger.info(f"Stopping service '{self.name}' ({len(self.processes)} processes)")
        await asyncio.gather(*(proc.stop() for proc in self.processes))

    async def restart(self) -> None:
        """Restart all processes in the service group concurrently."""
        self.logger.info(f"Restarting service '{self.name}' ({len(self.processes)} processes)")
        await asyncio.gather(*(proc.restart() for proc in self.processes))

    async def autostart_if_needed(self) -> None:
        """Launch processes if autostart is enabled."""
        if self.config.autostart:
            self.logger.info(f"Autostart enabled for service '{self.name}'")
            await self.start()

    def get_status(self) -> List[Dict[str, Any]]:
        """Return status records for all processes in this service."""
        return [
            {
                "service": self.name,
                "name": proc.name,
                "index": proc.index,
                "state": proc.state.value,
                "pid": proc.pid,
                "uptime": proc.uptime,
                "returncode": proc.returncode,
                "retries": proc.retries,
            }
            for proc in self.processes
        ]

    def update_config(self, new_config: ProgramConfig) -> None:
        """Update monitoring configuration parameters in-place for all instances."""
        self.config = new_config
        for proc in self.processes:
            proc.update_config(new_config)

    async def adjust_numprocs(self, target_numprocs: int) -> None:
        """
        Scale process count up or down without affecting existing instances.
        Fixes the numprocs reload bug in reference supervisor.
        """
        current_count = len(self.processes)
        if target_numprocs == current_count:
            return

        if target_numprocs > current_count:
            diff = target_numprocs - current_count
            self.logger.info(f"Scaling up service '{self.name}': adding {diff} instances")
            self._init_processes(diff)
            # If service is active or autostart is on, launch the newly created instances
            new_procs = self.processes[current_count:]
            if self.config.autostart or any(p.state == ProcessState.RUNNING for p in self.processes[:current_count]):
                await asyncio.gather(*(p.start() for p in new_procs))

        else:
            diff = current_count - target_numprocs
            self.logger.info(f"Scaling down service '{self.name}': removing {diff} instances")
            excess_procs = [self.processes.pop() for _ in range(diff)]
            await asyncio.gather(*(p.stop() for p in excess_procs))
