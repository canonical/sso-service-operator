# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from ops import testing
from ops.pebble import ConnectionError as PebbleConnectionError
from ops.pebble import Layer, ServiceStatus
from pytest_mock import MockerFixture
from unit.conftest import (
    KEY_A,
    create_state,
    envelope_key_secret,
    execs,
)

from constants import (
    ENVELOPE_KEY_SECRET_KEY,
    ENVELOPE_KEY_SECRET_LABEL,
    WORKLOAD_CONTAINER,
    WORKLOAD_SERVICE,
)


def pebble_ready(context: testing.Context, state: testing.State) -> testing.State:
    return context.run(context.on.pebble_ready(state.get_container(WORKLOAD_CONTAINER)), state)


def environment(state_out: testing.State) -> dict:
    layer = state_out.get_container(WORKLOAD_CONTAINER).layers[WORKLOAD_SERVICE]
    return layer.services[WORKLOAD_SERVICE].environment


def relation(state_out: testing.State, endpoint: str) -> testing.RelationBase:
    return next(r for r in state_out.relations if r.endpoint == endpoint)


def key_in(state_out: testing.State) -> str | None:
    """The key in the charm's envelope key secret, when the secret exists."""
    secret = next((s for s in state_out.secrets if s.label == ENVELOPE_KEY_SECRET_LABEL), None)
    return secret.latest_content[ENVELOPE_KEY_SECRET_KEY] if secret else None


class TestPebbleReadyEvent:
    def test_plans_the_service_with_every_input(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            config={"authn_allowed_subjects": " a , b,,c "},
        )

        state_out = pebble_ready(context, state)

        env = environment(state_out)
        assert env["PUBLIC_URL"] == "https://login.example.com/sso"
        assert env["DSN"] == (
            "postgres://relation-7:pg-password@"
            "postgresql-k8s-primary.model.svc.cluster.local:5432/test-model_sso-service"
        )
        assert env["HYDRA_SSO_ADMIN_URL"] == "http://hydra-sso.model.svc.cluster.local:4445"
        assert env["KRATOS_ADMIN_URL"] == "http://kratos.model.svc.cluster.local:4434"
        assert env["TENANT_SERVICE_GRPC_ADDRESS"] == "tenant-service.model.svc.cluster.local:50051"
        assert env["AUTHENTICATION_ISSUER"] == "https://login.example.com"
        assert env["AUTHENTICATION_JWKS_URL"] == "https://login.example.com/.well-known/jwks.json"
        # The listed subjects, and the service's own client for its actions.
        assert env["AUTHENTICATION_ALLOWED_SUBJECTS"] == "a,b,c,sso-service-client"
        assert env["SERVICE_TOKEN_URL"] == "https://login.example.com/oauth2/token"
        # The scope tenant-service publishes is the one the service asks for.
        assert env["SERVICE_TOKEN_SCOPES"] == "tenant-service"
        assert env["SERVICE_CLIENT_ID"] == "sso-service-client"
        assert env["SERVICE_CLIENT_SECRET"] == "service-client-secret"
        assert env["ENVELOPE_KEY"] == KEY_A
        assert env["PORT"] == "8080" and env["GRPC_PORT"] == "50051"
        assert "DEV" not in env
        assert state_out.unit_status == testing.ActiveStatus()
        assert state_out.workload_version == "1.0.0"

    @pytest.mark.parametrize("dev, expected", [(True, "true"), (False, None)])
    def test_dev_reaches_the_workload_only_when_set(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
        dev: bool,
        expected: str | None,
    ) -> None:
        """With dev, DEV=true for sso-service; without it nothing is set, not DEV=false."""
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            config={"dev": dev},
        )

        state_out = pebble_ready(context, state)

        assert environment(state_out).get("DEV") == expected
        assert state_out.unit_status == testing.ActiveStatus()

    def test_tenant_service_that_publishes_no_scope(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        tenant_service_info_relation: testing.Relation,
        mocked_is_running: MagicMock,
    ) -> None:
        """The client is registered with `openid` alone and the token asks for no scope."""
        published = tenant_service_info_relation.remote_app_data
        no_scope = testing.Relation(
            endpoint="tenant-service-info",
            interface="tenant_service_info",
            remote_app_name="tenant-service",
            remote_app_data={k: v for k, v in published.items() if k != "allowed_scope"},
            id=tenant_service_info_relation.id,
        )
        relations = [no_scope if r is tenant_service_info_relation else r for r in all_relations]
        state = create_state(relations=relations, secrets=[*client_secrets, envelope_key_secret()])

        state_out = pebble_ready(context, state)

        assert relation(state_out, "oauth").local_app_data["scope"] == "openid"
        assert environment(state_out)["SERVICE_TOKEN_SCOPES"] == ""

    @pytest.mark.parametrize(
        "jwks_url", ["https://sts/jwks", ""], ids=["keys given", "keys discovered"]
    )
    def test_configured_issuer_overrides_the_oauth_one(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
        jwks_url: str,
    ) -> None:
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            config={"authn_issuer": "https://sts.example.com", "authn_jwks_url": jwks_url},
        )

        env = environment(pebble_ready(context, state))

        assert env["AUTHENTICATION_ISSUER"] == "https://sts.example.com"
        # Never the oauth provider's keys for another issuer.
        assert env["AUTHENTICATION_JWKS_URL"] == jwks_url
        assert env["SERVICE_TOKEN_URL"] == "https://login.example.com/oauth2/token"


