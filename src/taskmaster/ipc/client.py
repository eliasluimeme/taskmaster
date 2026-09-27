"""UNIX Domain Socket IPC Client for taskmasterctl."""

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Optional, Tuple


class IPCClient:
    """Connects to taskmasterd daemon over UNIX domain socket."""

    def __init__(self, socket_path: str = "/tmp/taskmaster.sock") -> None:
        self.socket_path = socket_path

    async def send_command(self, cmd_line: str) -> Tuple[bool, str]:
        """Send a single command to the daemon and receive output."""
        if not os.path.exists(self.socket_path):
            return False, f"Error: Cannot connect to taskmasterd. Socket '{self.socket_path}' does not exist."

        try:
            reader, writer = await asyncio.open_unix_connection(self.socket_path)
            payload = json.dumps({"cmd": cmd_line}) + "\n"
            writer.write(payload.encode("utf-8"))
            await writer.drain()

            response_line = await reader.readline()
            writer.close()
            await writer.wait_closed()

            if not response_line:
                return False, "Error: Daemon closed connection unexpectedly."

            data = json.loads(response_line.decode("utf-8"))
            return data.get("should_exit", False), data.get("output", "")

        except (ConnectionRefusedError, FileNotFoundError):
            return False, f"Error: Connection refused. Is taskmasterd running on '{self.socket_path}'?"
        except Exception as exc:
            return False, f"IPC Error: {exc}"
