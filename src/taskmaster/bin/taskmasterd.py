"""taskmasterd - Headless supervisor daemon executable."""

import argparse
import asyncio
from pathlib import Path
import signal
import sys
from typing import Optional

from taskmaster import __version__
from taskmaster.config.parser import ConfigError, ConfigParser
from taskmaster.core.handler import ServiceHandler
from taskmaster.ipc.server import IPCServer
from taskmaster.utils.logger import TaskmasterLogger, logger


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="taskmasterd",
        description="taskmasterd - Headless supervisor daemon (42 School Bonus)",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="taskmaster.yml",
        help="Path to YAML configuration file (default: taskmaster.yml)",
    )
    parser.add_argument(
        "-s",
        "--socket",
        default="/tmp/taskmaster.sock",
        help="UNIX domain socket path (default: /tmp/taskmaster.sock)",
    )
    parser.add_argument(
        "-l",
        "--loglevel",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity level (default: INFO)",
    )
    parser.add_argument(
        "--logfile",
        default="logs/taskmasterd.log",
        help="Path to operational log file (default: logs/taskmasterd.log)",
    )
    return parser.parse_args(args)


async def run_daemon(args: argparse.Namespace) -> int:
    # 1. Setup logging
    TaskmasterLogger.setup(log_file=args.logfile, level=args.loglevel, console=True)
    logger.info(f"taskmasterd v{__version__} starting daemon...")

    # 2. Parse configuration
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"Error: Configuration file '{args.config}' not found.", file=sys.stderr)
        return 1

    try:
        config = ConfigParser.load(str(config_path))
    except ConfigError as exc:
        logger.error(f"Configuration load error: {exc}")
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    # 3. Instantiate handler and IPC server
    handler = ServiceHandler(config)
    socket_path = args.socket or config.socket_path
    ipc_server = IPCServer(handler, socket_path=socket_path)

    # 4. Attach signals
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def handle_sighup():
        logger.info("Daemon received SIGHUP: triggering reload.")
        asyncio.create_task(handler.reload())

    def handle_sigterm():
        logger.info("Daemon received stop signal: preparing shutdown.")
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGHUP, handle_sighup)
        loop.add_signal_handler(signal.SIGINT, handle_sigterm)
        loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    except NotImplementedError:
        pass

    # 5. Start IPC server & autostart services
    await ipc_server.start()
    await handler.autostart_all()
    print(f"taskmasterd running. IPC socket ready at '{socket_path}'.")

    # 6. Wait until termination signal
    try:
        await stop_event.wait()
    finally:
        print("Shutting down taskmasterd...")
        await ipc_server.stop()
        await handler.shutdown()

    return 0


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(run_daemon(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nDaemon terminated by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
