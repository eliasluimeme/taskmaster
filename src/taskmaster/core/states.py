"""Process states enum and transitions modeled after Supervisor."""

from enum import Enum


class ProcessState(str, Enum):
    """
    Supervisor process state model.
    Reference: http://supervisord.org/subprocess.html#process-states
    """
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    BACKOFF = "BACKOFF"
    STOPPING = "STOPPING"
    EXITED = "EXITED"
    FATAL = "FATAL"

    @property
    def is_active(self) -> bool:
        """Returns True if the process is currently executing or in transition."""
        return self in (ProcessState.STARTING, ProcessState.RUNNING, ProcessState.STOPPING)

    @property
    def can_start(self) -> bool:
        """Returns True if the process can be started."""
        return self in (ProcessState.STOPPED, ProcessState.EXITED, ProcessState.FATAL)

    @property
    def can_stop(self) -> bool:
        """Returns True if the process can be stopped."""
        return self in (ProcessState.STARTING, ProcessState.RUNNING)
