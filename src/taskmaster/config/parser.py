"""YAML Configuration parser and validator for Taskmaster."""

import os
from pathlib import Path
import re
import shlex
from typing import Any, Dict, List, Optional
import yaml

from .models import (
    AutoRestart,
    ProgramConfig,
    TaskmasterConfig,
    parse_signal,
    parse_umask,
)


class ConfigError(Exception):
    """Base exception for configuration errors."""
    pass


class ConfigFileNotFoundError(ConfigError):
    """Raised when configuration file cannot be found."""
    pass


class ConfigValidationError(ConfigError):
    """Raised when configuration content fails schema or value validation."""
    pass


class ConfigParser:
    """Parses and validates Taskmaster YAML configuration files."""

    ALLOWED_PROGRAM_KEYS = {
        "cmd",
        "command",
        "numprocs",
        "autostart",
        "autorestart",
        "exitcodes",
        "starttime",
        "startretries",
        "stopsignal",
        "stoptime",
        "stdout",
        "stderr",
        "env",
        "environment",
        "workingdir",
        "directory",
        "umask",
        "user",
        "name",  # Used if defined inside list items
    }

    @classmethod
    def load(cls, file_path: str | Path) -> TaskmasterConfig:
        """Load and parse configuration from a file path."""
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise ConfigFileNotFoundError(f"Configuration file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigValidationError(f"YAML syntax error in '{path}': {exc}") from exc
        except Exception as exc:
            raise ConfigError(f"Failed to read '{path}': {exc}") from exc

        return cls.parse_dict(content, config_path=str(path))

    @classmethod
    def parse_dict(cls, data: Any, config_path: Optional[str] = None) -> TaskmasterConfig:
        """Parse raw dictionary data into a validated TaskmasterConfig."""
        if not isinstance(data, dict):
            raise ConfigValidationError(
                f"Configuration root must be a YAML mapping/dictionary, got {type(data).__name__}"
            )

        programs_dict: Dict[str, ProgramConfig] = {}

        # 1. Check for standard 'programs:' mapping
        if "programs" in data:
            raw_programs = data["programs"]
            if not isinstance(raw_programs, dict):
                raise ConfigValidationError("'programs' section must be a dictionary of program names")
            for prog_name, raw_cfg in raw_programs.items():
                if not isinstance(raw_cfg, dict):
                    raise ConfigValidationError(f"Configuration for program '{prog_name}' must be a dictionary")
                program = cls._parse_program(prog_name, raw_cfg)
                programs_dict[program.name] = program

        # 2. Check for alternative 'services:' list (as used in reference repo)
        elif "services" in data:
            raw_services = data["services"]
            if not isinstance(raw_services, list):
                raise ConfigValidationError("'services' section must be a list of service definitions")
            for idx, raw_cfg in enumerate(raw_services):
                if not isinstance(raw_cfg, dict):
                    raise ConfigValidationError(f"Service at index {idx} must be a dictionary")
                name = raw_cfg.get("name")
                if not name:
                    raise ConfigValidationError(f"Service at index {idx} is missing required 'name' field")
                if name in programs_dict:
                    raise ConfigValidationError(f"Duplicate service name '{name}' detected")
                program = cls._parse_program(name, raw_cfg)
                programs_dict[program.name] = program

        else:
            raise ConfigValidationError(
                "Configuration must define either a 'programs' dictionary or a 'services' list"
            )

        if not programs_dict:
            raise ConfigValidationError("Configuration must contain at least one program definition")

        # Global taskmaster options (optional)
        socket_path = data.get("socket_path", "/tmp/taskmaster.sock")
        log_file = data.get("log_file", "logs/taskmaster.log")
        log_level = data.get("log_level", "INFO").upper()

        return TaskmasterConfig(
            programs=programs_dict,
            config_path=config_path,
            socket_path=socket_path,
            log_file=log_file,
            log_level=log_level,
        )

    @classmethod
    def _parse_program(cls, name: str, cfg: Dict[str, Any]) -> ProgramConfig:
        """Validate and construct a ProgramConfig object."""
        # Validate program name
        name_str = str(name).strip()
        if not name_str:
            raise ConfigValidationError("Program name cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_-]+$", name_str):
            raise ConfigValidationError(
                f"Invalid program name '{name_str}'. Allowed characters: letters, numbers, underscores, hyphens"
            )

        # Check for unknown keys (warning or error)
        unknown_keys = set(cfg.keys()) - cls.ALLOWED_PROGRAM_KEYS
        if unknown_keys:
            raise ConfigValidationError(
                f"Program '{name_str}' contains unrecognized keys: {', '.join(sorted(unknown_keys))}"
            )

        # Command is required
        cmd = cfg.get("cmd") or cfg.get("command")
        if not cmd or not str(cmd).strip():
            raise ConfigValidationError(f"Program '{name_str}' is missing required 'cmd' parameter")
        cmd_str = str(cmd).strip()
        try:
            # Verify command can be tokenized
            shlex.split(cmd_str)
        except ValueError as exc:
            raise ConfigValidationError(f"Program '{name_str}' has invalid cmd syntax: {exc}")

        # numprocs
        numprocs = cfg.get("numprocs", 1)
        if not isinstance(numprocs, int) or numprocs < 1:
            raise ConfigValidationError(f"Program '{name_str}' numprocs must be a positive integer >= 1 (got {numprocs})")
        if numprocs > 128:
            raise ConfigValidationError(f"Program '{name_str}' numprocs exceeds safe limit (max 128, got {numprocs})")

        # autostart
        autostart = cfg.get("autostart", True)
        if not isinstance(autostart, bool):
            raise ConfigValidationError(f"Program '{name_str}' autostart must be a boolean (got {autostart})")

        # autorestart
        autorestart_raw = cfg.get("autorestart", "unexpected")
        try:
            autorestart = AutoRestart.from_value(autorestart_raw)
        except ValueError as exc:
            raise ConfigValidationError(f"Program '{name_str}': {exc}")

        # exitcodes
        raw_exitcodes = cfg.get("exitcodes", [0])
        if isinstance(raw_exitcodes, int):
            exitcodes = [raw_exitcodes]
        elif isinstance(raw_exitcodes, list):
            exitcodes = []
            for code in raw_exitcodes:
                if not isinstance(code, int) or code < 0 or code > 255:
                    raise ConfigValidationError(
                        f"Program '{name_str}' exitcodes must be integers between 0 and 255 (got {code})"
                    )
                exitcodes.append(code)
        else:
            raise ConfigValidationError(f"Program '{name_str}' exitcodes must be a list of integers")

        # starttime
        starttime = cfg.get("starttime", 1)
        if not isinstance(starttime, int) or starttime < 0:
            raise ConfigValidationError(f"Program '{name_str}' starttime must be an integer >= 0 (got {starttime})")

        # startretries
        startretries = cfg.get("startretries", 3)
        if not isinstance(startretries, int) or startretries < 0:
            raise ConfigValidationError(f"Program '{name_str}' startretries must be an integer >= 0 (got {startretries})")

        # stopsignal
        raw_stopsignal = cfg.get("stopsignal", "TERM")
        try:
            stopsignal = parse_signal(raw_stopsignal)
        except ValueError as exc:
            raise ConfigValidationError(f"Program '{name_str}': {exc}")

        # stoptime
        stoptime = cfg.get("stoptime", 10)
        if not isinstance(stoptime, int) or stoptime < 0:
            raise ConfigValidationError(f"Program '{name_str}' stoptime must be an integer >= 0 (got {stoptime})")

        # stdout / stderr
        stdout = cfg.get("stdout")
        if stdout is not None:
            stdout = str(stdout).strip()
            if stdout.upper() in ("DEVNULL", "DISCARD", "NONE", ""):
                stdout = None

        stderr = cfg.get("stderr")
        if stderr is not None:
            stderr = str(stderr).strip()
            if stderr.upper() in ("DEVNULL", "DISCARD", "NONE", ""):
                stderr = None

        # env
        raw_env = cfg.get("env") or cfg.get("environment") or {}
        if not isinstance(raw_env, dict):
            raise ConfigValidationError(f"Program '{name_str}' env must be a dictionary of key-value pairs")
        env = {str(k): str(v) for k, v in raw_env.items()}

        # workingdir
        workingdir = cfg.get("workingdir") or cfg.get("directory")
        if workingdir is not None:
            workingdir = str(workingdir).strip()

        # umask
        raw_umask = cfg.get("umask", 0o022)
        try:
            umask = parse_umask(raw_umask)
        except ValueError as exc:
            raise ConfigValidationError(f"Program '{name_str}': {exc}")

        # user
        user = cfg.get("user")
        if user is not None:
            user = str(user).strip()

        return ProgramConfig(
            name=name_str,
            cmd=cmd_str,
            numprocs=numprocs,
            autostart=autostart,
            autorestart=autorestart,
            exitcodes=exitcodes,
            starttime=starttime,
            startretries=startretries,
            stopsignal=stopsignal,
            stoptime=stoptime,
            stdout=stdout,
            stderr=stderr,
            env=env,
            workingdir=workingdir,
            umask=umask,
            user=user,
        )
