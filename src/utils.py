# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Utility functions."""

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from ops import ActiveStatus, BlockedStatus, StatusBase

from constants import (
    BYO_SSO_CLIENT_INTEGRATION_NAME,
    DATABASE_INTEGRATION_NAME,
    HYDRA_ENDPOINTS_INTEGRATION_NAME,
    KRATOS_EXTERNAL_IDP_INTEGRATION_NAME,
    KRATOS_INFO_INTEGRATION_NAME,
    LOGIN_UI_ENDPOINTS_INTEGRATION_NAME,
    OAUTH_INTEGRATION_NAME,
    PEER_INTEGRATION_NAME,
    PUBLIC_ROUTE_INTEGRATION_NAME,
    TENANT_SERVICE_INFO_INTEGRATION_NAME,
    WORKLOAD_CONTAINER,
)
from exceptions import MigrationCheckError

if TYPE_CHECKING:
    from charm import SSOServiceOperatorCharm

logger = logging.getLogger(__name__)

Condition = Callable[["SSOServiceOperatorCharm"], bool]


def integration_existence(integration_name: str) -> Condition:
    """Create a condition that checks whether a relation exists."""

    def wrapped(charm: "SSOServiceOperatorCharm") -> bool:
        return bool(charm.model.relations[integration_name])

    return wrapped


database_integration_exists = integration_existence(DATABASE_INTEGRATION_NAME)
peer_integration_exists = integration_existence(PEER_INTEGRATION_NAME)
public_route_integration_exists = integration_existence(PUBLIC_ROUTE_INTEGRATION_NAME)
oauth_integration_exists = integration_existence(OAUTH_INTEGRATION_NAME)
kratos_info_integration_exists = integration_existence(KRATOS_INFO_INTEGRATION_NAME)
tenant_service_info_integration_exists = integration_existence(
    TENANT_SERVICE_INFO_INTEGRATION_NAME
)
hydra_endpoints_integration_exists = integration_existence(HYDRA_ENDPOINTS_INTEGRATION_NAME)
login_ui_endpoints_integration_exists = integration_existence(LOGIN_UI_ENDPOINTS_INTEGRATION_NAME)
byo_sso_client_integration_exists = integration_existence(BYO_SSO_CLIENT_INTEGRATION_NAME)
kratos_external_idp_integration_exists = integration_existence(
    KRATOS_EXTERNAL_IDP_INTEGRATION_NAME
)


def container_connectivity(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if the workload container is reachable."""
    return charm.unit.get_container(WORKLOAD_CONTAINER).can_connect()


def database_resource_is_created(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if the database resource has been created."""
    return charm.database_requirer.is_resource_created()


def migration_is_ready(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if database migrations are up to date."""
    try:
        return not charm.migration_needed
    except MigrationCheckError:
        return False


def public_route_is_secure(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if the public route, once known, uses HTTPS, or the charm runs in dev mode."""
    route = charm._cached_public_route
    return charm._config.dev or not route.is_ready() or route.secured


def public_route_is_ready(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if the public ingress has published its host."""
    return charm._cached_public_route.is_ready()


def tenant_service_info_is_ready(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if tenant-service has published its gRPC address."""
    return bool(charm._cached_tenant_service.grpc_url)


def hydra_endpoints_info_is_ready(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if hydra-sso has published its admin endpoint."""
    return bool(charm._cached_hydra_sso.admin_url)


def kratos_info_is_ready(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if Kratos has published its admin endpoint."""
    return charm._cached_kratos_info.is_ready()


def authentication_config_status(charm: "SSOServiceOperatorCharm") -> StatusBase:
    """Evaluate the authentication configuration and return the appropriate status."""
    oauth_config = charm._config.get_oauth_config()

    if oauth_config.get("authn_jwks_url") and not oauth_config.get("authn_issuer"):
        return BlockedStatus("Invalid configuration: authn_jwks_url is set without authn_issuer")

    return ActiveStatus()


def authentication_config_is_valid(charm: "SSOServiceOperatorCharm") -> bool:
    """Check if the authentication configuration is valid."""
    status = authentication_config_status(charm)
    return isinstance(status, ActiveStatus)


NOOP_CONDITIONS: tuple[Condition, ...] = (
    container_connectivity,
    database_integration_exists,
    database_resource_is_created,
    public_route_is_secure,
    authentication_config_is_valid,
)
