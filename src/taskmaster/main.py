"""Main entrypoint for Taskmaster supervisor."""

import argparse
import asyncio
from pathlib import Path
import signal
import sys
from typing import Optional

from taskmaster import __version__
from taskmaster.cli.shell import ShellController
from taskmaster.config.parser import ConfigError, ConfigParser
from taskmaster.core.handler import ServiceHandler
from taskmaster.utils.logger import TaskmasterLogger, logger


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """Parse command line flags."""
    parser = argparse.ArgumentParser(
        prog="taskmaster",
        description="Taskmaster - Job control daemon and supervisor (42 School)",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="taskmaster.yml",
        help="Path to YAML configuration file (default: taskmaster.yml)",
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
        default=None,
        help="Path to operational log file (default: logs/taskmaster.log)",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(args)


async def run_taskmaster(args: argparse.Namespace) -> int:
    """Initialize supervisor, attach signals, autostart services, and run CLI shell."""
    # 1. Setup logging
    log_file = args.logfile or "logs/taskmaster.log"
    TaskmasterLogger.setup(log_file=log_file, level=args.loglevel, console=False)
    logger.info(f"Taskmaster v{__version__} initializing (PID: {sys.platform})")

    # 2. Parse configuration
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        # Fallback to current directory taskmaster.yml if default
        print(f"Error: Configuration file '{args.config}' not found.", file=sys.stderr)
        return 1

    try:
        config = ConfigParser.load(str(config_path))
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        logger.error(f"Configuration load error: {exc}")
        return 1

    # 3. Instantiate supervisor handler
    handler = ServiceHandler(config)

    # 4. Attach OS signal handlers
    loop = asyncio.get_running_loop()

    def handle_sighup():
        logger.info("Received SIGHUP: scheduling configuration reload.")
        print("\n[taskmaster] SIGHUP received: reloading configuration...")
        asyncio.create_task(handler.reload())

    def handle_sigterm():
        logger.info("Received termination signal: initiating supervisor shutdown.")
        print("\n[taskmaster] Termination signal received: shutting down...")
        asyncio.create_task(handler.shutdown())

    try:
        loop.add_signal_handler(signal.SIGHUP, handle_sighup)
        loop.add_signal_handler(signal.SIGINT, handle_sigterm)
        loop.add_signal_handler(signal.SIGTERM, handle_sigterm)
    except NotImplementedError:
        # Signals might not be supported on non-unix platforms
        pass

    # 5. Autostart configured services
    await handler.autostart_all()

    # 6. Run foreground interactive control shell
    shell = ShellController(handler)
    try:
        await shell.run()
    finally:
        await handler.shutdown()

    return 0


def main() -> None:
    """CLI executable entry point."""
    args = parse_args()
    try:
        exit_code = asyncio.run(run_taskmaster(args))
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nExiting Taskmaster...")
        sys.exit(0)


if __name__ == "__main__":
    main()