class TestIntegrationEvents:
    def test_follower_learns_the_public_route_when_it_changes(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        public_route_relation: testing.Relation,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            leader=False,
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
        )

        state_out = context.run(context.on.relation_changed(public_route_relation), state)

        assert environment(state_out)["PUBLIC_URL"] == "https://login.example.com/sso"

    def test_tracing_endpoint_reaches_the_workload(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        tracing = testing.Relation(
            endpoint="tracing",
            interface="tracing",
            remote_app_data={
                "receivers": json.dumps([
                    {"protocol": {"name": "otlp_http", "type": "http"}, "url": "http://tempo:4318"}
                ])
            },
        )
        state = create_state(
            relations=[*all_relations, tracing], secrets=[*client_secrets, envelope_key_secret()]
        )

        env = environment(context.run(context.on.relation_changed(tracing), state))

        assert env["TRACING_ENABLED"] and env["OTEL_HTTP_ENDPOINT"] == "tempo:4318"

    def test_broken_database_relation_stops_the_service(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )
        running = pebble_ready(context, state)

        state_out = context.run(
            context.on.relation_broken(relation(running, "pg-database")), running
        )

        workload = state_out.get_container(WORKLOAD_CONTAINER)
        assert workload.service_statuses[WORKLOAD_SERVICE] == ServiceStatus.INACTIVE


class TestLogAlert:
    def test_selects_on_a_label_the_forwarded_streams_have(self, context: testing.Context) -> None:
        """Pebble's log forwarding labels a stream with `charm`, never with `juju_charm`."""
        logging = testing.Relation(
            endpoint="logging",
            interface="loki_push_api",
            remote_units_data={0: {"endpoint": json.dumps({"url": "http://loki:3100/push"})}},
        )

        state_out = context.run(
            context.on.relation_changed(logging), create_state(relations=[logging])
        )

        rules = json.loads(relation(state_out, "logging").local_app_data["alert_rules"])
        (rule,) = rules["groups"][0]["rules"]
        assert '{charm="sso-service"}' in rule["expr"]
        # Two models may have one name.
        assert "by (juju_model, juju_model_uuid, juju_application, level)" in rule["expr"]
        # Loki adds a matcher to the selector for every topology label on the rule.
        assert rule["labels"] == {"severity": "error"}


class TestCollectStatusEvent:
    @pytest.mark.parametrize(
        "endpoint",
        [
            "pg-database",
            "public-route",
            "oauth",
            "kratos-info",
            "tenant-service-info",
            "hydra-endpoint-info",
            "ui-endpoint-info",
            "byo-sso-client",
            "kratos-external-idp",
        ],
    )
    def test_missing_integration_blocks(
        self, context: testing.Context, all_relations: list, client_secrets: list, endpoint: str
    ) -> None:
        state = create_state(
            relations=[r for r in all_relations if r.endpoint != endpoint],
            secrets=[*client_secrets, envelope_key_secret()],
        )

        state_out = context.run(context.on.config_changed(), state)

        assert state_out.unit_status == testing.BlockedStatus(f"Missing integration {endpoint}")

    def test_longest_messages_fit_in_juju_status(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        public_route_relation: testing.Relation,
    ) -> None:
        """`juju status` shows 120 characters; a command's error has the cause at its end."""
        database_down = (
            "DB connection failed, shutting down, err: failed to connect to "
            "`user=relation-7 database=prod_sso-service`: hostname resolving error: lookup "
            "postgresql-k8s-primary.prod.svc.cluster.local on 10.152.183.10:53: no such host"
        )
        related = {"relations": all_relations, "secrets": [*client_secrets, envelope_key_secret()]}
        http = testing.Relation(
            endpoint="public-route",
            interface="istio_ingress_route",
            remote_app_name="istio-ingress-public",
            remote_app_data={"external_host": "login.example.com", "tls_enabled": "False"},
            id=public_route_relation.id,
        )
        plain_http = [http if r is public_route_relation else r for r in all_relations]
        cases = [
            (
                create_state(relations=plain_http, secrets=related["secrets"]),
                "Requires a secure (HTTPS) public ingress: enable HTTPS on it, or set 'dev' for "
                "development",
            ),
            (
                create_state(**related, containers=[failing_migrate("check", database_down)]),
                "Migration check failed: ...error: lookup "
                "postgresql-k8s-primary.prod.svc.cluster.local on 10.152.183.10:53: no such host",
            ),
            (
                create_state(**related, containers=[failing_migrate("up", database_down)]),
                "Database migration failed: ...or: lookup "
                "postgresql-k8s-primary.prod.svc.cluster.local on 10.152.183.10:53: no such host",
            ),
        ]

        for state, message in cases:
            state_out = context.run(context.on.update_status(), state)

            assert state_out.unit_status == testing.BlockedStatus(message)
            assert len(message) <= 120

    @pytest.mark.parametrize(
        "endpoint, planned, waiting_for",
        [
            ("oauth", False, "Waiting for the oauth client"),
            # Kratos's client is not needed to start the service.
            ("byo-sso-client", True, "Waiting for hydra-sso to register the byo-sso client"),
        ],
    )
    def test_waits_for_a_client(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        endpoint: str,
        planned: bool,
        waiting_for: str,
    ) -> None:
        created = next(r for r in all_relations if r.endpoint == endpoint)
        pending = testing.Relation(endpoint=endpoint, interface="oauth", id=created.id)
        relations = [pending if r is created else r for r in all_relations]
        state = create_state(relations=relations, secrets=[*client_secrets, envelope_key_secret()])

        state_out = pebble_ready(context, state)

        layers = state_out.get_container(WORKLOAD_CONTAINER).layers
        assert (WORKLOAD_SERVICE in layers) is planned
        assert state_out.unit_status == testing.WaitingStatus(waiting_for)

    def test_dev_plans_a_plain_http_public_route(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        public_route_relation: testing.Relation,
        mocked_is_running: MagicMock,
    ) -> None:
        http = testing.Relation(
            endpoint="public-route",
            interface="istio_ingress_route",
            remote_app_name="istio-ingress-public",
            remote_app_data={"external_host": "login.example.com", "tls_enabled": "False"},
            id=public_route_relation.id,
        )
        relations = [http if r is public_route_relation else r for r in all_relations]
        state = create_state(
            relations=relations,
            secrets=[*client_secrets, envelope_key_secret()],
            config={"dev": True},
        )

        state_out = pebble_ready(context, state)

        assert environment(state_out)["PUBLIC_URL"] == "http://login.example.com/sso"
        assert isinstance(state_out.unit_status, testing.ActiveStatus)

    def test_unreachable_pebble_reads_as_no_service(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocker: MockerFixture,
    ) -> None:
        mocker.patch("ops.Container.get_service", side_effect=PebbleConnectionError("down"))
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        state_out = context.run(context.on.start(), state)

        assert state_out.unit_status == testing.WaitingStatus("Waiting for the service to start")

    def test_insecure_public_route_changes_nothing(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        """What runs, the route and what hydra-sso was told stay as they were."""
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )
        running = pebble_ready(context, state)
        public = relation(running, "public-route")
        http = testing.Relation(
            endpoint="public-route",
            interface="istio_ingress_route",
            remote_app_name="istio-ingress-public",
            remote_app_data={"external_host": "login.example.com", "tls_enabled": "False"},
            local_app_data=public.local_app_data,
            id=public.id,
        )
        state = create_state(
            relations=[http if r is public else r for r in running.relations],
            secrets=list(running.secrets),
            containers=list(running.containers),
        )

        state_out = context.run(context.on.relation_changed(http), state)

        assert state_out.unit_status == testing.BlockedStatus(
            "Requires a secure (HTTPS) public ingress: "
            "enable HTTPS on it, or set 'dev' for development"
        )
        assert environment(state_out)["PUBLIC_URL"] == "https://login.example.com/sso"
        assert relation(state_out, "public-route").local_app_data == public.local_app_data
        assert relation(state_out, "ui-endpoint-info").local_app_data["login_url"] == (
            "https://login.example.com/sso/login"
        )


class TestEnvelopeKey:
    def test_leader_creates_the_key(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state_out = pebble_ready(
            context, create_state(relations=all_relations, secrets=client_secrets)
        )

        key = key_in(state_out)
        assert key and len(key) == 44
        assert environment(state_out)["ENVELOPE_KEY"] == key

    def test_leader_starts_from_the_configured_key(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        backup = testing.Secret(tracked_content={ENVELOPE_KEY_SECRET_KEY: KEY_A})
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, backup],
            config={"initial_envelope_key_secret_id": backup.id},
        )

        state_out = pebble_ready(context, state)

        assert key_in(state_out) == KEY_A
        assert environment(state_out)["ENVELOPE_KEY"] == KEY_A

    def test_unusable_configured_key_blocks(
        self, context: testing.Context, all_relations: list, client_secrets: list
    ) -> None:
        backup = testing.Secret(tracked_content={ENVELOPE_KEY_SECRET_KEY: "too-short"})
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, backup],
            config={"initial_envelope_key_secret_id": backup.id},
        )

        state_out = pebble_ready(context, state)

        assert key_in(state_out) is None
        assert isinstance(state_out.unit_status, testing.BlockedStatus)
        assert "initial_envelope_key_secret_id" in state_out.unit_status.message

    @pytest.mark.parametrize(
        "content, message",
        [
            ({ENVELOPE_KEY_SECRET_KEY: "B" * 43 + "="}, "is not the key in use (unchanged)"),
            ({"other": KEY_A}, "Cannot compare initial_envelope_key_secret_id"),
        ],
        ids=["another key", "no key to compare"],
    )
    def test_configured_key_blocks_once_there_is_another(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
        content: dict,
        message: str,
    ) -> None:
        """The option set after the first start: the key in use stays, and the status says so."""
        backup = testing.Secret(tracked_content=content)
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret(), backup],
            config={"initial_envelope_key_secret_id": backup.id},
        )

        state_out = pebble_ready(context, state)

        assert environment(state_out)["ENVELOPE_KEY"] == KEY_A
        assert isinstance(state_out.unit_status, testing.BlockedStatus)
        assert message in state_out.unit_status.message
        assert len(state_out.unit_status.message) <= 120  # `juju status` cuts the rest

    def test_follower_waits_for_the_leader(
        self, context: testing.Context, all_relations: list, client_secrets: list
    ) -> None:
        state = create_state(leader=False, relations=all_relations, secrets=client_secrets)

        state_out = pebble_ready(context, state)

        assert key_in(state_out) is None
        assert WORKLOAD_SERVICE not in state_out.get_container(WORKLOAD_CONTAINER).layers
        assert state_out.unit_status == testing.WaitingStatus("Waiting for secrets creation")


