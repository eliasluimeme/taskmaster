"""ServiceHandler - Central supervisor managing all services and operational dispatch."""

import asyncio
import signal
from typing import Any, Callable, Dict, List, Optional

from taskmaster.config.models import TaskmasterConfig
from taskmaster.core.service import Service
from taskmaster.core.states import ProcessState
from taskmaster.utils.logger import TaskmasterLogger


class ServiceHandler:
    """Central supervisor coordinating all configured services."""

    def __init__(
        self,
        config: TaskmasterConfig,
        on_process_state_change: Optional[Callable[[Any, ProcessState, ProcessState], None]] = None,
    ) -> None:
        self.config = config
        self.on_process_state_change = on_process_state_change
        self.logger = TaskmasterLogger.get_logger("handler")
        self.services: Dict[str, Service] = {}

        self._init_services()

    def _init_services(self) -> None:
        """Instantiate Service managers from current configuration."""
        for name, prog_cfg in self.config.programs.items():
            self.services[name] = Service(
                config=prog_cfg,
                on_process_state_change=self.on_process_state_change,
            )

    async def autostart_all(self) -> None:
        """Launch all services configured with autostart: true."""
        self.logger.info("Triggering autostart for configured services.")
        tasks = [svc.autostart_if_needed() for svc in self.services.values()]
        if tasks:
            await asyncio.gather(*tasks)

    async def start(self, names: Optional[List[str]] = None) -> Dict[str, str]:
        """Start specified services or all services if names is None or contains 'all'."""
        targets = self._resolve_targets(names)
        results: Dict[str, str] = {}
        for name in targets:
            if name in self.services:
                await self.services[name].start()
                results[name] = "started"
            else:
                results[name] = "ERROR: no such service"
        return results

    async def stop(self, names: Optional[List[str]] = None) -> Dict[str, str]:
        """Stop specified services or all services if names is None or contains 'all'."""
        targets = self._resolve_targets(names)
        results: Dict[str, str] = {}
        for name in targets:
            if name in self.services:
                await self.services[name].stop()
                results[name] = "stopped"
            else:
                results[name] = "ERROR: no such service"
        return results

    async def restart(self, names: Optional[List[str]] = None) -> Dict[str, str]:
        """Restart specified services or all services if names is None or contains 'all'."""
        targets = self._resolve_targets(names)
        results: Dict[str, str] = {}
        for name in targets:
            if name in self.services:
                await self.services[name].restart()
                results[name] = "restarted"
            else:
                results[name] = "ERROR: no such service"
        return results

    async def reload(self, config_path: Optional[str] = None):
        """Hot reload configuration without interrupting unaffected running processes."""
        from taskmaster.config.reconciler import ConfigReconciler
        return await ConfigReconciler.reload_from_file(self, config_path)

    def _resolve_targets(self, names: Optional[List[str]]) -> List[str]:
        """Resolve list of service names, translating None or 'all' to all service names."""
        if not names or "all" in names:
            return list(self.services.keys())
        return names

    def get_status(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Return status records for specified services or all services."""
        targets = self._resolve_targets(names)
        records: List[Dict[str, Any]] = []
        for name in targets:
            if name in self.services:
                records.extend(self.services[name].get_status())
            else:
                records.append({
                    "service": name,
                    "name": name,
                    "index": 0,
                    "state": "UNKNOWN",
                    "pid": None,
                    "uptime": None,
                    "returncode": None,
                    "retries": 0,
                    "error": "No such service",
                })
        return records

    async def shutdown(self) -> None:
        """Gracefully stop all child processes before Taskmaster exits."""
        self.logger.info("Initiating supervisor shutdown: stopping all child processes.")
        tasks = [svc.stop() for svc in self.services.values()]
        if tasks:
            await asyncio.gather(*tasks)
        self.logger.info("All child processes terminated.")
