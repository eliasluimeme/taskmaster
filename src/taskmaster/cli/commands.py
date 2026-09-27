"""Command processor and table formatters for Taskmaster CLI shell."""

import os
from pathlib import Path
import shlex
from typing import Any, Dict, List, Optional, Tuple

from taskmaster.core.handler import ServiceHandler


class CommandHandler:
    """Executes CLI commands against the ServiceHandler and formats output."""

    COMMANDS = {
        "status": "status [name ...]        Display status of all or specified services",
        "start": "start <name ... | all>   Start specified stopped or exited services",
        "stop": "stop <name ... | all>    Stop specified running services gracefully",
        "restart": "restart <name ... | all> Restart specified services",
        "reload": "reload                  Reload configuration file without stopping supervisor",
        "tail": "tail [-n N] <name> [err] Display recent output logs of a service",
        "shutdown": "shutdown                  Gracefully stop all child processes and shut down supervisor",
        "help": "help [command]            Show documentation for available commands",
        "quit": "quit                      Gracefully stop all child processes and exit",
        "exit": "exit                      Alias for quit",
    }

    def __init__(self, handler: ServiceHandler) -> None:
        self.handler = handler

    def get_completions(self) -> List[str]:
        """Return list of command verbs and active service names for autocomplete."""
        verbs = list(self.COMMANDS.keys()) + ["all"]
        services = list(self.handler.services.keys())
        return sorted(set(verbs + services))

    async def execute(self, line: str) -> Tuple[bool, str]:
        """
        Parse and execute a command string.
        Returns (should_exit: bool, output_message: str).
        """
        line = line.strip()
        if not line:
            return False, ""

        try:
            parts = shlex.split(line)
        except ValueError as exc:
            return False, f"Syntax error in command: {exc}"

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("quit", "exit", "shutdown"):
            await self.handler.shutdown()
            return True, "Shutting down Taskmaster. Goodbye!"

        if cmd == "help":
            return False, self._handle_help(args)

        if cmd == "status":
            return False, self._handle_status(args)

        if cmd == "start":
            return False, await self._handle_start(args)

        if cmd == "stop":
            return False, await self._handle_stop(args)

        if cmd == "restart":
            return False, await self._handle_restart(args)

        if cmd == "reload":
            return False, await self._handle_reload(args)

        if cmd == "tail":
            return False, self._handle_tail(args)

        return False, f"Unknown command: '{cmd}'. Type 'help' for available commands."

    def _handle_help(self, args: List[str]) -> str:
        """Format help text for all or specific command."""
        if args:
            cmd = args[0].lower()
            if cmd in self.COMMANDS:
                return self.COMMANDS[cmd]
            return f"No help available for unknown command: '{cmd}'"

        lines = ["Available Taskmaster commands:"]
        for _, desc in sorted(self.COMMANDS.items()):
            lines.append(f"  {desc}")
        return "\n".join(lines)

    def _handle_status(self, args: List[str]) -> str:
        """Format and return status table for specified or all services."""
        records = self.handler.get_status(args if args else None)
        if not records:
            return "No programs configured."

        # Compute column widths
        col_name = "PROCESS"
        col_state = "STATE"
        col_pid = "PID"
        col_uptime = "UPTIME / EXIT"

        w_name = max(len(col_name), max(len(r.get("name", "")) for r in records))
        w_state = max(len(col_state), max(len(r.get("state", "")) for r in records))
        w_pid = max(len(col_pid), max(len(str(r.get("pid") or "-")) for r in records))

        header = f"{col_name:<{w_name}}  {col_state:<{w_state}}  {col_pid:<{w_pid}}  {col_uptime}"
        sep = "-" * (len(header) + 12)
        lines = [header, sep]

        for r in records:
            name = r.get("name", "")
            state = r.get("state", "")
            pid_str = str(r.get("pid")) if r.get("pid") else "-"

            if state == "RUNNING" and r.get("uptime") is not None:
                detail = f"uptime {int(r['uptime'])}s"
            elif state in ("EXITED", "FATAL") and r.get("returncode") is not None:
                detail = f"exit code {r['returncode']}"
            elif "error" in r:
                detail = r["error"]
            else:
                detail = "-"

            lines.append(f"{name:<{w_name}}  {state:<{w_state}}  {pid_str:<{w_pid}}  {detail}")

        return "\n".join(lines)

    async def _handle_start(self, args: List[str]) -> str:
        if not args:
            return "Usage: start <name ... | all>"
        results = await self.handler.start(args)
        return "\n".join(f"{name}: {status}" for name, status in results.items())

    async def _handle_stop(self, args: List[str]) -> str:
        if not args:
            return "Usage: stop <name ... | all>"
        results = await self.handler.stop(args)
        return "\n".join(f"{name}: {status}" for name, status in results.items())

    async def _handle_restart(self, args: List[str]) -> str:
        if not args:
            return "Usage: restart <name ... | all>"
        results = await self.handler.restart(args)
        return "\n".join(f"{name}: {status}" for name, status in results.items())

    async def _handle_reload(self, args: List[str]) -> str:
        config_path = args[0] if args else None
        report = await self.handler.reload(config_path)
        if report.errors:
            return f"Reload failed: {'; '.join(report.errors)}"
        return f"Reload successful: {report.summary()}"

    def _handle_tail(self, args: List[str]) -> str:
        """Display recent lines from service stdout or stderr file."""
        if not args:
            return "Usage: tail [-n lines] <service_name> [stdout|stderr]"

        num_lines = 20
        idx = 0
        if args[0] == "-n" and len(args) > 2:
            try:
                num_lines = int(args[1])
                idx = 2
            except ValueError:
                return "Invalid number of lines."

        if idx >= len(args):
            return "Missing service name."

        svc_name = args[idx]
        stream_type = args[idx + 1].lower() if len(args) > idx + 1 else "stdout"

        if svc_name not in self.handler.services:
            return f"Service '{svc_name}' not found."

        svc = self.handler.services[svc_name]
        log_path = svc.config.stderr if stream_type in ("stderr", "err") else svc.config.stdout

        if not log_path or not os.path.exists(log_path):
            return f"No log file configured or found for '{svc_name}' {stream_type}."

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail_slice = lines[-num_lines:] if len(lines) > num_lines else lines
                return "".join(tail_slice).rstrip()
        except Exception as exc:
            return f"Error reading log file '{log_path}': {exc}"
