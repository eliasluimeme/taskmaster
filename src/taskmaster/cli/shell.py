"""Interactive control shell for Taskmaster."""

import asyncio
from pathlib import Path
import sys
from typing import Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.history import FileHistory
    HAVE_PROMPT_TOOLKIT = True
except ImportError:
    HAVE_PROMPT_TOOLKIT = False

from taskmaster.cli.commands import CommandHandler
from taskmaster.core.handler import ServiceHandler


class ShellController:
    """Provides the interactive control shell for the user in foreground mode."""

    def __init__(self, handler: ServiceHandler, history_file: Optional[str] = None) -> None:
        self.handler = handler
        self.cmd_handler = CommandHandler(handler)
        self.history_path = (
            Path(history_file).expanduser().resolve()
            if history_file
            else Path.home() / ".taskmaster_history"
        )
        self._running: bool = False

    async def run(self) -> None:
        """Run the interactive shell loop until exit or EOF."""
        self._running = True

        # Check if running in an interactive terminal
        if not sys.stdin.isatty() or not HAVE_PROMPT_TOOLKIT:
            await self._run_stream_mode()
            return

        session: PromptSession = PromptSession(
            history=FileHistory(str(self.history_path)),
        )

        print("Taskmaster Job Control Shell")
        print("Type 'help' for commands, 'status' for process table, 'quit' to exit.\n")

        while self._running:
            try:
                # Update autocomplete words dynamically
                completer = WordCompleter(
                    self.cmd_handler.get_completions(),
                    ignore_case=True,
                    sentence=True,
                )
                line = await session.prompt_async("taskmaster> ", completer=completer)
                should_exit, output = await self.cmd_handler.execute(line)
                if output:
                    print(output)
                if should_exit:
                    self._running = False
                    break

            except KeyboardInterrupt:
                # Ctrl+C clears current input line without quitting
                print()
                continue
            except EOFError:
                # Ctrl+D triggers graceful exit
                print("\nReceived EOF. Exiting...")
                await self.handler.shutdown()
                self._running = False
                break
            except Exception as exc:
                print(f"Error executing command: {exc}")

    async def _run_stream_mode(self) -> None:
        """Stream input reader for non-interactive / piped environments."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self._running:
            line_bytes = await reader.readline()
            if not line_bytes:
                # End of piped input
                await self.handler.shutdown()
                break

            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            should_exit, output = await self.cmd_handler.execute(line)
            if output:
                print(output)
            if should_exit:
                self._running = False
                break
