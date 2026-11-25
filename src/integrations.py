# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper classes for managing the charm's integrations."""

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

from charmlibs.interfaces.istio_ingress_route import (
    BackendRef,
    HTTPPathMatch,
    HTTPPathMatchType,
    HTTPRoute,
    HTTPRouteMatch,
    IstioIngressRouteConfig,
    IstioIngressRouteRequirer,
    Listener,
    PathModifier,
    PathModifierType,
    ProtocolType,
    URLRewriteFilter,
    URLRewriteSpec,
)
from charmlibs.interfaces.oauth import ClientConfig, OAuthRequirer
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.hydra.v0.hydra_endpoints import (
    HydraEndpointsRelationError,
    HydraEndpointsRequirer,
)
from charms.identity_platform_login_ui_operator.v0.login_ui_endpoints import (
    LoginUIEndpointsProvider,
    LoginUIProviderData,
)
from charms.kratos.v0.kratos_info import KratosInfoRelationError, KratosInfoRequirer
from charms.kratos_external_idp_integrator.v1.kratos_external_provider import (
    ExternalIdpProvider,
)
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from charms.tenant_service.v0.tenant_service_info import TenantServiceInfoRequirer
from ops.model import Model
from pydantic import AnyHttpUrl
from sso_service_info import SSOServiceInfoProvider

from constants import (
    BYO_SSO_GRANT_TYPES,
    BYO_SSO_MAPPER_FILE,
    BYO_SSO_PROVIDER_ID,
    BYO_SSO_PROVIDER_LABEL,
    BYO_SSO_SCOPE,
    CERTIFICATE_TRANSFER_INTEGRATION_NAME,
    INGRESS_HTTP_PORT,
    INGRESS_HTTPS_PORT,
    KRATOS_CALLBACK_PATH,
    KRATOS_LOGIN_BROWSER_PATH,
    MANAGEMENT_PATH_PREFIXES,
    OAUTH_GRANT_TYPES,
    OAUTH_SCOPES,
    PEER_INTEGRATION_NAME,
    PORT,
    POSTGRESQL_DSN_TEMPLATE,
    PUBLIC_CALLBACK_PREFIX,
    PUBLIC_PAGES,
    PUBLIC_PATH_PREFIX,
)
from env_vars import EnvVars

logger = logging.getLogger(__name__)


