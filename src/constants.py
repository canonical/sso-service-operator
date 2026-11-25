# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Constants."""

from pathlib import Path
from string import Template

POSTGRESQL_DSN_TEMPLATE = Template("postgres://$username:$password@$endpoint/$database")
WORKLOAD_CONTAINER = "sso-service"
WORKLOAD_SERVICE = "sso-service"
PEBBLE_READY_CHECK_NAME = "ready"
ENVELOPE_KEY_SECRET_KEY = "key"
ENVELOPE_KEY_SECRET_LABEL = "envelopekey"
ENVELOPE_KEY_BYTES = 32
LOCAL_CERTIFICATES_PATH = Path("/tmp")
LOCAL_CERTIFICATES_FILE = Path(LOCAL_CERTIFICATES_PATH / "ca-certificates.crt")
LOCAL_CHARM_CERTIFICATES_PATH = Path("/tmp/charm")
LOCAL_CHARM_CERTIFICATES_FILE = Path(LOCAL_CHARM_CERTIFICATES_PATH / "charm-certificates.crt")

SERVICE_COMMAND = "sso-service serve"
PORT = 8080
GRPC_PORT = 50051
OAUTH_GRANT_TYPES = ["client_credentials"]
OAUTH_SCOPES = "openid"
CERTIFICATES_PATH = Path("/etc/ssl/certs/")
CERTIFICATES_FILE = Path(CERTIFICATES_PATH / "ca-certificates.crt")
# What `juju status` shows of a status message.
STATUS_MESSAGE_LENGTH = 120

PUBLIC_PATH_PREFIX = "/sso"
PUBLIC_PAGES = ("login", "consent", "error")
PUBLIC_CALLBACK_PREFIX = "/callback/"
MANAGEMENT_PATH_PREFIXES = ("/api/v0/sso/tenants", "/api/v0/sso/connections")
INGRESS_HTTP_PORT = 80
INGRESS_HTTPS_PORT = 443

BYO_SSO_PROVIDER_ID = "byo-sso"
BYO_SSO_PROVIDER_LABEL = "SSO"
BYO_SSO_SCOPE = "openid email"
BYO_SSO_GRANT_TYPES = ["authorization_code"]
BYO_SSO_MAPPER_FILE = Path("templates/byo-sso.jsonnet")
KRATOS_CALLBACK_PATH = f"self-service/methods/oidc/callback/{BYO_SSO_PROVIDER_ID}"
KRATOS_LOGIN_BROWSER_PATH = "self-service/login/browser"

INTERNAL_ROUTE_INTEGRATION_NAME = "internal-route"
PUBLIC_ROUTE_INTEGRATION_NAME = "public-route"
PROMETHEUS_SCRAPE_INTEGRATION_NAME = "metrics-endpoint"
LOGGING_INTEGRATION_NAME = "logging"
GRAFANA_DASHBOARD_INTEGRATION_NAME = "grafana-dashboard"
TEMPO_TRACING_INTEGRATION_NAME = "tracing"
HYDRA_ENDPOINTS_INTEGRATION_NAME = "hydra-endpoint-info"
KRATOS_INFO_INTEGRATION_NAME = "kratos-info"
KRATOS_EXTERNAL_IDP_INTEGRATION_NAME = "kratos-external-idp"
DATABASE_INTEGRATION_NAME = "pg-database"
MIGRATION_COMPLETED = "migration_completed"
PEER_INTEGRATION_NAME = "sso-service"
OAUTH_INTEGRATION_NAME = "oauth"
BYO_SSO_CLIENT_INTEGRATION_NAME = "byo-sso-client"
CERTIFICATE_TRANSFER_INTEGRATION_NAME = "receive-ca-cert"
TENANT_SERVICE_INFO_INTEGRATION_NAME = "tenant-service-info"
LOGIN_UI_ENDPOINTS_INTEGRATION_NAME = "ui-endpoint-info"
