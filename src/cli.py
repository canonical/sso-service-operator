# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to access the sso-service CLI."""

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from ops.model import Container
from ops.pebble import Error, ExecError

from env_vars import EnvVars
from exceptions import MigrationCheckError, MigrationError

VERSION_REGEX = re.compile(r"App Version:\s*(?P<version>\S+)\s*$")

logger = logging.getLogger(__name__)


def _reason(err: Error) -> str:
    """Get why a command failed, on one line, for a status message.

    Args:
        err: The error Pebble raised.

    Returns:
        What the command wrote to stderr, or Pebble's own error.
    """
    if not isinstance(err, ExecError):
        return str(err)
    stderr = " ".join(str(err.stderr or "").split())
    return stderr or f"exit code {err.exit_code}, nothing on stderr"


@dataclass
class CmdExecConfig:
    """Command Execution Config."""

    service_context: str | None = None
    environment: EnvVars = field(default_factory=dict)
    timeout: float = 20
    stdin: str | None = None


class CommandLine:
    """A class to handle command line interactions with the sso-service."""

    def __init__(self, container: Container):
        self.container = container

    def get_service_version(self) -> str | None:
        """Get the version of the sso-service workload.

        Returns:
            The version string, or None if it could not be determined.
        """
        cmd = ["sso-service", "version"]
        try:
            stdout, _ = self._run_cmd(cmd)
        except Error as err:
            logger.error("Failed to fetch the service version: %s", err)
            return None
        matched = VERSION_REGEX.search(stdout)
        return matched.group("version") if matched else None

    def migrate_up(self, dsn: str, timeout: float = 120) -> None:
        """Run database migrations.

        Args:
            dsn: The database connection string.
            timeout: The timeout for the migration command.

        Raises:
            MigrationError: If the migration fails.
        """
        cmd = ["sso-service", "migrate", "up", "--dsn", dsn, "-f", "json"]
        try:
            self._run_cmd(
                cmd,
                exec_config=CmdExecConfig(timeout=timeout),
            )
        except Error as err:
            logger.error("Failed to migrate up the service: %s", err)
            raise MigrationError(_reason(err)) from err

    def migration_check(self, dsn: str) -> bool:
        """Check if database migrations are up to date.

        Args:
            dsn: The database connection string.

        Returns:
            True if migrations are up to date.

        Raises:
            MigrationCheckError: If the migration check fails.
        """
        cmd = ["sso-service", "migrate", "check", "--dsn", dsn, "-f", "json"]
        try:
            stdout, stderr = self._run_cmd(cmd)
        except Error as err:
            logger.error("Failed to check migration status: %s", err)
            raise MigrationCheckError(_reason(err)) from err
        if stderr:
            # On one line: the error ends up in a status message.
            stderr = " ".join(stderr.split())
            logger.error("Migration check error: %s", stderr)
            raise MigrationCheckError(f"Migration check error: {stderr}")
        out = json.loads(stdout)
        return out.get("status") == "ok"

    def _run_cmd(
        self, cmd: list[str], exec_config: CmdExecConfig | None = None
    ) -> tuple[str, str]:
        """Run a command in the workload container.

        Args:
            cmd: The command to run.
            exec_config: Optional execution configuration.

        Returns:
            A tuple of (stdout, stderr).

        Raises:
            ExecError: If the command exits with a non-zero code.
        """
        if exec_config is None:
            exec_config = CmdExecConfig()
        # Not the arguments: a DSN carries the database password.
        logger.debug("Running command: %s", cmd[:3])
        process = self.container.exec(cmd, **asdict(exec_config))
        try:
            stdout, stderr = process.wait_output()
        except ExecError as err:
            logger.error("Exited with code: %d. Error: %s", err.exit_code, err.stderr)
            raise
        return stdout, stderr
