# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, create_autospec

import pytest
from charmlibs.interfaces.istio_ingress_route import IstioIngressRouteRequirer
from charmlibs.interfaces.oauth import OAuthRequirer
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from pydantic import AnyHttpUrl

from integrations import (
    DatabaseConfig,
    KratosInfoData,
    OAuthIntegration,
    PublicRouteData,
    TenantServiceData,
    TracingData,
)


@pytest.fixture
def route_requirer() -> MagicMock:
    requirer = create_autospec(IstioIngressRouteRequirer, instance=True)
    requirer._charm = MagicMock()
    requirer._charm.model.name = "prod"
    requirer._charm.app.name = "sso-service"
    requirer.external_host = "login.example.com"
    requirer.tls_enabled = True
    return requirer


class TestPublicRouteData:
    def test_load(self, route_requirer: MagicMock) -> None:
        data = PublicRouteData.load(route_requirer)

        assert data.url == AnyHttpUrl("https://login.example.com/sso")
        assert data.is_ready() and data.secured
        assert data.to_env_vars() == {"PUBLIC_URL": "https://login.example.com/sso"}
        assert data.config is not None
        assert [r.name for r in data.config.http_routes] == [
            "sso-service-login",
            "sso-service-consent",
            "sso-service-error",
            "sso-service-callback",
        ]
        assert all(b.port == 8080 for r in data.config.http_routes for b in r.backends)

    def test_without_external_host(self, route_requirer: MagicMock) -> None:
        route_requirer.external_host = ""

        data = PublicRouteData.load(route_requirer)

        assert not data.is_ready()
        assert data.config is not None

    def test_plain_http(self, route_requirer: MagicMock) -> None:
        route_requirer.tls_enabled = False

        data = PublicRouteData.load(route_requirer)

        assert data.url == AnyHttpUrl("http://login.example.com/sso") and not data.secured
        assert data.config is not None and data.config.listeners[0].port == 80


class TestTracingData:
    @pytest.mark.parametrize("missing", ["otlp_http", "otlp_grpc"])
    def test_load_without_an_endpoint(self, missing: str) -> None:
        """A provider that has not sent one of the two endpoints yet is still read."""
        endpoints = {"otlp_http": "http://tempo:4318", "otlp_grpc": "tempo:4317", missing: None}
        requirer = create_autospec(TracingEndpointRequirer, instance=True)
        requirer.is_ready.return_value = True
        requirer.get_endpoint.side_effect = endpoints.get

        data = TracingData.load(requirer)

        assert data.is_ready
        assert data.http_endpoint == (endpoints["otlp_http"] or "").removeprefix("http://")
        assert data.grpc_endpoint == (endpoints["otlp_grpc"] or "")


class TestDatabaseConfig:
    def test_dsn_encodes_the_user_and_the_password(self) -> None:
        """Unencoded, a password with `@`, `/` or `?` gives a DSN that does not parse."""
        config = DatabaseConfig(
            endpoint="pg:5432", database="prod_sso-service", username="u/1", password="p@ss/w?rd"
        )

        assert config.dsn == "postgres://u%2F1:p%40ss%2Fw%3Frd@pg:5432/prod_sso-service"


class TestKratosInfoData:
    def test_callback_derived_from_the_login_browser_endpoint(self) -> None:
        kratos = KratosInfoData(
            admin_url="http://kratos:4434",
            login_browser_url="https://id.example.com/kratos/self-service/login/browser",
        )

        assert kratos.byo_sso_callback_url == (
            "https://id.example.com/kratos/self-service/methods/oidc/callback/byo-sso"
        )

    def test_unknown_shape(self) -> None:
        kratos = KratosInfoData(login_browser_url="https://id.example.com/x")

        assert kratos.byo_sso_callback_url == ""


class TestOAuthIntegration:
    def test_client_holds_the_scope_tenant_service_admits(self) -> None:
        requirer = create_autospec(OAuthRequirer, instance=True)
        requirer.is_client_created.return_value = False

        integration = OAuthIntegration(
            requirer,
            TenantServiceData(grpc_url="tenant-service:50051", allowed_scope="tenant-service"),
        )

        client_config = requirer.update_client_config.call_args.args[0]
        assert client_config.scope == "openid tenant-service"
        assert client_config.grant_types == ["client_credentials"]
        assert not integration.is_ready()

    def test_client_stays_as_it_is_without_tenant_service(self) -> None:
        """The scope is not taken from a client whose service still asks for it."""
        requirer = create_autospec(OAuthRequirer, instance=True)

        OAuthIntegration(requirer, TenantServiceData())

        requirer.update_client_config.assert_not_called()