def _join(base: str, path: str) -> str:
    """Join a base URL and a path with one slash."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def get_external_host_and_scheme(requirer: IstioIngressRouteRequirer) -> tuple[str, str]:
    """Extract external_host and scheme from an istio ingress route requirer."""
    scheme = "https" if requirer.tls_enabled else "http"
    return requirer.external_host, scheme


def _listener(requirer: IstioIngressRouteRequirer) -> Listener:
    """Build the gateway listener the routes attach to."""
    port = INGRESS_HTTPS_PORT if requirer.tls_enabled else INGRESS_HTTP_PORT
    return Listener(port=port, protocol=ProtocolType.HTTP)


def _rewritten_route(
    app: str, name: str, listener: Listener, match: HTTPPathMatch, rewrite: PathModifier
) -> HTTPRoute:
    """Build a route to the service for one path match, with the path rewritten."""
    return HTTPRoute(
        name=f"{app}-{name}",
        listener=listener,
        matches=[HTTPRouteMatch(path=match)],
        filters=[URLRewriteFilter(urlRewrite=URLRewriteSpec(path=rewrite))],
        backends=[BackendRef(service=app, port=PORT)],
    )


@dataclass(frozen=True, slots=True)
class PublicRouteData:
    """The data source from the public-route integration.

    The browser pages, under /sso on the public gateway, each rewritten to the
    service's own path; nothing else of the service is public. /sso/login,
    /sso/consent and /sso/error are exact paths, and the prefix /sso/callback/
    is rewritten to /callback/: the callback is a path per tenant.
    """

    url: AnyHttpUrl | None = None
    config: IstioIngressRouteConfig | None = None

    def is_ready(self) -> bool:
        """Check if the ingress has published its host."""
        return self.url is not None

    @property
    def secured(self) -> bool:
        """Check if the ingress URL uses HTTPS."""
        return self.url is not None and self.url.scheme == "https"

    def to_env_vars(self) -> EnvVars:
        """Get public route env vars."""
        return {"PUBLIC_URL": str(self.url) if self.url else ""}

    @classmethod
    def load(cls, requirer: IstioIngressRouteRequirer) -> "PublicRouteData":
        """Load the route from the relation."""
        model, app = requirer._charm.model.name, requirer._charm.app.name
        external_host, scheme = get_external_host_and_scheme(requirer)

        listener = _listener(requirer)
        http_routes = [
            _rewritten_route(
                app,
                page,
                listener,
                HTTPPathMatch(type=HTTPPathMatchType.Exact, value=f"{PUBLIC_PATH_PREFIX}/{page}"),
                PathModifier(type=PathModifierType.ReplaceFullPath, value=f"/{page}"),
            )
            for page in PUBLIC_PAGES
        ]
        http_routes.append(
            _rewritten_route(
                app,
                "callback",
                listener,
                HTTPPathMatch(
                    type=HTTPPathMatchType.PathPrefix,
                    value=f"{PUBLIC_PATH_PREFIX}{PUBLIC_CALLBACK_PREFIX}",
                ),
                PathModifier(
                    type=PathModifierType.ReplacePrefixMatch, value=PUBLIC_CALLBACK_PREFIX
                ),
            )
        )
        config = IstioIngressRouteConfig(
            model=model, listeners=[listener], http_routes=http_routes
        )

        if not external_host:
            logger.info("External hostname is not set on the ingress provider")
            return cls(config=config)

        return cls(
            url=AnyHttpUrl(f"{scheme}://{external_host}{PUBLIC_PATH_PREFIX}"),
            config=config,
        )


@dataclass(frozen=True, slots=True)
class InternalIngressData:
    """The data source from the internal-route integration.

    The management API on the internal gateway, which the Authorization Service
    must guard: the charm cannot tell whether it does. One route with a prefix
    match per MANAGEMENT_PATH_PREFIXES, the paths as the service has them.
    """

    config: IstioIngressRouteConfig | None = None

    @classmethod
    def load(cls, requirer: IstioIngressRouteRequirer) -> "InternalIngressData":
        """Load the route from the relation."""
        model, app = requirer._charm.model.name, requirer._charm.app.name
        listener = _listener(requirer)
        return cls(
            config=IstioIngressRouteConfig(
                model=model,
                listeners=[listener],
                http_routes=[
                    HTTPRoute(
                        name=f"{app}-management",
                        listener=listener,
                        matches=[
                            HTTPRouteMatch(
                                path=HTTPPathMatch(type=HTTPPathMatchType.PathPrefix, value=prefix)
                            )
                            for prefix in MANAGEMENT_PATH_PREFIXES
                        ],
                        backends=[BackendRef(service=app, port=PORT)],
                    )
                ],
            )
        )


@dataclass(frozen=True)
class TracingData:
    """The data source from the tracing integration."""

    is_ready: bool = False
    http_endpoint: str = ""
    grpc_endpoint: str = ""

    def to_env_vars(self) -> EnvVars:
        """Get tracing env vars."""
        return {
            "TRACING_ENABLED": self.is_ready,
            "OTEL_HTTP_ENDPOINT": self.http_endpoint,
            "OTEL_GRPC_ENDPOINT": self.grpc_endpoint,
        }

    @classmethod
    def load(cls, requirer: TracingEndpointRequirer) -> "TracingData":
        """Load the tracing data."""
        if not (is_ready := requirer.is_ready()):
            return TracingData()

        # The provider may not have sent an endpoint yet: neither is parsed unless it is there.
        http_endpoint_raw = requirer.get_endpoint("otlp_http")
        http_endpoint = ""
        if http_endpoint_raw:
            parsed = urlparse(http_endpoint_raw)
            http_endpoint = parsed.geturl().replace(f"{parsed.scheme}://", "", 1)

        grpc_endpoint_raw = requirer.get_endpoint("otlp_grpc")
        grpc_endpoint = ""
        if grpc_endpoint_raw:
            parsed = urlparse(grpc_endpoint_raw)
            grpc_endpoint = parsed.geturl().replace(f"{parsed.scheme}://", "", 1)

        return TracingData(
            is_ready=is_ready,
            http_endpoint=http_endpoint,
            grpc_endpoint=grpc_endpoint,
        )


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    """The data source from the database integration."""

    endpoint: str = ""
    database: str = ""
    username: str = ""
    password: str = ""

    @property
    def dsn(self) -> str:
        """The PostgreSQL DSN, the user and the password percent-encoded."""
        return POSTGRESQL_DSN_TEMPLATE.substitute(
            username=quote(self.username, safe=""),
            password=quote(self.password, safe=""),
            endpoint=self.endpoint,
            database=self.database,
        )

    def to_env_vars(self) -> EnvVars:
        """Get database env vars."""
        return {
            "DSN": self.dsn,
        }

    @classmethod
    def load(cls, requirer: DatabaseRequires) -> "DatabaseConfig":
        """Load the database config from the relation."""
        if not (database_integrations := requirer.relations):
            return cls()

        integration_id = database_integrations[0].id
        integration_data: dict[str, str] = requirer.fetch_relation_data()[integration_id]

        return cls(
            endpoint=integration_data.get("endpoints", "").split(",")[0],
            database=requirer.database,
            username=integration_data.get("username", ""),
            password=integration_data.get("password", ""),
        )


@dataclass(frozen=True)
class HydraSSOData:
    """The data source from the hydra-endpoint-info integration.

    hydra-sso's issuer comes from byo-sso-client instead: hydra-endpoint-info
    publishes the in-cluster public address, not the one browsers reach.
    """

    admin_url: str = ""

    def to_env_vars(self) -> EnvVars:
        """Get hydra-sso env vars."""
        return {"HYDRA_SSO_ADMIN_URL": self.admin_url}

    @classmethod
    def load(cls, requirer: HydraEndpointsRequirer) -> "HydraSSOData":
        """Load the hydra-sso data from the relation."""
        try:
            endpoints = requirer.get_hydra_endpoints()
        except (HydraEndpointsRelationError, KeyError):
            return cls()
        return cls(admin_url=endpoints.get("admin_endpoint", ""))


@dataclass(frozen=True)
class KratosInfoData:
    """The data source from the kratos-info integration."""

    admin_url: str = ""
    login_browser_url: str = ""

    def is_ready(self) -> bool:
        """Check if Kratos has published its admin endpoint."""
        return bool(self.admin_url)

    @property
    def byo_sso_callback_url(self) -> str:
        """Kratos's callback for the byo-sso provider.

        Derived from the login browser endpoint (<Kratos public URL>/
        self-service/login/browser) before Kratos confirms it over
        kratos-external-idp; Kratos's answer wins once it comes.
        """
        url = self.login_browser_url.rstrip("/")
        if not url.endswith(KRATOS_LOGIN_BROWSER_PATH):
            return ""
        return _join(url[: -len(KRATOS_LOGIN_BROWSER_PATH)], KRATOS_CALLBACK_PATH)

    def to_env_vars(self) -> EnvVars:
        """Get Kratos info env vars."""
        return {"KRATOS_ADMIN_URL": self.admin_url}

    @classmethod
    def load(cls, requirer: KratosInfoRequirer) -> "KratosInfoData":
        """Load Kratos info from the relation."""
        if not requirer.is_ready():
            return cls()
        try:
            info = requirer.get_kratos_info() or {}
        except KratosInfoRelationError:
            return cls()
        return cls(
            admin_url=info.get("admin_endpoint", ""),
            login_browser_url=info.get("login_browser_endpoint", ""),
        )


@dataclass(frozen=True)
class TenantServiceData:
    """The data source from the tenant-service-info integration."""

    grpc_url: str = ""
    allowed_scope: str = ""

    def to_env_vars(self) -> EnvVars:
        """Get tenant-service env vars."""
        return {"TENANT_SERVICE_GRPC_ADDRESS": self.grpc_url}

    @classmethod
    def load(cls, requirer: TenantServiceInfoRequirer) -> "TenantServiceData":
        """Load the tenant-service gRPC URL and the scope it admits callers by."""
        return cls(
            grpc_url=requirer.get_grpc_url() or "",
            allowed_scope=requirer.get_allowed_scope() or "",
        )


@dataclass(frozen=True)
class OAuthProviderData:
    """The data source from the oauth integration.

    Callers' tokens are verified against the oauth provider's issuer and keys,
    unless authn_issuer is configured (e.g. the Secure Token Service's tokens
    behind the gateway): its keys are at authn_jwks_url or, without it, the
    ones the service discovers from the issuer.
    """

    oidc_issuer_url: str = ""
    allowed_subjects: str = ""
    allowed_scope: str = ""
    client_id: str = ""
    jwks_url: str = ""
    token_endpoint: str = ""
    client_secret: str = ""
    scopes: str = ""

    def to_env_vars(self) -> EnvVars:
        """Get OAuth env vars."""
        allowed_subjects = [s.strip() for s in self.allowed_subjects.split(",") if s.strip()]

        return {
            "AUTHENTICATION_ISSUER": self.oidc_issuer_url,
            "AUTHENTICATION_ALLOWED_SUBJECTS": ",".join(allowed_subjects),
            "AUTHENTICATION_REQUIRED_SCOPE": self.allowed_scope,
            "AUTHENTICATION_JWKS_URL": self.jwks_url,
            "SERVICE_TOKEN_URL": self.token_endpoint,
            "SERVICE_CLIENT_ID": self.client_id,
            "SERVICE_CLIENT_SECRET": self.client_secret,
            "SERVICE_TOKEN_SCOPES": self.scopes,
        }


class OAuthIntegration:
    """Wraps the OAuth integration library."""

    def __init__(self, requirer: OAuthRequirer, tenant_service: TenantServiceData) -> None:
        self._requirer = requirer
        # The scope tenant-service admits callers by: the client has to hold it to ask for it.
        self._token_scope = tenant_service.allowed_scope
        # Without tenant-service's data the client stays as it is: the running
        # service still asks for the scope it was planned with.
        if tenant_service.grpc_url:
            self._requirer.update_client_config(self.oauth_client_config)

    def is_ready(self) -> bool:
        """Check if the oauth integration is ready."""
        return True if self._requirer.is_client_created() else False

    def get_oauth_provider_data(
        self,
        allowed_subjects: str = "",
        allowed_scope: str = "",
        jwks_url: str = "",
        issuer: str = "",
    ) -> OAuthProviderData:
        """Get the OAuth provider data."""
        if self._requirer.is_client_created() and (info := self._requirer.get_provider_info()):
            return OAuthProviderData(
                oidc_issuer_url=issuer or info.issuer_url,
                jwks_url=jwks_url if issuer else info.jwks_endpoint,
                allowed_subjects=allowed_subjects,
                allowed_scope=allowed_scope,
                token_endpoint=info.token_endpoint,
                client_id=info.client_id or "",
                client_secret=info.client_secret or "",
                scopes=self._token_scope,
            )

        return OAuthProviderData()

    @property
    def oauth_client_config(self) -> ClientConfig:
        """The OAuth client config."""
        scope = " ".join(dict.fromkeys(f"{OAUTH_SCOPES} {self._token_scope}".split()))
        client = ClientConfig(
            redirect_uri="https://example.com",
            scope=scope,
            grant_types=OAUTH_GRANT_TYPES,
        )

        return client


@dataclass(frozen=True)
class ByoSSOClient:
    """Kratos's client at hydra-sso, registered over byo-sso-client, and hydra-sso's issuer."""

    client_id: str = ""
    client_secret: str = ""
    issuer_url: str = ""


class ByoSSOClientIntegration:
    """Wraps the OAuth library for Kratos's byo-sso client at hydra-sso.

    The charm registers the client on Kratos's behalf: hydra-sso knows the
    client, Kratos gets its credentials over kratos-external-idp.
    """

    def __init__(self, requirer: OAuthRequirer) -> None:
        self._requirer = requirer

    def update_relation_data(self, redirect_uri: str) -> None:
        """Ask hydra-sso for the client, or update its redirect URI."""
        self._requirer.update_client_config(
            ClientConfig(
                redirect_uri=redirect_uri,
                scope=BYO_SSO_SCOPE,
                grant_types=BYO_SSO_GRANT_TYPES,
            )
        )

    def get_byo_sso_client(self) -> ByoSSOClient:
        """Get the registered client, if hydra-sso created it."""
        if not self._requirer.is_client_created():
            return ByoSSOClient()
        info = self._requirer.get_provider_info()
        if not info or not info.client_id or not info.client_secret:
            return ByoSSOClient()
        return ByoSSOClient(
            client_id=info.client_id, client_secret=info.client_secret, issuer_url=info.issuer_url
        )


class KratosExternalIdpIntegration:
    """Wraps the external_provider library: Kratos's one byo-sso provider."""

    def __init__(self, provider: ExternalIdpProvider) -> None:
        self._provider = provider

    def is_ready(self) -> bool:
        """Check if the kratos-external-idp integration is ready."""
        return self._provider.is_ready()

    @property
    def redirect_uri(self) -> str:
        """The callback Kratos reports for the provider, once it registered it."""
        try:
            return self._provider.get_redirect_uri() or ""
        except Exception:  # the requirer's data may not be there or valid yet
            logger.info("Kratos has not reported the byo-sso callback yet")
            return ""

    def update_relation_data(self, client: ByoSSOClient) -> None:
        """Register (or update) the byo-sso provider at Kratos."""
        providers = ExternalIdpProvider.validate_provider_config([
            {
                "provider": "generic",
                "provider_id": BYO_SSO_PROVIDER_ID,
                "label": BYO_SSO_PROVIDER_LABEL,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "issuer_url": client.issuer_url,
                "scope": BYO_SSO_SCOPE,
                "jsonnet_mapper": BYO_SSO_MAPPER_FILE.read_text(),
            }
        ])
        if providers is None:
            logger.error("The byo-sso provider configuration is invalid")
            return
        self._provider.create_providers(providers)


