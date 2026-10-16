# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
import yaml
from ops import testing
from ops.pebble import ExecError
from unit.conftest import KEY_A, create_state, envelope_key_secret

from constants import WORKLOAD_CONTAINER

TENANT = "tenant-1"
CONNECTION = "connection-1"
MANAGEMENT_ACTIONS = [
    "list-connections",
    "get-connection",
    "create-connection",
    "update-connection",
    "delete-connection",
    "test-connection",
    "get-policy",
    "set-policy",
    "get-domains",
    "set-domains",
]


@pytest.fixture
def idp_secret() -> testing.Secret:
    """A client secret as `juju add-secret <name> client-secret#file=<path>` stores it."""
    return testing.Secret(tracked_content={"client-secret": "idp-secret\n"})


class TestRunMigrationAction:
    def test_runs_the_migration(
        self, context: testing.Context, all_relations: list, client_secrets: list
    ) -> None:
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        context.run(context.on.action("run-migration", params={"timeout": 60}), state)

        (migrate,) = [
            e
            for e in context.exec_history[WORKLOAD_CONTAINER]
            if e.command[:3] == ["sso-service", "migrate", "up"]
        ]
        assert migrate.timeout == 60

    def test_needs_the_database(self, context: testing.Context) -> None:
        with pytest.raises(testing.ActionFailed, match="The database is not ready"):
            context.run(context.on.action("run-migration"), create_state())


class TestGetEnvelopeKeyAction:
    def test_get_envelope_key(self, context: testing.Context) -> None:
        state = create_state(secrets=[envelope_key_secret()])

        context.run(context.on.action("get-envelope-key"), state)

        assert context.action_results == {"key": KEY_A}

    def test_fails_without_a_key(self, context: testing.Context) -> None:
        with pytest.raises(testing.ActionFailed, match="not ready"):
            context.run(context.on.action("get-envelope-key"), create_state())


class TestManagementToken:
    def test_token_of_the_service_client(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
        mocked_requests: MagicMock,
        oauth_relation: testing.Relation,
        oauth_client_secret: testing.Secret,
    ) -> None:
        """The commands call the API as the service's own client, through the workload's proxy."""
        mock_client = mocked_requests.return_value.__enter__.return_value
        mock_client.get_access_token.return_value = "the-token"
        state = create_state(
            relations=[oauth_relation],
            secrets=[oauth_client_secret],
            config={"https_proxy": "http://proxy:3128", "no_proxy": "svc.cluster.local"},
        )

        context.run(context.on.action("get-policy", params={"tenant-id": TENANT}), state)

        mocked_requests.assert_called_once_with(
            token_url="https://login.example.com/oauth2/token",
            http_proxy="",
            https_proxy="http://proxy:3128",
            no_proxy="svc.cluster.local",
        )
        mock_client.get_access_token.assert_called_once_with(
            client_id="sso-service-client", client_secret="service-client-secret"
        )
        mocked_cli.return_value.get_policy.assert_called_once_with(
            tenant_id=TENANT, token="the-token"
        )

    def test_no_token_when_the_exchange_fails(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
        mocked_requests: MagicMock,
        oauth_relation: testing.Relation,
        oauth_client_secret: testing.Secret,
    ) -> None:
        mock_client = mocked_requests.return_value.__enter__.return_value
        mock_client.get_access_token.side_effect = requests.ConnectionError("refused")
        state = create_state(relations=[oauth_relation], secrets=[oauth_client_secret])

        context.run(context.on.action("get-policy", params={"tenant-id": TENANT}), state)

        mocked_cli.return_value.get_policy.assert_called_once_with(tenant_id=TENANT, token=None)


class TestManagementActionSchemas:
    def test_undefined_parameters_are_refused(self) -> None:
        """Juju before 4.0 accepts them otherwise: a misspelt `domains` removes every domain."""
        charmcraft = yaml.safe_load((Path(__file__).parents[2] / "charmcraft.yaml").read_text())
        accepting = [
            name
            for name in MANAGEMENT_ACTIONS
            if charmcraft["actions"][name].get("additionalProperties") is not False
        ]
        assert not accepting


class TestListConnectionsAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.list_connections.return_value = '{"connections": []}'
        state = create_state()
        params = {"tenant-id": TENANT, "page-size": 5, "page-token": "next"}
        context.run(context.on.action("list-connections", params=params), state)
        mocked_cli.return_value.list_connections.assert_called_once_with(
            tenant_id=TENANT, page_size=5, page_token="next", token=None
        )
        assert context.action_results == {"output": '{"connections": []}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.list_connections.side_effect = Exception("fail")
        state = create_state()
        with pytest.raises(testing.ActionFailed, match="Failed to list connections"):
            context.run(context.on.action("list-connections"), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("list-connections"), state)


class TestGetConnectionAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.get_connection.return_value = '{"connection": {}}'
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        context.run(context.on.action("get-connection", params=params), state)
        mocked_cli.return_value.get_connection.assert_called_once_with(
            tenant_id=TENANT, connection_id=CONNECTION, token=None
        )
        assert context.action_results == {"output": '{"connection": {}}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.get_connection.side_effect = Exception("fail")
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Failed to get connection"):
            context.run(context.on.action("get-connection", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("get-connection", params=params), state)


class TestCreateConnectionAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
        idp_secret: testing.Secret,
    ) -> None:
        mocked_cli.return_value.create_connection.return_value = '{"connection": {}}'
        state = create_state(secrets=[idp_secret])
        params = {
            "tenant-id": TENANT,
            "label": "Okta",
            "issuer": "https://idp.example.com",
            "client-id": "portal",
            "client-secret-id": idp_secret.id,
        }
        context.run(context.on.action("create-connection", params=params), state)
        mocked_cli.return_value.create_connection.assert_called_once_with(
            tenant_id=TENANT,
            label="Okta",
            issuer="https://idp.example.com",
            client_id="portal",
            client_secret="idp-secret",
            token=None,
        )
        assert context.action_results == {"output": '{"connection": {}}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
        idp_secret: testing.Secret,
    ) -> None:
        mocked_cli.return_value.create_connection.side_effect = Exception("fail")
        state = create_state(secrets=[idp_secret])
        params = {
            "tenant-id": TENANT,
            "label": "Okta",
            "issuer": "https://idp.example.com",
            "client-id": "portal",
            "client-secret-id": idp_secret.id,
        }
        with pytest.raises(testing.ActionFailed, match="Failed to create connection"):
            context.run(context.on.action("create-connection", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
        idp_secret: testing.Secret,
    ) -> None:
        state = create_state(can_connect=False)
        params = {
            "tenant-id": TENANT,
            "label": "Okta",
            "issuer": "https://idp.example.com",
            "client-id": "portal",
            "client-secret-id": idp_secret.id,
        }
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("create-connection", params=params), state)


class TestUpdateConnectionAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.update_connection.return_value = '{"connection": {}}'
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION, "label": "Okta"}
        context.run(context.on.action("update-connection", params=params), state)
        mocked_cli.return_value.update_connection.assert_called_once_with(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            label="Okta",
            client_secret=None,
            token=None,
        )
        assert context.action_results == {"output": '{"connection": {}}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.update_connection.side_effect = Exception("fail")
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION, "label": "Okta"}
        with pytest.raises(testing.ActionFailed, match="Failed to update connection"):
            context.run(context.on.action("update-connection", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {"tenant-id": TENANT, "connection-id": CONNECTION, "label": "Okta"}
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("update-connection", params=params), state)

    @pytest.mark.parametrize(
        "content, reason",
        [
            pytest.param(None, "grant it to this application", id="not granted"),
            pytest.param({"other": "value"}, "has no `client-secret` entry", id="no entry"),
        ],
    )
    def test_unusable_secret(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
        content: dict | None,
        reason: str,
    ) -> None:
        secret = testing.Secret(tracked_content=content or {"client-secret": "idp-secret"})
        state = create_state(secrets=[secret] if content else [])
        params = {"tenant-id": TENANT, "connection-id": CONNECTION, "client-secret-id": secret.id}
        with pytest.raises(testing.ActionFailed, match=reason):
            context.run(context.on.action("update-connection", params=params), state)
        mocked_cli.return_value.update_connection.assert_not_called()

    def test_latest_revision_of_the_secret(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        """A secret changed since the charm last read it is sent with its new value."""
        secret = testing.Secret(
            tracked_content={"client-secret": "old-secret"},
            latest_content={"client-secret": "new-secret"},
        )
        state = create_state(secrets=[secret])
        params = {"tenant-id": TENANT, "connection-id": CONNECTION, "client-secret-id": secret.id}
        context.run(context.on.action("update-connection", params=params), state)
        sent = mocked_cli.return_value.update_connection.call_args.kwargs
        assert sent["client_secret"] == "new-secret"


class TestDeleteConnectionAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.delete_connection.return_value = "{}"
        state = create_state()
        params = {"connection-id": CONNECTION}
        context.run(context.on.action("delete-connection", params=params), state)
        mocked_cli.return_value.delete_connection.assert_called_once_with(
            connection_id=CONNECTION, token=None
        )
        assert context.action_results == {"output": "{}"}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.delete_connection.side_effect = Exception("fail")
        state = create_state()
        params = {"connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Failed to delete connection"):
            context.run(context.on.action("delete-connection", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {"connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("delete-connection", params=params), state)


class TestTestConnectionAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.test_connection.return_value = (
            '{"url": "https://login.example.com/sso/..."}'
        )
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        context.run(context.on.action("test-connection", params=params), state)
        mocked_cli.return_value.test_connection.assert_called_once_with(
            tenant_id=TENANT, connection_id=CONNECTION, token=None
        )
        assert context.action_results == {"output": '{"url": "https://login.example.com/sso/..."}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.test_connection.side_effect = Exception("fail")
        state = create_state()
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Failed to test connection"):
            context.run(context.on.action("test-connection", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {"tenant-id": TENANT, "connection-id": CONNECTION}
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("test-connection", params=params), state)


class TestGetPolicyAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.get_policy.return_value = '{"policy": {}}'
        state = create_state()
        context.run(context.on.action("get-policy", params={"tenant-id": TENANT}), state)
        mocked_cli.return_value.get_policy.assert_called_once_with(tenant_id=TENANT, token=None)
        assert context.action_results == {"output": '{"policy": {}}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        """The message carries no argument of the command: the token is one."""
        mocked_cli.return_value.get_policy.side_effect = ExecError(
            ["sso-service", "policy", "get", "--token=the-token", "--", TENANT], 1, "", "refused"
        )
        state = create_state()
        with pytest.raises(testing.ActionFailed, match="Failed to get policy") as failure:
            context.run(context.on.action("get-policy", params={"tenant-id": TENANT}), state)
        assert "the-token" not in failure.value.message

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("get-policy", params={"tenant-id": TENANT}), state)


class TestSetPolicyAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.set_policy.return_value = '{"policy": {}}'
        state = create_state()
        params = {
            "tenant-id": TENANT,
            "enforcement": "required",
            "bindings": "a,b:inactive",
            "auto-join": True,
        }
        context.run(context.on.action("set-policy", params=params), state)
        mocked_cli.return_value.set_policy.assert_called_once_with(
            tenant_id=TENANT,
            enforcement="required",
            bindings="a,b:inactive",
            auto_join=True,
            token=None,
        )
        assert context.action_results == {"output": '{"policy": {}}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.set_policy.side_effect = Exception("fail")
        state = create_state()
        params = {
            "tenant-id": TENANT,
            "enforcement": "required",
            "bindings": "a,b:inactive",
            "auto-join": True,
        }
        with pytest.raises(testing.ActionFailed, match="Failed to set policy"):
            context.run(context.on.action("set-policy", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {
            "tenant-id": TENANT,
            "enforcement": "required",
            "bindings": "a,b:inactive",
            "auto-join": True,
        }
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("set-policy", params=params), state)


class TestGetDomainsAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.get_domains.return_value = '{"domains": []}'
        state = create_state()
        context.run(context.on.action("get-domains", params={"tenant-id": TENANT}), state)
        mocked_cli.return_value.get_domains.assert_called_once_with(tenant_id=TENANT, token=None)
        assert context.action_results == {"output": '{"domains": []}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.get_domains.side_effect = Exception("fail")
        state = create_state()
        with pytest.raises(testing.ActionFailed, match="Failed to get domains"):
            context.run(context.on.action("get-domains", params={"tenant-id": TENANT}), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("get-domains", params={"tenant-id": TENANT}), state)


class TestSetDomainsAction:
    def test_success(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.set_domains.return_value = '{"domains": []}'
        state = create_state()
        params = {"tenant-id": TENANT, "domains": "acme.example,acme.test"}
        context.run(context.on.action("set-domains", params=params), state)
        mocked_cli.return_value.set_domains.assert_called_once_with(
            tenant_id=TENANT, domains="acme.example,acme.test", token=None
        )
        assert context.action_results == {"output": '{"domains": []}'}

    def test_failure(
        self,
        context: testing.Context,
        mocked_cli: MagicMock,
    ) -> None:
        mocked_cli.return_value.set_domains.side_effect = Exception("fail")
        state = create_state()
        params = {"tenant-id": TENANT, "domains": "acme.example,acme.test"}
        with pytest.raises(testing.ActionFailed, match="Failed to set domains"):
            context.run(context.on.action("set-domains", params=params), state)

    def test_container_not_ready(
        self,
        context: testing.Context,
    ) -> None:
        state = create_state(can_connect=False)
        params = {"tenant-id": TENANT, "domains": "acme.example,acme.test"}
        with pytest.raises(testing.ActionFailed, match="Workload container is not ready"):
            context.run(context.on.action("set-domains", params=params), state)
