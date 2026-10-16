# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import json
from unittest.mock import MagicMock

import pytest
from ops import testing
from pytest_mock import MockerFixture

from charm import SSOServiceOperatorCharm
from constants import ENVELOPE_KEY_SECRET_KEY, ENVELOPE_KEY_SECRET_LABEL, WORKLOAD_CONTAINER

KEY_A = "A" * 43 + "="


def execs(migration_status: str = "ok", workload_version: str = "1.0.0") -> set[testing.Exec]:
    """The workload commands the charm runs."""
    return {
        testing.Exec(
            command_prefix=["sso-service", "version"],
            return_code=0,
            stdout=f"App Version: {workload_version}",
        ),
        testing.Exec(
            command_prefix=["sso-service", "migrate", "check"],
            return_code=0,
            stdout=json.dumps({"status": migration_status}),
        ),
        testing.Exec(
            command_prefix=["sso-service", "migrate", "up"],
            return_code=0,
            stdout="",
        ),
    }


# ---------------------------------------------------------------------------
# create_state() — module-level factory (NOT a fixture)
# ---------------------------------------------------------------------------
def create_state(
    leader: bool = True,
    secrets: list | None = None,
    relations: list | None = None,
    containers: list | None = None,
    config: dict | None = None,
    can_connect: bool = True,
    workload_version: str = "1.0.0",
) -> testing.State:
    """Build a complete State with sensible defaults for sso-service tests."""
    if secrets is None:
        secrets = []
    if relations is None:
        relations = []
    if containers is None:
        containers = [
            testing.Container(
                WORKLOAD_CONTAINER,
                can_connect=can_connect,
                execs=execs(workload_version=workload_version),
            )
        ]
    if config is None:
        config = {}

    return testing.State(
        leader=leader,
        secrets=secrets,
        containers=containers,
        relations=relations,
        config=config,
        model=testing.Model(name="test-model"),
    )


def envelope_key_secret() -> testing.Secret:
    """The charm's envelope key secret, holding KEY_A."""
    return testing.Secret(
        tracked_content={ENVELOPE_KEY_SECRET_KEY: KEY_A},
        label=ENVELOPE_KEY_SECRET_LABEL,
        owner="app",
    )


# ---------------------------------------------------------------------------
# Resource-patch mocks (autouse)
# ---------------------------------------------------------------------------
@pytest.fixture()
def mocked_resource_patch(mocker: MockerFixture) -> MagicMock:
    mocked = mocker.patch(
        "charms.observability_libs.v0.kubernetes_compute_resources_patch.ResourcePatcher",
        autospec=True,
    )
    mocked.return_value.is_failed.return_value = (False, "")
    mocked.return_value.is_in_progress.return_value = False
    return mocked


@pytest.fixture(autouse=True)
def mocked_k8s_resource_patch(mocker: MockerFixture, mocked_resource_patch: MagicMock) -> None:
    mocker.patch.multiple(
        "charm.KubernetesComputeResourcesPatch",
        _namespace="testing",
        _patch=lambda *a, **kw: True,
        is_ready=lambda *a, **kw: True,
    )


# ---------------------------------------------------------------------------
# Subprocess autouse mock
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mocked_subprocess_run(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("subprocess.run")


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
@pytest.fixture
def context() -> testing.Context:
    return testing.Context(SSOServiceOperatorCharm)


# ---------------------------------------------------------------------------
# Charm service mocks
# ---------------------------------------------------------------------------
@pytest.fixture
def mocked_is_running(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("charm.WorkloadService.is_running", return_value=True)


# ---------------------------------------------------------------------------
# Relation fixtures (standalone)
# ---------------------------------------------------------------------------
@pytest.fixture
def database_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="pg-database",
        interface="postgresql_client",
        remote_app_name="postgresql-k8s",
        remote_app_data={
            "endpoints": "postgresql-k8s-primary.model.svc.cluster.local:5432",
            "username": "relation-7",
            "password": "pg-password",
        },
    )


@pytest.fixture
def public_route_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="public-route",
        interface="istio_ingress_route",
        remote_app_name="istio-ingress-public",
        remote_app_data={"external_host": "login.example.com", "tls_enabled": "True"},
    )


@pytest.fixture
def internal_route_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="internal-route",
        interface="istio_ingress_route",
        remote_app_name="istio-ingress-internal",
        remote_app_data={"external_host": "iam.internal.example.com", "tls_enabled": "True"},
    )


@pytest.fixture
def oauth_client_secret() -> testing.Secret:
    return testing.Secret(tracked_content={"secret": "service-client-secret"})


