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