class TestPublishing:
    def test_routes(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        internal_route_relation: testing.Relation,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=[*all_relations, internal_route_relation],
            secrets=[*client_secrets, envelope_key_secret()],
        )

        state_out = pebble_ready(context, state)

        public = json.loads(relation(state_out, "public-route").local_app_data["config"])
        # A prefix rewrite takes exactly one match in its rule (Gateway API).
        assert all(len(r["matches"]) == 1 for r in public["http_routes"])
        rewrites = {
            (r["matches"][0]["path"]["type"], r["matches"][0]["path"]["value"]): r["filters"][0][
                "urlRewrite"
            ]["path"]
            for r in public["http_routes"]
        }
        assert rewrites == {
            ("Exact", "/sso/login"): {"type": "ReplaceFullPath", "replaceFullPath": "/login"},
            ("Exact", "/sso/consent"): {"type": "ReplaceFullPath", "replaceFullPath": "/consent"},
            ("Exact", "/sso/error"): {"type": "ReplaceFullPath", "replaceFullPath": "/error"},
            # A redirect URI per tenant: /sso/callback/<tenant id>.
            ("PathPrefix", "/sso/callback/"): {
                "type": "ReplacePrefixMatch",
                "replacePrefixMatch": "/callback/",
            },
        }
        assert public["listeners"][0]["port"] == 443

        internal = json.loads(relation(state_out, "internal-route").local_app_data["config"])
        (route,) = internal["http_routes"]
        assert route["name"] == "sso-service-management"
        # The tenant-admin and platform-admin routes, nothing else of /api/v0/sso.
        assert [(m["path"]["type"], m["path"]["value"]) for m in route["matches"]] == [
            ("PathPrefix", "/api/v0/sso/tenants"),
            ("PathPrefix", "/api/v0/sso/connections"),
        ]
        # The paths as the service has them: no rewrite.
        assert not route["filters"]
        assert [b["port"] for b in route["backends"]] == [8080]

    def test_leader_publishes_to_the_platform(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        state_out = pebble_ready(context, state)

        hydra_sso = relation(state_out, "ui-endpoint-info").local_app_data
        assert hydra_sso["login_url"] == "https://login.example.com/sso/login"
        assert hydra_sso["consent_url"] == "https://login.example.com/sso/consent"
        assert hydra_sso["oidc_error_url"] == "https://login.example.com/sso/error"
        assert "device_verification_url" not in hydra_sso

        assert relation(state_out, "sso-service-info").local_app_data == {
            "grpc_url": "sso-service.test-model.svc.cluster.local:50051"
        }

    def test_byo_sso_client_and_provider(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        state_out = pebble_ready(context, state)

        client = relation(state_out, "byo-sso-client").local_app_data
        assert client["redirect_uri"] == (
            "https://login.example.com/self-service/methods/oidc/callback/byo-sso"
        )
        assert json.loads(client["grant_types"]) == ["authorization_code"]
        assert client["scope"] == "openid email"

        (provider,) = json.loads(
            relation(state_out, "kratos-external-idp").local_app_data["providers"]
        )
        assert provider["id"] == "byo-sso"
        assert provider["issuer_url"] == "https://sso.example.com"
        assert provider["client_id"] == "kratos-byo-sso"
        assert provider["scope"] == "openid email"
        assert "email_verified" in provider["jsonnet_mapper"]
        assert provider["client_secret"] == "kratos-client-secret"

    def test_publishes_before_the_database_is_ready(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        database_relation: testing.Relation,
    ) -> None:
        not_created = testing.Relation(
            endpoint="pg-database",
            interface="postgresql_client",
            remote_app_name="postgresql-k8s",
            id=database_relation.id,
        )
        relations = [not_created if r is database_relation else r for r in all_relations]
        state = create_state(relations=relations, secrets=[*client_secrets, envelope_key_secret()])

        state_out = pebble_ready(context, state)

        assert WORKLOAD_SERVICE not in state_out.get_container(WORKLOAD_CONTAINER).layers
        assert relation(state_out, "ui-endpoint-info").local_app_data["login_url"]
        assert relation(state_out, "sso-service-info").local_app_data["grpc_url"]
        assert "providers" in relation(state_out, "kratos-external-idp").local_app_data

    def test_kratos_reported_callback_wins(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        kratos_external_idp_relation: testing.Relation,
        mocked_is_running: MagicMock,
    ) -> None:
        reported = testing.Relation(
            endpoint="kratos-external-idp",
            interface="external_provider",
            remote_app_name="kratos",
            remote_app_data={
                "providers": json.dumps([
                    {"provider_id": "byo-sso", "redirect_uri": "https://id.example.com/cb"}
                ])
            },
            id=kratos_external_idp_relation.id,
        )
        relations = [reported if r is kratos_external_idp_relation else r for r in all_relations]
        state = create_state(relations=relations, secrets=[*client_secrets, envelope_key_secret()])

        state_out = pebble_ready(context, state)

        assert relation(state_out, "byo-sso-client").local_app_data["redirect_uri"] == (
            "https://id.example.com/cb"
        )

    def test_follower_publishes_nothing(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            leader=False,
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
        )

        state_out = pebble_ready(context, state)

        assert not relation(state_out, "ui-endpoint-info").local_app_data
        assert not relation(state_out, "kratos-external-idp").local_app_data
        assert "config" not in relation(state_out, "public-route").local_app_data
        assert environment(state_out)["ENVELOPE_KEY"] == KEY_A


class TestCABundle:
    CA = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"

    @pytest.fixture
    def charm_copy(self, mocker: MockerFixture, tmp_path: Path) -> Path:
        """The charm's copy of the bundle: what it last applied."""
        return mocker.patch("charm.LOCAL_CHARM_CERTIFICATES_FILE", tmp_path / "ca.crt")

    @pytest.fixture
    def relations(self, all_relations: list) -> list:
        ca_relation = testing.Relation(
            endpoint="receive-ca-cert",
            interface="certificate_transfer",
            remote_app_data={"certificates": json.dumps([self.CA]), "version": "1"},
        )
        return [*all_relations, ca_relation]

    @pytest.fixture
    def state(self, relations: list, client_secrets: list) -> testing.State:
        return create_state(relations=relations, secrets=[*client_secrets, envelope_key_secret()])

    @pytest.mark.parametrize("workload_restarted", [True, False])
    def test_unchanged_bundle_is_pushed_only_to_a_restarted_workload(
        self,
        context: testing.Context,
        state: testing.State,
        charm_copy: Path,
        mocker: MockerFixture,
        workload_restarted: bool,
    ) -> None:
        """A workload container that restarted alone has lost the bundle."""
        charm_copy.write_text(self.CA)
        push = mocker.patch("charm.WorkloadService.update_ca_certs", return_value=True)

        if workload_restarted:
            pebble_ready(context, state)
        else:
            context.run(context.on.config_changed(), state)

        assert push.called is workload_restarted

    def test_failed_update_is_retried(
        self,
        context: testing.Context,
        state: testing.State,
        charm_copy: Path,
        mocker: MockerFixture,
    ) -> None:
        """The charm's copy is not kept, so the next hook sees the bundle as new."""
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "update-ca-certificates"),
        )

        state_out = context.run(context.on.config_changed(), state)

        assert not charm_copy.exists()
        assert WORKLOAD_SERVICE not in state_out.get_container(WORKLOAD_CONTAINER).layers

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(PebbleConnectionError("pebble is down"), id="pebble is down"),
            pytest.param(TimeoutError("timed out"), id="pebble does not answer in time"),
        ],
    )
    def test_failed_push_is_retried(
        self,
        context: testing.Context,
        state: testing.State,
        charm_copy: Path,
        mocker: MockerFixture,
        error: Exception,
    ) -> None:
        """With the new copy left in place, the next hook would find nothing to push."""
        push = mocker.patch(
            "charm.WorkloadService.update_ca_certs",
            side_effect=[error, True],
        )

        context.run(context.on.config_changed(), state)
        context.run(context.on.config_changed(), state)

        assert push.call_count == 2

    def test_failed_removal_is_retried(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        charm_copy: Path,
        mocker: MockerFixture,
    ) -> None:
        """The charm's copy is put back, so the next hook sees the bundle as removed."""
        charm_copy.write_text(self.CA)
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "update-ca-certificates"),
        )
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        context.run(context.on.config_changed(), state)

        assert charm_copy.read_text() == self.CA

    def test_applied_bundle_with_crlf_line_endings_is_not_applied_again(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        charm_copy: Path,
        mocked_subprocess_run: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Read as text, the copy would never equal a bundle with CRLF line endings."""
        ca = self.CA.replace("\n", "\r\n")
        charm_copy.write_text(ca)
        push = mocker.patch("charm.WorkloadService.update_ca_certs")
        ca_relation = testing.Relation(
            endpoint="receive-ca-cert",
            interface="certificate_transfer",
            remote_app_data={"certificates": json.dumps([ca]), "version": "1"},
        )
        state = create_state(
            relations=[*all_relations, ca_relation],
            secrets=[*client_secrets, envelope_key_secret()],
        )

        context.run(context.on.config_changed(), state)

        assert not mocked_subprocess_run.called
        assert not push.called

    @pytest.mark.parametrize("sent", [True, False], ids=["a new bundle", "the bundle removed"])
    def test_changed_bundle_restarts_the_service(
        self,
        context: testing.Context,
        relations: list,
        all_relations: list,
        client_secrets: list,
        charm_copy: Path,
        mocker: MockerFixture,
        sent: bool,
    ) -> None:
        """A removed bundle leaves no copy: one would read as a change in every hook."""
        mocker.patch("charm.WorkloadService.update_ca_certs", return_value=True)
        plan = mocker.patch("charm.PebbleService.plan")
        if not sent:
            charm_copy.write_text(self.CA)
        state = create_state(
            relations=relations if sent else all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
        )

        context.run(context.on.config_changed(), state)

        assert plan.call_args.kwargs == {"force_restart": True}
        assert charm_copy.exists() is sent

    def test_bundle_is_read_once_a_hook(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        byo_sso_client_relation: testing.Relation,
        charm_copy: Path,
        mocker: MockerFixture,
    ) -> None:
        """Reading a bundle sent as unit data consumes it, and this hook reconciles twice."""
        charm_copy.write_text(self.CA)
        push = mocker.patch("charm.WorkloadService.update_ca_certs", return_value=True)
        plan = mocker.patch("charm.PebbleService.plan")
        ca = json.dumps(self.CA)
        sent_by_units = testing.Relation(
            endpoint="receive-ca-cert",
            interface="certificate_transfer",
            remote_units_data={0: {"ca": ca, "certificate": ca, "chain": json.dumps([self.CA])}},
        )
        state = create_state(
            relations=[*all_relations, sent_by_units],
            secrets=[*client_secrets, envelope_key_secret()],
        )

        context.run(context.on.relation_changed(byo_sso_client_relation), state)

        assert plan.call_count == 2
        assert not push.called
        assert charm_copy.read_text() == self.CA

    @pytest.mark.parametrize(
        "leader, pending, silent, waiting_for",
        [
            (False, True, None, "Waiting for leader unit to run the migration"),
            (True, False, "pg-database", "Waiting for database creation"),
            (True, False, "public-route", "Waiting for the public route"),
            (True, False, "tenant-service-info", "Waiting for tenant-service's address"),
            (True, False, "hydra-endpoint-info", "Waiting for hydra-sso's endpoints"),
            (True, False, "kratos-info", "Waiting for Kratos's info"),
        ],
        ids=[
            "a follower before the migration",
            "no database yet",
            "no public route yet",
            "no tenant-service address yet",
            "no hydra-sso endpoints yet",
            "no Kratos info yet",
        ],
    )
    def test_bundle_waits_for_a_hook_that_plans(
        self,
        context: testing.Context,
        relations: list,
        client_secrets: list,
        charm_copy: Path,
        mocker: MockerFixture,
        leader: bool,
        pending: bool,
        silent: str | None,
        waiting_for: str,
    ) -> None:
        """Pushed in a hook that does not restart, the bundle would never be loaded."""
        push = mocker.patch("charm.WorkloadService.update_ca_certs")
        state = create_state(
            leader=leader,
            relations=[
                testing.Relation(endpoint=r.endpoint, interface=r.interface, id=r.id)
                if r.endpoint == silent
                else r
                for r in relations
            ],
            secrets=[*client_secrets, envelope_key_secret()],
            containers=[pending_migration()] if pending else None,
        )

        state_out = context.run(context.on.config_changed(), state)

        assert not push.called
        assert not charm_copy.exists()
        # The bundle waits with the plan, and the status says what the plan waits for.
        assert state_out.unit_status == testing.WaitingStatus(waiting_for)


def pending_migration() -> testing.Container:
    """A workload whose database is not migrated yet."""
    return testing.Container(WORKLOAD_CONTAINER, can_connect=True, execs=execs("pending"))


def failing_migrate(command: str, stderr: str = "lock timeout") -> testing.Container:
    """A workload whose `sso-service migrate <command>` fails."""
    commands = {e for e in execs("pending") if e.command_prefix[-1] != command}
    commands.add(testing.Exec(["sso-service", "migrate", command], return_code=1, stderr=stderr))
    return testing.Container(WORKLOAD_CONTAINER, can_connect=True, execs=commands)


class TestMigration:
    def test_leader_migrates(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            containers=[pending_migration()],
        )

        state_out = pebble_ready(context, state)

        commands = [e.command for e in context.exec_history[WORKLOAD_CONTAINER]]
        assert any(c[:3] == ["sso-service", "migrate", "up"] for c in commands)
        # What wakes the units that wait for the migration.
        assert relation(state_out, "sso-service").local_app_data == {
            "migration_completed": '"1.0.0"'
        }
        # The workload is not asked again, and would still say pending in this test.
        assert state_out.unit_status == testing.ActiveStatus()

    def test_follower_waits_for_the_migration(
        self, context: testing.Context, all_relations: list, client_secrets: list
    ) -> None:
        state = create_state(
            leader=False,
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            containers=[pending_migration()],
        )

        state_out = pebble_ready(context, state)

        commands = [e.command for e in context.exec_history[WORKLOAD_CONTAINER]]
        assert not any(c[:3] == ["sso-service", "migrate", "up"] for c in commands)
        assert WORKLOAD_SERVICE not in state_out.get_container(WORKLOAD_CONTAINER).layers
        assert state_out.unit_status == testing.WaitingStatus(
            "Waiting for leader unit to run the migration"
        )

    @pytest.mark.parametrize(
        "command, ran, status",
        [
            ("up", ["check", "up"], "Database migration failed: lock timeout"),
            # Asked once, and nothing is migrated on an answer the charm does not have.
            ("check", ["check"], "Migration check failed: lock timeout"),
        ],
    )
    def test_failure_blocks_with_the_reason(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        command: str,
        ran: list[str],
        status: str,
    ) -> None:
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            containers=[failing_migrate(command)],
        )

        state_out = context.run(context.on.update_status(), state)

        commands = [e.command for e in context.exec_history[WORKLOAD_CONTAINER]]
        assert [c[2] for c in commands if c[1] == "migrate"] == ran
        assert WORKLOAD_SERVICE not in state_out.get_container(WORKLOAD_CONTAINER).layers
        assert state_out.unit_status == testing.BlockedStatus(status)

    def test_checked_once_a_hook(
        self,
        context: testing.Context,
        all_relations: list,
        client_secrets: list,
        mocked_is_running: MagicMock,
    ) -> None:
        state = create_state(
            relations=all_relations, secrets=[*client_secrets, envelope_key_secret()]
        )

        context.run(context.on.update_status(), state)

        commands = [e.command[:3] for e in context.exec_history[WORKLOAD_CONTAINER]]
        assert commands.count(["sso-service", "migrate", "check"]) == 1


class TestInvalidConfig:
    def test_leaves_the_service_as_it_is(
        self, context: testing.Context, all_relations: list, client_secrets: list
    ) -> None:
        """An invalid configuration is reported; what runs stays as it was."""
        container = testing.Container(
            WORKLOAD_CONTAINER,
            can_connect=True,
            execs=execs(),
            layers={
                WORKLOAD_SERVICE: Layer({
                    "services": {
                        WORKLOAD_SERVICE: {
                            "override": "replace",
                            "command": "sso-service serve",
                            "startup": "enabled",
                        }
                    }
                })
            },
            service_statuses={WORKLOAD_SERVICE: ServiceStatus.ACTIVE},
        )
        state = create_state(
            relations=all_relations,
            secrets=[*client_secrets, envelope_key_secret()],
            containers=[container],
            config={"authn_jwks_url": "https://sts/jwks"},
        )

        state_out = context.run(context.on.config_changed(), state)

        workload = state_out.get_container(WORKLOAD_CONTAINER)
        assert workload.service_statuses[WORKLOAD_SERVICE] == ServiceStatus.ACTIVE
        assert workload.layers == container.layers
        assert state_out.unit_status == testing.BlockedStatus(
            "Invalid configuration: authn_jwks_url is set without authn_issuer"
        )