@pytest.fixture
def oauth_relation(oauth_client_secret: testing.Secret) -> testing.Relation:
    return testing.Relation(
        endpoint="oauth",
        interface="oauth",
        remote_app_name="hydra",
        remote_app_data={
            "issuer_url": "https://login.example.com",
            "authorization_endpoint": "https://login.example.com/oauth2/auth",
            "token_endpoint": "https://login.example.com/oauth2/token",
            "introspection_endpoint": "https://hydra-admin/admin/oauth2/introspect",
            "userinfo_endpoint": "https://login.example.com/userinfo",
            "jwks_endpoint": "https://login.example.com/.well-known/jwks.json",
            "scope": "openid",
            "client_id": "sso-service-client",
            "client_secret_id": oauth_client_secret.id,
        },
    )


@pytest.fixture
def byo_sso_client_secret() -> testing.Secret:
    return testing.Secret(tracked_content={"secret": "kratos-client-secret"})


@pytest.fixture
def byo_sso_client_relation(byo_sso_client_secret: testing.Secret) -> testing.Relation:
    return testing.Relation(
        endpoint="byo-sso-client",
        interface="oauth",
        remote_app_name="hydra-sso",
        remote_app_data={
            "issuer_url": "https://sso.example.com",
            "authorization_endpoint": "https://sso.example.com/oauth2/auth",
            "token_endpoint": "https://sso.example.com/oauth2/token",
            "introspection_endpoint": "https://hydra-sso-admin/admin/oauth2/introspect",
            "userinfo_endpoint": "https://sso.example.com/userinfo",
            "jwks_endpoint": "https://sso.example.com/.well-known/jwks.json",
            "scope": "openid email",
            "client_id": "kratos-byo-sso",
            "client_secret_id": byo_sso_client_secret.id,
        },
    )


@pytest.fixture
def hydra_endpoints_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="hydra-endpoint-info",
        interface="hydra_endpoints",
        remote_app_name="hydra-sso",
        remote_app_data={
            "admin_endpoint": "http://hydra-sso.model.svc.cluster.local:4445",
            "public_endpoint": "http://hydra-sso.model.svc.cluster.local:4444",
        },
    )


@pytest.fixture
def kratos_info_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="kratos-info",
        interface="kratos_info",
        remote_app_name="kratos",
        remote_app_data={
            "admin_endpoint": "http://kratos.model.svc.cluster.local:4434",
            "public_endpoint": "http://kratos.model.svc.cluster.local:4433",
            "login_browser_endpoint": "https://login.example.com/self-service/login/browser",
        },
    )


@pytest.fixture
def tenant_service_info_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="tenant-service-info",
        interface="tenant_service_info",
        remote_app_name="tenant-service",
        remote_app_data={
            "service_url": "http://tenant-service.model.svc.cluster.local:8080",
            "grpc_url": "tenant-service.model.svc.cluster.local:50051",
            "allowed_scope": "tenant-service",
        },
    )


@pytest.fixture
def login_ui_endpoints_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="ui-endpoint-info", interface="login_ui_endpoints", remote_app_name="hydra-sso"
    )


@pytest.fixture
def kratos_external_idp_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="kratos-external-idp",
        interface="external_provider",
        remote_app_name="kratos",
    )


@pytest.fixture
def sso_service_info_relation() -> testing.Relation:
    return testing.Relation(
        endpoint="sso-service-info", interface="sso_service_info", remote_app_name="login-ui"
    )


@pytest.fixture
def peer_relation() -> testing.PeerRelation:
    return testing.PeerRelation(endpoint="sso-service", interface="sso_service_peers")


@pytest.fixture
def all_relations(
    database_relation: testing.Relation,
    public_route_relation: testing.Relation,
    oauth_relation: testing.Relation,
    byo_sso_client_relation: testing.Relation,
    hydra_endpoints_relation: testing.Relation,
    kratos_info_relation: testing.Relation,
    tenant_service_info_relation: testing.Relation,
    login_ui_endpoints_relation: testing.Relation,
    kratos_external_idp_relation: testing.Relation,
    sso_service_info_relation: testing.Relation,
    peer_relation: testing.PeerRelation,
) -> list:
    """Every required relation, with data."""
    return [
        database_relation,
        public_route_relation,
        oauth_relation,
        byo_sso_client_relation,
        hydra_endpoints_relation,
        kratos_info_relation,
        tenant_service_info_relation,
        login_ui_endpoints_relation,
        kratos_external_idp_relation,
        sso_service_info_relation,
        peer_relation,
    ]


@pytest.fixture
def client_secrets(
    oauth_client_secret: testing.Secret, byo_sso_client_secret: testing.Secret
) -> list:
    """The OAuth client secrets the two oauth relations point at."""
    return [oauth_client_secret, byo_sso_client_secret]
