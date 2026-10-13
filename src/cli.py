# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to access the sso-service CLI."""

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from ops.model import Container
from ops.pebble import Error, ExecError

from constants import GRPC_PORT
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

    # The management commands are `<group> <verb> <the charm's flags> <the action's
    # flags> -- <positionals>`, a flag's value joined to its name with `=`: nothing
    # an operator types is read as a flag. A flag with an empty value is left out.

    def list_connections(
        self,
        tenant_id: str | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        token: str | None = None,
    ) -> str:
        """List a tenant's SSO connections, or every tenant's.

        Args:
            tenant_id: The tenant ID. Every tenant's connections are listed without it.
            page_size: Maximum number of results per page.
            page_token: Token to retrieve the next page of results.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "list"]
        cmd.extend(self._grpc_flags(token))
        if page_size is not None:
            cmd.append(f"--page-size={page_size}")
        if page_token:
            cmd.append(f"--page-token={page_token}")
        cmd.append("--")
        if tenant_id:
            cmd.append(tenant_id)
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def get_connection(self, tenant_id: str, connection_id: str, token: str | None = None) -> str:
        """Get an SSO connection.

        Args:
            tenant_id: The tenant ID.
            connection_id: The connection ID.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "get"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", tenant_id, connection_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def create_connection(
        self,
        tenant_id: str,
        label: str,
        issuer: str,
        client_id: str,
        client_secret: str | None = None,
        token: str | None = None,
    ) -> str:
        """Create an SSO connection.

        Args:
            tenant_id: The tenant ID.
            label: The name the sign-in button shows.
            issuer: The identity provider's OIDC issuer URL.
            client_id: The client ID at the identity provider.
            client_secret: The client secret at the identity provider. It is
                passed in the environment, not as an argument.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "create"]
        cmd.extend(self._grpc_flags(token))
        if label:
            cmd.append(f"--label={label}")
        if issuer:
            cmd.append(f"--issuer={issuer}")
        if client_id:
            cmd.append(f"--client-id={client_id}")
        cmd.extend(["--", tenant_id])
        environment = {"CLIENT_SECRET": client_secret} if client_secret else {}
        stdout, _ = self._run_cmd(cmd, exec_config=CmdExecConfig(environment=environment))
        return stdout

    def update_connection(
        self,
        tenant_id: str,
        connection_id: str,
        label: str | None = None,
        client_secret: str | None = None,
        token: str | None = None,
    ) -> str:
        """Update an SSO connection's label or client secret.

        Args:
            tenant_id: The tenant ID.
            connection_id: The connection ID.
            label: The new name for the sign-in button.
            client_secret: The new client secret at the identity provider. It
                is passed in the environment, not as an argument.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "update"]
        cmd.extend(self._grpc_flags(token))
        if label:
            cmd.append(f"--label={label}")
        cmd.extend(["--", tenant_id, connection_id])
        environment = {"CLIENT_SECRET": client_secret} if client_secret else {}
        stdout, _ = self._run_cmd(cmd, exec_config=CmdExecConfig(environment=environment))
        return stdout

    def delete_connection(self, connection_id: str, token: str | None = None) -> str:
        """Delete an SSO connection, whichever tenant owns it.

        Args:
            connection_id: The connection ID.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "delete"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", connection_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def test_connection(self, tenant_id: str, connection_id: str, token: str | None = None) -> str:
        """Start a test sign-in through an SSO connection.

        Args:
            tenant_id: The tenant ID.
            connection_id: The connection ID.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "connection", "test"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", tenant_id, connection_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def get_policy(self, tenant_id: str, token: str | None = None) -> str:
        """Get a tenant's SSO policy.

        Args:
            tenant_id: The tenant ID.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "policy", "get"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", tenant_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def set_policy(
        self,
        tenant_id: str,
        enforcement: str,
        bindings: str | None = None,
        auto_join: bool = False,
        token: str | None = None,
    ) -> str:
        """Replace a tenant's SSO policy.

        Args:
            tenant_id: The tenant ID.
            enforcement: Whether SSO sign-in is optional or required.
            bindings: The tenant's connections, comma or space separated.
            auto_join: Whether addresses in the tenant's domains are admitted
                at their first SSO sign-in.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "policy", "set"]
        cmd.extend(self._grpc_flags(token))
        if enforcement:
            cmd.append(f"--enforcement={enforcement}")
        for binding in (bindings or "").replace(",", " ").split():
            cmd.append(f"--binding={binding}")
        if auto_join:
            cmd.append("--auto-join")
        cmd.extend(["--", tenant_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def get_domains(self, tenant_id: str, token: str | None = None) -> str:
        """Get the email domains a tenant's SSO sign-in applies to.

        Args:
            tenant_id: The tenant ID.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "domains", "get"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", tenant_id])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def set_domains(
        self, tenant_id: str, domains: str | None = None, token: str | None = None
    ) -> str:
        """Replace the email domains a tenant's SSO sign-in applies to.

        Args:
            tenant_id: The tenant ID.
            domains: The domains, comma or space separated. None removes them all.
            token: Optional authentication token.

        Returns:
            The command output.
        """
        cmd = ["sso-service", "domains", "set"]
        cmd.extend(self._grpc_flags(token))
        cmd.extend(["--", tenant_id, *(domains or "").replace(",", " ").split()])
        stdout, _ = self._run_cmd(cmd)
        return stdout

    def _grpc_flags(self, token: str | None = None) -> list[str]:
        """Build common gRPC flags for the management commands.

        Args:
            token: Optional authentication token. When None a placeholder is
                used, which the service refuses.

        Returns:
            A list of CLI flags.
        """
        flags = [f"--grpc-endpoint=localhost:{GRPC_PORT}"]
        flags.append(f"--token={token or 'no-token'}")
        return flags

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
        # Not the arguments: they carry the database password or the management token.
        logger.debug("Running command: %s", cmd[:3])
        process = self.container.exec(cmd, **asdict(exec_config))
        try:
            stdout, stderr = process.wait_output()
        except ExecError as err:
            logger.error("Exited with code: %d. Error: %s", err.exit_code, err.stderr)
            raise
        return stdout, stderr
