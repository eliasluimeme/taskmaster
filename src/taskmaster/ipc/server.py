"""UNIX Domain Socket IPC Server for Client/Server Daemon mode."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from taskmaster.cli.commands import CommandHandler
from taskmaster.core.handler import ServiceHandler
from taskmaster.utils.logger import TaskmasterLogger


class IPCServer:
    """Listens on a UNIX domain socket and executes commands from taskmasterctl."""

    def __init__(
        self,
        handler: ServiceHandler,
        socket_path: str = "/tmp/taskmaster.sock",
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        self.handler = handler
        self.cmd_handler = CommandHandler(handler)
        self.socket_path = socket_path
        self.stop_event = stop_event
        self.logger = TaskmasterLogger.get_logger("ipc_server")
        self._server: Optional[asyncio.Server] = None
        self._running: bool = False

    async def start(self) -> None:
        """Start listening on the UNIX domain socket."""
        # Unlink existing socket file if dead
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError as exc:
                self.logger.warning(f"Failed to remove stale socket {self.socket_path}: {exc}")

        # Ensure parent directory exists
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )
        self._running = True
        self.logger.info(f"IPC Server listening on UNIX socket: {self.socket_path}")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming client connections."""
        while self._running:
            line_bytes = await reader.readline()
            if not line_bytes:
                break

            raw_str = line_bytes.decode("utf-8", errors="replace").strip()
            if not raw_str:
                continue

            # Support both JSON payload and plain text command
            cmd_line = raw_str
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    payload = json.loads(raw_str)
                    cmd_line = payload.get("cmd") or payload.get("command") or ""
                except json.JSONDecodeError:
                    pass

            # Execute command
            should_exit, output = await self.cmd_handler.execute(cmd_line)

            # Send response terminated by newline
            response = {
                "output": output,
                "should_exit": should_exit,
            }
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()

            if should_exit:
                self._running = False
                if self.stop_event:
                    self.stop_event.set()
                break

        writer.close()
        await writer.wait_closed()

    async def stop(self) -> None:
        """Stop IPC server and remove socket file."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        self.logger.info("IPC Server stopped.")
