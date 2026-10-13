# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from unittest.mock import MagicMock, create_autospec

import pytest
from ops.model import Container
from ops.pebble import ExecError

from cli import CommandLine
from exceptions import MigrationCheckError, MigrationError

DSN = "postgres://user:pass@host/db"
# The charm's own flags of a management command, without a token.
GRPC_FLAGS = ["--grpc-endpoint=localhost:50051", "--token=no-token"]


@pytest.fixture
def mocked_container() -> MagicMock:
    return create_autospec(Container)


@pytest.fixture
def cli(mocked_container: MagicMock) -> CommandLine:
    return CommandLine(mocked_container)


class TestMigrateUp:
    @pytest.mark.parametrize(
        "stderr, reason",
        [
            ("boom:\n\tlock timeout\n", "boom: lock timeout"),
            ("", "exit code 1, nothing on stderr"),
        ],
    )
    def test_failure(
        self, cli: CommandLine, mocked_container: MagicMock, stderr: str, reason: str
    ) -> None:
        """The error is the reason on one line: a status message shows it."""
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "migrate", "up"], 1, "", stderr
        )
        mocked_container.exec.return_value = process

        with pytest.raises(MigrationError, match=f"^{reason}$"):
            cli.migrate_up(dsn=DSN)

    def test_dsn_is_not_logged(
        self, cli: CommandLine, mocked_container: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        command = ["sso-service", "migrate", "up", "--dsn", DSN, "-f", "json"]
        process = MagicMock()
        process.wait_output.side_effect = ExecError(command, 1, "", "lock timeout")
        mocked_container.exec.return_value = process

        with caplog.at_level(logging.DEBUG), pytest.raises(MigrationError):
            cli.migrate_up(dsn=DSN)

        assert mocked_container.exec.call_args.args[0] == command
        assert "pass" not in caplog.text


class TestMigrationCheck:
    def test_stderr(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ("", "warning:\n\tcannot connect\n")
        mocked_container.exec.return_value = process

        with pytest.raises(
            MigrationCheckError, match="^Migration check error: warning: cannot connect$"
        ):
            cli.migration_check(dsn=DSN)


class TestConnectionCommands:
    @pytest.mark.parametrize(
        "kwargs, arguments",
        [
            ({}, ["--"]),
            (
                {"tenant_id": "t", "page_size": 5, "page_token": "next"},
                ["--page-size=5", "--page-token=next", "--", "t"],
            ),
        ],
    )
    def test_list_connections(
        self,
        cli: CommandLine,
        mocked_container: MagicMock,
        kwargs: dict,
        arguments: list[str],
    ) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"connections": []}', "")
        mocked_container.exec.return_value = process

        result = cli.list_connections(**kwargs)

        assert result == '{"connections": []}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "list", *GRPC_FLAGS]
        assert command[5:] == arguments

    def test_get_connection(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"connection": {}}', "")
        mocked_container.exec.return_value = process

        result = cli.get_connection(tenant_id="t", connection_id="c")

        assert result == '{"connection": {}}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "get", *GRPC_FLAGS]
        assert command[5:] == ["--", "t", "c"]

    def test_create_connection(
        self, cli: CommandLine, mocked_container: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"connection": {}}', "")
        mocked_container.exec.return_value = process

        with caplog.at_level(logging.DEBUG):
            result = cli.create_connection(
                tenant_id="t",
                label="Okta",
                issuer="https://idp.example.com",
                client_id="portal",
                client_secret="idp-secret",
                token="the-token",
            )

        assert result == '{"connection": {}}'
        # The charm's own flags first, and the tenant after `--`.
        assert mocked_container.exec.call_args.args[0] == [
            "sso-service",
            "connection",
            "create",
            "--grpc-endpoint=localhost:50051",
            "--token=the-token",
            "--label=Okta",
            "--issuer=https://idp.example.com",
            "--client-id=portal",
            "--",
            "t",
        ]
        # The identity provider's secret is not an argument.
        environment = mocked_container.exec.call_args.kwargs["environment"]
        assert environment == {"CLIENT_SECRET": "idp-secret"}
        assert "the-token" not in caplog.text and "idp-secret" not in caplog.text

    @pytest.mark.parametrize(
        "kwargs, arguments, environment",
        [
            ({}, ["--", "t", "c"], {}),
            ({"label": "Okta"}, ["--label=Okta", "--", "t", "c"], {}),
            pytest.param(
                {"client_secret": "idp-secret"},
                ["--", "t", "c"],
                {"CLIENT_SECRET": "idp-secret"},
                id="the client secret is not an argument",
            ),
        ],
    )
    def test_update_connection(
        self,
        cli: CommandLine,
        mocked_container: MagicMock,
        kwargs: dict,
        arguments: list[str],
        environment: dict,
    ) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"connection": {}}', "")
        mocked_container.exec.return_value = process

        result = cli.update_connection(tenant_id="t", connection_id="c", **kwargs)

        assert result == '{"connection": {}}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "update", *GRPC_FLAGS]
        assert command[5:] == arguments
        assert mocked_container.exec.call_args.kwargs["environment"] == environment

    def test_delete_connection(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ("{}", "")
        mocked_container.exec.return_value = process

        result = cli.delete_connection(connection_id="c")

        assert result == "{}"
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "delete", *GRPC_FLAGS]
        assert command[5:] == ["--", "c"]

    def test_test_connection(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"url": "https://login.example.com"}', "")
        mocked_container.exec.return_value = process

        result = cli.test_connection(tenant_id="t", connection_id="c")

        assert result == '{"url": "https://login.example.com"}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "test", *GRPC_FLAGS]
        assert command[5:] == ["--", "t", "c"]

    def test_value_starting_with_a_dash_is_not_a_flag(
        self, cli: CommandLine, mocked_container: MagicMock
    ) -> None:
        """It stays the value of its flag, or a positional after `--`."""
        process = MagicMock()
        process.wait_output.return_value = ("{}", "")
        mocked_container.exec.return_value = process

        cli.update_connection(
            tenant_id="--grpc-endpoint=other:1", connection_id="--", label="--token=other"
        )

        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "connection", "update", *GRPC_FLAGS]
        assert command[5:] == ["--label=--token=other", "--", "--grpc-endpoint=other:1", "--"]

    def test_list_connections_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "list"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.list_connections()

    def test_get_connection_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "get"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.get_connection(tenant_id="t", connection_id="c")

    def test_create_connection_failure(
        self, cli: CommandLine, mocked_container: MagicMock
    ) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "create"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.create_connection(
                tenant_id="t", label="Okta", issuer="https://idp.example.com", client_id="portal"
            )

    def test_update_connection_failure(
        self, cli: CommandLine, mocked_container: MagicMock
    ) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "update"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.update_connection(tenant_id="t", connection_id="c")

    def test_delete_connection_failure(
        self, cli: CommandLine, mocked_container: MagicMock
    ) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "delete"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.delete_connection(connection_id="c")

    def test_test_connection_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "connection", "test"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.test_connection(tenant_id="t", connection_id="c")


