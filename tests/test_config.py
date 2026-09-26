"""Unit tests for Taskmaster configuration parsing and validation."""

import os
from pathlib import Path
import pytest
import signal
import tempfile

from taskmaster.config.models import AutoRestart, ProgramConfig, TaskmasterConfig, parse_signal, parse_umask
from taskmaster.config.parser import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigParser,
    ConfigValidationError,
)


def test_parse_signal():
    assert parse_signal("TERM") == signal.SIGTERM
    assert parse_signal("sigterm") == signal.SIGTERM
    assert parse_signal("INT") == signal.SIGINT
    assert parse_signal("HUP") == signal.SIGHUP
    assert parse_signal("QUIT") == signal.SIGQUIT
    assert parse_signal("USR1") == signal.SIGUSR1
    assert parse_signal(signal.SIGKILL) == signal.SIGKILL

    with pytest.raises(ValueError):
        parse_signal("NONEXISTENT_SIGNAL_XYZ")


def test_parse_umask():
    assert parse_umask("022") == 0o022
    assert parse_umask("077") == 0o077
    assert parse_umask("0o022") == 0o022
    assert parse_umask(0o022) == 0o022
    assert parse_umask(None) == 0o022


def test_autorestart_enum():
    assert AutoRestart.from_value("always") == AutoRestart.ALWAYS
    assert AutoRestart.from_value("never") == AutoRestart.NEVER
    assert AutoRestart.from_value("unexpected") == AutoRestart.UNEXPECTED
    assert AutoRestart.from_value(True) == AutoRestart.ALWAYS
    assert AutoRestart.from_value(False) == AutoRestart.NEVER

    with pytest.raises(ValueError):
        AutoRestart.from_value("sometimes")


def test_valid_programs_dict():
    yaml_content = """
    programs:
      nginx:
        cmd: "/usr/sbin/nginx -g 'daemon off;'"
        numprocs: 2
        autostart: true
        autorestart: unexpected
        exitcodes:
          - 0
          - 2
        starttime: 5
        startretries: 3
        stopsignal: TERM
        stoptime: 10
        stdout: /tmp/nginx.stdout
        stderr: /tmp/nginx.stderr
        workingdir: /tmp
        umask: "022"
        env:
          ENV: "production"
          PORT: "80"
    """
    config = ConfigParser.parse_dict(yaml.safe_load(yaml_content))
    assert "nginx" in config.programs
    p = config.programs["nginx"]
    assert p.name == "nginx"
    assert p.cmd == "/usr/sbin/nginx -g 'daemon off;'"
    assert p.numprocs == 2
    assert p.autostart is True
    assert p.autorestart == AutoRestart.UNEXPECTED
    assert p.exitcodes == [0, 2]
    assert p.starttime == 5
    assert p.startretries == 3
    assert p.stopsignal == signal.SIGTERM
    assert p.stoptime == 10
    assert p.stdout == "/tmp/nginx.stdout"
    assert p.stderr == "/tmp/nginx.stderr"
    assert p.workingdir == "/tmp"
    assert p.umask == 0o022
    assert p.env == {"ENV": "production", "PORT": "80"}


def test_valid_services_list():
    yaml_content = """
    services:
      - name: worker
        cmd: "python3 worker.py"
        numprocs: 1
        autostart: false
        autorestart: always
        exitcodes: 0
    """
    config = ConfigParser.parse_dict(yaml.safe_load(yaml_content))
    assert "worker" in config.programs
    p = config.programs["worker"]
    assert p.name == "worker"
    assert p.autostart is False
    assert p.autorestart == AutoRestart.ALWAYS
    assert p.exitcodes == [0]


def test_missing_cmd():
    yaml_content = """
    programs:
      bad_service:
        numprocs: 1
    """
    with pytest.raises(ConfigValidationError, match="missing required 'cmd'"):
        ConfigParser.parse_dict(yaml.safe_load(yaml_content))


def test_invalid_numprocs():
    yaml_content = """
    programs:
      bad_service:
        cmd: "sleep 10"
        numprocs: 0
    """
    with pytest.raises(ConfigValidationError, match="numprocs must be a positive integer"):
        ConfigParser.parse_dict(yaml.safe_load(yaml_content))


def test_duplicate_services():
    yaml_content = """
    services:
      - name: test
        cmd: "echo 1"
      - name: test
        cmd: "echo 2"
    """
    with pytest.raises(ConfigValidationError, match="Duplicate service name"):
        ConfigParser.parse_dict(yaml.safe_load(yaml_content))


def test_unknown_keys():
    yaml_content = """
    programs:
      bad_service:
        cmd: "sleep 10"
        random_unsupported_key: "value"
    """
    with pytest.raises(ConfigValidationError, match="unrecognized keys"):
        ConfigParser.parse_dict(yaml.safe_load(yaml_content))


def test_load_from_file():
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
        f.write("""
        programs:
          test_prog:
            cmd: "echo hello"
        """)
        f_path = f.name

    try:
        config = ConfigParser.load(f_path)
        assert "test_prog" in config.programs
        assert config.config_path == str(Path(f_path).resolve())
    finally:
        os.unlink(f_path)


def test_file_not_found():
    with pytest.raises(ConfigFileNotFoundError):
        ConfigParser.load("/nonexistent/file/path/taskmaster.yml")


import yaml
