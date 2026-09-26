"""Data models and enums for Taskmaster configuration."""

from dataclasses import dataclass, field
from enum import Enum
import signal
from typing import Dict, List, Optional, Any


class AutoRestart(str, Enum):
    """Restart policy for supervised processes."""
    ALWAYS = "always"
    NEVER = "never"
    UNEXPECTED = "unexpected"

    @classmethod
    def from_value(cls, val: Any) -> "AutoRestart":
        if isinstance(val, bool):
            return cls.ALWAYS if val else cls.NEVER
        if isinstance(val, str):
            val_lower = val.strip().lower()
            if val_lower in ("always", "true"):
                return cls.ALWAYS
            if val_lower in ("never", "false"):
                return cls.NEVER
            if val_lower == "unexpected":
                return cls.UNEXPECTED
        raise ValueError(
            f"Invalid autorestart value: '{val}'. Expected 'always', 'never', or 'unexpected'."
        )


def parse_signal(sig_name: Any) -> signal.Signals:
    """Normalize and convert string signal representation to signal.Signals."""
    if isinstance(sig_name, signal.Signals):
        return sig_name
    if isinstance(sig_name, int):
        return signal.Signals(sig_name)

    name = str(sig_name).strip().upper()
    if name.startswith("SIG"):
        name = name[3:]

    # Map common aliases
    alias_map = {
        "TERM": signal.SIGTERM,
        "INT": signal.SIGINT,
        "QUIT": signal.SIGQUIT,
        "HUP": signal.SIGHUP,
        "KILL": signal.SIGKILL,
        "USR1": signal.SIGUSR1,
        "USR2": signal.SIGUSR2,
        "STOP": signal.SIGSTOP,
    }

    if name in alias_map:
        return alias_map[name]

    # Attempt to lookup on signal module
    attr = f"SIG{name}"
    if hasattr(signal, attr):
        return getattr(signal, attr)

    raise ValueError(f"Unknown or unsupported signal: '{sig_name}'")


def parse_umask(val: Any) -> int:
    """
    Parse umask value into an integer.
    Handles octal strings ("022"), numbers, or YAML octal ints.
    """
    if val is None:
        return 0o022

    if isinstance(val, int):
        # In YAML, 077 is parsed as octal in YAML 1.1 or decimal in YAML 1.2
        # If it was written as 022 decimal, it's 22. If octal string like "022", parse base 8.
        return val

    if isinstance(val, str):
        val = val.strip()
        if val.startswith("0o"):
            return int(val, 8)
        if val.startswith("0") and len(val) > 1:
            return int(val, 8)
        return int(val, 8)

    raise ValueError(f"Invalid umask format: '{val}'. Expected octal string or integer.")


@dataclass
class ProgramConfig:
    """Configuration for a supervised program."""
    name: str
    cmd: str
    numprocs: int = 1
    autostart: bool = True
    autorestart: AutoRestart = AutoRestart.UNEXPECTED
    exitcodes: List[int] = field(default_factory=lambda: [0])
    starttime: int = 1
    startretries: int = 3
    stopsignal: signal.Signals = signal.SIGTERM
    stoptime: int = 10
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    workingdir: Optional[str] = None
    umask: int = 0o022
    user: Optional[str] = None

    def runtime_parameters_equal(self, other: "ProgramConfig") -> bool:
        """
        Check if parameters requiring process recreation are equal.
        Monitoring parameters (e.g. startretries, exitcodes) don't require restarting.
        """
        return (
            self.cmd == other.cmd
            and self.stdout == other.stdout
            and self.stderr == other.stderr
            and self.env == other.env
            and self.workingdir == other.workingdir
            and self.umask == other.umask
            and self.user == other.user
        )


@dataclass
class TaskmasterConfig:
    """Root configuration holding all programs and global options."""
    programs: Dict[str, ProgramConfig] = field(default_factory=dict)
    config_path: Optional[str] = None
    socket_path: str = "/tmp/taskmaster.sock"
    log_file: str = "logs/taskmaster.log"
    log_level: str = "INFO"