class TestPolicyCommands:
    def test_get_policy(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"policy": {}}', "")
        mocked_container.exec.return_value = process

        result = cli.get_policy(tenant_id="t")

        assert result == '{"policy": {}}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "policy", "get", *GRPC_FLAGS]
        assert command[5:] == ["--", "t"]

    @pytest.mark.parametrize(
        "kwargs, arguments",
        [
            ({"enforcement": "optional"}, ["--enforcement=optional", "--", "t"]),
            pytest.param({"enforcement": ""}, ["--", "t"], id="an empty value is left out"),
            (
                {"enforcement": "required", "bindings": "a, b:inactive", "auto_join": True},
                [
                    "--enforcement=required",
                    "--binding=a",
                    "--binding=b:inactive",
                    "--auto-join",
                    "--",
                    "t",
                ],
            ),
        ],
    )
    def test_set_policy(
        self,
        cli: CommandLine,
        mocked_container: MagicMock,
        kwargs: dict,
        arguments: list[str],
    ) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"policy": {}}', "")
        mocked_container.exec.return_value = process

        result = cli.set_policy(tenant_id="t", **kwargs)

        assert result == '{"policy": {}}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "policy", "set", *GRPC_FLAGS]
        assert command[5:] == arguments

    def test_get_policy_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "policy", "get"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.get_policy(tenant_id="t")

    def test_set_policy_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "policy", "set"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.set_policy(tenant_id="t", enforcement="optional")


class TestDomainsCommands:
    def test_get_domains(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"domains": []}', "")
        mocked_container.exec.return_value = process

        result = cli.get_domains(tenant_id="t")

        assert result == '{"domains": []}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "domains", "get", *GRPC_FLAGS]
        assert command[5:] == ["--", "t"]

    @pytest.mark.parametrize(
        "kwargs, arguments",
        [
            ({}, ["--", "t"]),
            ({"domains": "acme.example,acme.test"}, ["--", "t", "acme.example", "acme.test"]),
        ],
    )
    def test_set_domains(
        self,
        cli: CommandLine,
        mocked_container: MagicMock,
        kwargs: dict,
        arguments: list[str],
    ) -> None:
        process = MagicMock()
        process.wait_output.return_value = ('{"domains": []}', "")
        mocked_container.exec.return_value = process

        result = cli.set_domains(tenant_id="t", **kwargs)

        assert result == '{"domains": []}'
        command = mocked_container.exec.call_args.args[0]
        assert command[:5] == ["sso-service", "domains", "set", *GRPC_FLAGS]
        assert command[5:] == arguments

    def test_get_domains_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "domains", "get"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.get_domains(tenant_id="t")

    def test_set_domains_failure(self, cli: CommandLine, mocked_container: MagicMock) -> None:
        process = MagicMock()
        process.wait_output.side_effect = ExecError(
            ["sso-service", "domains", "set"], 1, "", "error"
        )
        mocked_container.exec.return_value = process

        with pytest.raises(ExecError):
            cli.set_domains(tenant_id="t")
