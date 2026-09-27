"""taskmasterctl - Remote client CLI for controlling taskmasterd."""

import argparse
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

from taskmaster.ipc.client import IPCClient


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="taskmasterctl",
        description="taskmasterctl - Remote supervisor client (42 School Bonus)",
    )
    parser.add_argument(
        "-s",
        "--socket",
        default="/tmp/taskmaster.sock",
        help="Path to taskmasterd UNIX domain socket (default: /tmp/taskmaster.sock)",
    )
    parser.add_argument(
        "action",
        nargs="*",
        help="Command to execute (e.g. status, start <name>, stop <name>). Omit for interactive shell.",
    )
    return parser.parse_args(args)


async def run_client(args: argparse.Namespace) -> int:
    client = IPCClient(socket_path=args.socket)

    # 1. One-shot execution mode
    if args.action:
        cmd_line = " ".join(args.action)
        _, output = await client.send_command(cmd_line)
        if output:
            print(output)
        return 0

    # 2. Interactive shell mode
    print(f"Connected to taskmasterd at '{args.socket}'")
    print("Type 'help' for commands, 'status' for process table, 'quit' to exit.\n")

    history_path = Path.home() / ".taskmasterctl_history"

    if not sys.stdin.isatty() or not HAVE_PROMPT_TOOLKIT:
        # Piped / Stream mode
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line_bytes = await reader.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            should_exit, output = await client.send_command(line)
            if output:
                print(output)
            if should_exit:
                break
        return 0

    session: PromptSession = PromptSession(history=FileHistory(str(history_path)))
    verbs = ["status", "start", "stop", "restart", "reload", "tail", "help", "quit", "exit", "all"]

    while True:
        try:
            line = await session.prompt_async(
                "taskmasterctl> ",
                completer=WordCompleter(verbs, ignore_case=True, sentence=True),
            )
            line = line.strip()
            if not line:
                continue

            should_exit, output = await client.send_command(line)
            if output:
                print(output)
            if should_exit or line in ("quit", "exit"):
                break

        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print("\nExiting taskmasterctl...")
            break
        except Exception as exc:
            print(f"Client error: {exc}")

    return 0


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(run_client(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nExiting taskmasterctl...")
        sys.exit(0)


if __name__ == "__main__":
    main()