class LoginUIEndpointsIntegration:
    """Wraps the login_ui_endpoints library: sso-service's pages for hydra-sso."""

    def __init__(self, provider: LoginUIEndpointsProvider) -> None:
        self._provider = provider

    def update_relation_data(self, public_url: str) -> None:
        """Send hydra-sso the login, consent and error URLs."""
        self._provider.send_endpoints_relation_data(
            LoginUIProviderData(
                login_url=_join(public_url, "login"),
                consent_url=_join(public_url, "consent"),
                error_url=_join(public_url, "error"),
                oidc_error_url=_join(public_url, "error"),
            )
        )


class SSOServiceInfoIntegration:
    """Wraps the sso_service_info library."""

    def __init__(self, provider: SSOServiceInfoProvider) -> None:
        self._provider = provider

    def update_relations_app_data(self, grpc_url: str) -> None:
        """Publish the sso-service gRPC URL into all active relation databags."""
        self._provider.update_relations_app_data(grpc_url=grpc_url)


class PeerData:
    """Peer app data: the leader writes the version it migrated to, which wakes the other units."""

    def __init__(self, model: "Model") -> None:
        self._model = model
        self._app = model.app

    def __getitem__(self, key: str) -> dict[str, Any]:
        """Get a value from the peer relation data."""
        if not (peers := self._model.get_relation(PEER_INTEGRATION_NAME)):
            return {}

        value = peers.data[self._app].get(key)
        return json.loads(value) if value else {}

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a value in the peer relation data."""
        if not (peers := self._model.get_relation(PEER_INTEGRATION_NAME)):
            return

        peers.data[self._app][key] = json.dumps(value)

    def pop(self, key: str) -> dict[str, Any]:
        """Remove and return a value from the peer relation data."""
        if not (peers := self._model.get_relation(PEER_INTEGRATION_NAME)):
            return {}

        data = peers.data[self._app].pop(key, None)
        return json.loads(data) if data else {}


@dataclass(frozen=True)
class TLSCertificates:
    """The data source from the certificate transfer integration."""

    ca_bundle: str

    @classmethod
    def load(cls, requirer: CertificateTransferRequires) -> "TLSCertificates":
        """Fetch the CA certificates from all receive-ca-cert integrations."""
        # deal with v1 relations
        ca_certs = requirer.get_all_certificates()

        # deal with v0 relations
        cert_transfer_integrations = requirer.charm.model.relations[
            CERTIFICATE_TRANSFER_INTEGRATION_NAME
        ]

        for integration in cert_transfer_integrations:
            ca = {
                integration.data[unit]["ca"]
                for unit in integration.units
                if "ca" in integration.data.get(unit, {})
            }
            ca_certs.update(ca)

        ca_bundle = "\n".join(sorted(ca_certs))

        return cls(ca_bundle=ca_bundle)
