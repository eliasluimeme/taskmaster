"""Differential Configuration Reconciler for zero-downtime hot reloading."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from taskmaster.config.models import ProgramConfig, TaskmasterConfig
from taskmaster.config.parser import ConfigError, ConfigParser
from taskmaster.utils.logger import TaskmasterLogger


@dataclass
class ReconciliationReport:
    """Summary of changes applied during a hot configuration reload."""
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    restarted: List[str] = field(default_factory=list)
    updated_in_place: List[str] = field(default_factory=list)
    numprocs_adjusted: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added
            or self.removed
            or self.restarted
            or self.updated_in_place
            or self.numprocs_adjusted
        )

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"Added: {', '.join(self.added)}")
        if self.removed:
            parts.append(f"Removed: {', '.join(self.removed)}")
        if self.restarted:
            parts.append(f"Restarted (config changed): {', '.join(self.restarted)}")
        if self.numprocs_adjusted:
            adj = [f"{k} ({old}->{new})" for k, (old, new) in self.numprocs_adjusted.items()]
            parts.append(f"Scaled: {', '.join(adj)}")
        if self.updated_in_place:
            parts.append(f"Updated in-place: {', '.join(self.updated_in_place)}")
        if not parts:
            return "No changes detected."
        return "; ".join(parts)


class ConfigReconciler:
    """Safely reconciles differences between running state and newly parsed configuration."""

    logger = TaskmasterLogger.get_logger("reconciler")

    @classmethod
    async def reload_from_file(cls, handler: Any, config_path: Optional[str] = None) -> ReconciliationReport:
        """Parse configuration file and reconcile active services."""
        path = config_path or handler.config.config_path
        if not path:
            report = ReconciliationReport()
            report.errors.append("No configuration file path specified for reload.")
            cls.logger.error("Reload aborted: no configuration file path.")
            return report

        try:
            new_config = ConfigParser.load(path)
        except ConfigError as exc:
            report = ReconciliationReport()
            report.errors.append(str(exc))
            cls.logger.error(f"Configuration reload rejected: {exc}")
            return report

        return await cls.reconcile(handler, new_config)

    @classmethod
    async def reconcile(cls, handler: Any, new_config: TaskmasterConfig) -> ReconciliationReport:
        """
        Compare active services against new_config and apply minimal disruptive changes.
        Guarantee: Unchanged processes are NEVER interrupted or de-spawned.
        """
        from taskmaster.core.service import Service

        report = ReconciliationReport()
        cls.logger.info("Beginning configuration reconciliation...")

        current_names = set(handler.services.keys())
        new_names = set(new_config.programs.keys())

        # 1. Removed services
        removed_names = current_names - new_names
        for name in removed_names:
            cls.logger.info(f"Reconcile: removing service '{name}'")
            svc = handler.services.pop(name)
            await svc.stop()
            report.removed.append(name)

        # 2. Added services
        added_names = new_names - current_names
        for name in added_names:
            cls.logger.info(f"Reconcile: adding new service '{name}'")
            new_svc = Service(
                config=new_config.programs[name],
                on_process_state_change=handler.on_process_state_change,
            )
            handler.services[name] = new_svc
            await new_svc.autostart_if_needed()
            report.added.append(name)

        # 3. Retained services
        retained_names = current_names & new_names
        for name in retained_names:
            svc = handler.services[name]
            old_cfg = svc.config
            new_cfg = new_config.programs[name]

            # Check if runtime parameters changed
            if not old_cfg.runtime_parameters_equal(new_cfg):
                cls.logger.info(
                    f"Reconcile: runtime parameters changed for '{name}' - gracefully restarting"
                )
                svc.update_config(new_cfg)
                await svc.adjust_numprocs(new_cfg.numprocs)
                await svc.restart()
                report.restarted.append(name)
            else:
                # Runtime parameters identical: update monitoring in-place without restart!
                svc.update_config(new_cfg)
                if new_cfg.numprocs != len(svc.processes):
                    old_count = len(svc.processes)
                    cls.logger.info(
                        f"Reconcile: scaling '{name}' from {old_count} to {new_cfg.numprocs}"
                    )
                    await svc.adjust_numprocs(new_cfg.numprocs)
                    report.numprocs_adjusted[name] = (old_count, new_cfg.numprocs)
                else:
                    cls.logger.info(f"Reconcile: updating monitoring parameters in-place for '{name}'")
                    report.updated_in_place.append(name)

        handler.config = new_config
        cls.logger.info(f"Reconciliation completed: {report.summary()}")
        return report


from typing import Any
