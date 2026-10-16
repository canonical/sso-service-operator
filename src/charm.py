#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for the Identity Platform SSO Service (Bring Your Own SSO)."""

import logging
import subprocess
from functools import cached_property

import ops
import requests
from charmlibs.interfaces.istio_ingress_route import IstioIngressRouteRequirer
from charmlibs.interfaces.oauth import ClientConfigError, OAuthRequirer
from charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.hydra.v0.hydra_endpoints import HydraEndpointsRequirer
from charms.identity_platform_login_ui_operator.v0.login_ui_endpoints import (
    LoginUIEndpointsProvider,
)
from charms.kratos.v0.kratos_info import KratosInfoRequirer
from charms.kratos_external_idp_integrator.v1.kratos_external_provider import (
    ExternalIdpProvider,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    ResourceRequirements,
    adjust_resource_requirements,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
from charms.tenant_service.v0.tenant_service_info import TenantServiceInfoRequirer
from sso_service_info import SSOServiceInfoProvider

from cli import CommandLine
from clients import HTTPClient
from configs import CharmConfig
from constants import (
    BYO_SSO_CLIENT_INTEGRATION_NAME,
    CERTIFICATE_TRANSFER_INTEGRATION_NAME,
    CLIENT_SECRET_KEY,
    DATABASE_INTEGRATION_NAME,
    ENVELOPE_KEY_SECRET_KEY,
    ENVELOPE_KEY_SECRET_LABEL,
    GRAFANA_DASHBOARD_INTEGRATION_NAME,
    GRPC_PORT,
    HYDRA_ENDPOINTS_INTEGRATION_NAME,
    INTERNAL_ROUTE_INTEGRATION_NAME,
    KRATOS_EXTERNAL_IDP_INTEGRATION_NAME,
    KRATOS_INFO_INTEGRATION_NAME,
    LOCAL_CERTIFICATES_PATH,
    LOCAL_CHARM_CERTIFICATES_FILE,
    LOCAL_CHARM_CERTIFICATES_PATH,
    LOGGING_INTEGRATION_NAME,
    LOGIN_UI_ENDPOINTS_INTEGRATION_NAME,
    MIGRATION_COMPLETED,
    OAUTH_INTEGRATION_NAME,
    PEBBLE_READY_CHECK_NAME,
    PEER_INTEGRATION_NAME,
    PORT,
    PROMETHEUS_SCRAPE_INTEGRATION_NAME,
    PUBLIC_ROUTE_INTEGRATION_NAME,
    STATUS_MESSAGE_LENGTH,
    TEMPO_TRACING_INTEGRATION_NAME,
    TENANT_SERVICE_INFO_INTEGRATION_NAME,
    WORKLOAD_CONTAINER,
)
from exceptions import (
    CharmError,
    InvalidConfigError,
    MigrationCheckError,
    MigrationError,
    PebbleError,
)
from integrations import (
    ByoSSOClientIntegration,
    DatabaseConfig,
    HydraSSOData,
    InternalIngressData,
    KratosExternalIdpIntegration,
    KratosInfoData,
    LoginUIEndpointsIntegration,
    OAuthIntegration,
    PeerData,
    PublicRouteData,
    SSOServiceInfoIntegration,
    TenantServiceData,
    TLSCertificates,
    TracingData,
)
from secret import Secrets, generate_envelope_key, get_initial_envelope_key
from services import PebbleService, WorkloadService
from utils import (
    NOOP_CONDITIONS,
    authentication_config_status,
    byo_sso_client_integration_exists,
    container_connectivity,
    database_integration_exists,
    database_resource_is_created,
    hydra_endpoints_info_is_ready,
    hydra_endpoints_integration_exists,
    kratos_external_idp_integration_exists,
    kratos_info_integration_exists,
    kratos_info_is_ready,
    login_ui_endpoints_integration_exists,
    migration_is_ready,
    oauth_integration_exists,
    peer_integration_exists,
    public_route_integration_exists,
    public_route_is_ready,
    public_route_is_secure,
    tenant_service_info_integration_exists,
    tenant_service_info_is_ready,
)

logger = logging.getLogger(__name__)


class SSOServiceOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self._migration_error = ""
        self._container = self.unit.get_container(WORKLOAD_CONTAINER)
        self._cli = CommandLine(self._container)
        self.peer_data = PeerData(self.model)
        self._workload_service = WorkloadService(self.unit)
        self._pebble_service = PebbleService(self.unit)
        self._secrets = Secrets(self.model)
        self._config = CharmConfig(self.config)

        self.database_requirer = DatabaseRequires(
            self,
            relation_name=DATABASE_INTEGRATION_NAME,
            database_name=f"{self.model.name}_{self.app.name}",
        )

        self.public_route = IstioIngressRouteRequirer(
            self,
            relation_name=PUBLIC_ROUTE_INTEGRATION_NAME,
        )

        self.internal_ingress = IstioIngressRouteRequirer(
            self,
            relation_name=INTERNAL_ROUTE_INTEGRATION_NAME,
        )

        self.oauth_requirer = OAuthRequirer(self, relation_name=OAUTH_INTEGRATION_NAME)

        self.byo_sso_requirer = OAuthRequirer(self, relation_name=BYO_SSO_CLIENT_INTEGRATION_NAME)
        self.byo_sso_client_integration = ByoSSOClientIntegration(self.byo_sso_requirer)

        self.hydra_endpoints_requirer = HydraEndpointsRequirer(
            self, relation_name=HYDRA_ENDPOINTS_INTEGRATION_NAME
        )
        self.kratos_info_requirer = KratosInfoRequirer(
            self, relation_name=KRATOS_INFO_INTEGRATION_NAME
        )
        self.tenant_service_info_requirer = TenantServiceInfoRequirer(self)
        self.oauth_integration = OAuthIntegration(self.oauth_requirer, self._cached_tenant_service)

        self.login_ui_endpoints_provider = LoginUIEndpointsProvider(self)
        self.login_ui_endpoints_integration = LoginUIEndpointsIntegration(
            self.login_ui_endpoints_provider
        )

        self.external_idp_provider = ExternalIdpProvider(
            self, relation_name=KRATOS_EXTERNAL_IDP_INTEGRATION_NAME
        )
        self.kratos_external_idp_integration = KratosExternalIdpIntegration(
            self.external_idp_provider
        )

        self.sso_service_info_provider = SSOServiceInfoProvider(self)
        self.sso_service_info_integration = SSOServiceInfoIntegration(
            self.sso_service_info_provider
        )

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            relation_name=PROMETHEUS_SCRAPE_INTEGRATION_NAME,
            jobs=[
                {
                    "job_name": "sso_service_metrics",
                    "metrics_path": "/api/v0/metrics",
                    "static_configs": [
                        {
                            "targets": [f"*:{PORT}"],
                        }
                    ],
                }
            ],
        )

        self.resources_patch = KubernetesComputeResourcesPatch(
            self,
            WORKLOAD_CONTAINER,
            resource_reqs_func=self._resource_reqs_from_config,
        )

        self.certificate_transfer_requirer = CertificateTransferRequires(
            self,
            relationship_name=CERTIFICATE_TRANSFER_INTEGRATION_NAME,
        )

        # Pebble events
        self.framework.observe(self.on.sso_service_pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on.sso_service_pebble_check_failed, self._on_pebble_check_failed
        )
        self.framework.observe(
            self.on.sso_service_pebble_check_recovered, self._on_pebble_check_recovered
        )

        # Lifecycle events
        self.framework.observe(self.on.config_changed, self._on_holistic_handler)
        self.framework.observe(self.on.leader_elected, self._on_holistic_handler)
        self.framework.observe(self.on.upgrade_charm, self._on_holistic_handler)
        self.framework.observe(self.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(self.on.secret_changed, self._on_holistic_handler)
        self.framework.observe(self.on.update_status, self._on_holistic_handler)

        # Actions
        self.framework.observe(self.on.run_migration_action, self._on_run_migration_action)
        self.framework.observe(self.on.get_envelope_key_action, self._on_get_envelope_key_action)
        self.framework.observe(self.on.list_connections_action, self._on_list_connections_action)
        self.framework.observe(self.on.get_connection_action, self._on_get_connection_action)
        self.framework.observe(self.on.create_connection_action, self._on_create_connection_action)
        self.framework.observe(self.on.update_connection_action, self._on_update_connection_action)
        self.framework.observe(self.on.delete_connection_action, self._on_delete_connection_action)
        self.framework.observe(self.on.test_connection_action, self._on_test_connection_action)
        self.framework.observe(self.on.get_policy_action, self._on_get_policy_action)
        self.framework.observe(self.on.set_policy_action, self._on_set_policy_action)
        self.framework.observe(self.on.get_domains_action, self._on_get_domains_action)
        self.framework.observe(self.on.set_domains_action, self._on_set_domains_action)

        # Hydra endpoints relation
        self.framework.observe(
            self.on[HYDRA_ENDPOINTS_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[HYDRA_ENDPOINTS_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )

        # Kratos info relation
        self.framework.observe(
            self.on[KRATOS_INFO_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[KRATOS_INFO_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )

        # Kratos external IdP relation
        self.framework.observe(self.external_idp_provider.on.ready, self._on_holistic_handler)
        self.framework.observe(
            self.external_idp_provider.on.redirect_uri_changed, self._on_holistic_handler
        )

        # Tenant service info relation
        self.framework.observe(
            self.tenant_service_info_requirer.on.tenant_service_info_changed,
            self._on_holistic_handler,
        )
        self.framework.observe(
            self.tenant_service_info_requirer.on.tenant_service_info_removed,
            self._on_holistic_handler,
        )

        # Login UI endpoints relation
        self.framework.observe(
            self.login_ui_endpoints_provider.on.ready, self._on_holistic_handler
        )

        # SSO service info relation
        self.framework.observe(self.sso_service_info_provider.on.ready, self._on_holistic_handler)

        # OAuth relation
        self.framework.observe(
            self.oauth_requirer.on.oauth_info_changed,
            self._on_holistic_handler,
        )
        self.framework.observe(
            self.oauth_requirer.on.oauth_info_removed,
            self._on_holistic_handler,
        )

        # byo-sso-client relation
        self.framework.observe(
            self.on[BYO_SSO_CLIENT_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[BYO_SSO_CLIENT_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )
        self.framework.observe(
            self.byo_sso_requirer.on.oauth_info_changed,
            self._on_holistic_handler,
        )
        self.framework.observe(
            self.byo_sso_requirer.on.oauth_info_removed,
            self._on_holistic_handler,
        )

        # Certificate transfer relation
        self.framework.observe(
            self.certificate_transfer_requirer.on.certificate_set_updated,
            self._on_holistic_handler,
        )
        self.framework.observe(
            self.certificate_transfer_requirer.on.certificates_removed,
            self._on_holistic_handler,
        )

        # COS relations
        # The log alert selects on the labels Pebble's forwarding gives the streams,
        # which are not the ones the library's topology labeling selects on.
        self._log_forwarder = LogForwarder(
            self, relation_name=LOGGING_INTEGRATION_NAME, skip_alert_topology_labeling=True
        )

        self._grafana_dashboards = GrafanaDashboardProvider(
            self,
            relation_name=GRAFANA_DASHBOARD_INTEGRATION_NAME,
        )

        self.tracing_requirer = TracingEndpointRequirer(
            self,
            relation_name=TEMPO_TRACING_INTEGRATION_NAME,
            protocols=["otlp_http", "otlp_grpc"],
        )
        self.framework.observe(
            self.tracing_requirer.on.endpoint_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.tracing_requirer.on.endpoint_removed, self._on_holistic_handler
        )

        # Peer relation
        self.framework.observe(
            self.on[PEER_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[PEER_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )

        # Resource patching
        self.framework.observe(
            self.resources_patch.on.patch_failed, self._on_resource_patch_failed
        )

        # Database
        self.framework.observe(
            self.database_requirer.on.database_created, self._on_holistic_handler
        )
        self.framework.observe(
            self.database_requirer.on.endpoints_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[DATABASE_INTEGRATION_NAME].relation_broken,
            self._on_database_integration_broken,
        )

        # Public route
        # The relation's own events, as for the internal route: the route
        # library's `ready` reaches only the leader.
        self.framework.observe(
            self.on[PUBLIC_ROUTE_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[PUBLIC_ROUTE_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )

        # Internal route
        self.framework.observe(
            self.on[INTERNAL_ROUTE_INTEGRATION_NAME].relation_changed, self._on_holistic_handler
        )
        self.framework.observe(
            self.on[INTERNAL_ROUTE_INTEGRATION_NAME].relation_broken, self._on_holistic_handler
        )

    @cached_property
    def _cached_public_route(self) -> PublicRouteData:
        """Public route data, computed once per charm instance."""
        return PublicRouteData.load(self.public_route)

    @cached_property
    def _cached_database_config(self) -> DatabaseConfig:
        """Database config, computed once per charm instance."""
        return DatabaseConfig.load(self.database_requirer)

    @cached_property
    def _cached_hydra_sso(self) -> HydraSSOData:
        """hydra-sso data, computed once per charm instance."""
        return HydraSSOData.load(self.hydra_endpoints_requirer)

    @cached_property
    def _cached_kratos_info(self) -> KratosInfoData:
        """Kratos info data, computed once per charm instance."""
        return KratosInfoData.load(self.kratos_info_requirer)

    @cached_property
    def _cached_tenant_service(self) -> TenantServiceData:
        """tenant-service data, computed once per charm instance."""
        return TenantServiceData.load(self.tenant_service_info_requirer)

    @cached_property
    def _cached_internal_ingress(self) -> InternalIngressData:
        """Internal ingress data, computed once per charm instance."""
        return InternalIngressData.load(self.internal_ingress)

    @cached_property
    def _cached_ca_bundle(self) -> str:
        """CA bundle, computed once per charm instance.

        A bundle sent as unit data is consumed by the library when it is read.
        """
        return TLSCertificates.load(self.certificate_transfer_requirer).ca_bundle

    @cached_property
    def _cached_migration_check(self) -> bool | MigrationCheckError:
        """Migration check result or its error, computed once per charm instance."""
        database_config = self._cached_database_config
        try:
            return self._cli.migration_check(dsn=database_config.dsn)
        except MigrationCheckError as e:
            return e

    @property
    def _pebble_layer(self) -> ops.pebble.Layer:
        """Build the pebble layer from all env var sources."""
        oauth_config = self._config.get_oauth_config()
        oauth_provider_data = self.oauth_integration.get_oauth_provider_data(
            allowed_subjects=oauth_config.get("authn_allowed_subjects") or "",
            allowed_scope=oauth_config.get("authn_allowed_scope") or "",
            jwks_url=oauth_config.get("authn_jwks_url") or "",
            issuer=oauth_config.get("authn_issuer") or "",
        )

        return self._pebble_service.render_pebble_layer(
            TracingData.load(self.tracing_requirer),
            self._cached_database_config,
            self._secrets,
            self._config,
            self._cached_public_route,
            self._cached_hydra_sso,
            self._cached_kratos_info,
            self._cached_tenant_service,
            oauth_provider_data,
        )

    @property
    def _grpc_url(self) -> str:
        """The gRPC service URL for the sso-service."""
        return f"{self.app.name}.{self.model.name}.svc.cluster.local:{GRPC_PORT}"

    @property
    def migration_needed(self) -> bool:
        """Check if database migration is needed."""
        if not self.database_requirer.is_resource_created():
            return False

        # The workload is asked once a hook, whatever it answers.
        if isinstance(check := self._cached_migration_check, MigrationCheckError):
            raise check
        return not check

    def _ensure_secrets(self) -> bool:
        """Ensure the charm secrets are created."""
        if self._secrets.is_ready():
            return True

        if self.unit.is_leader():
            try:
                initial_key = get_initial_envelope_key(
                    self.model, self._config.initial_envelope_key_secret_id
                )
            except InvalidConfigError as e:
                logger.error("Cannot use the initial envelope key: %s", e)
                return False

            self._secrets[ENVELOPE_KEY_SECRET_LABEL] = {
                ENVELOPE_KEY_SECRET_KEY: initial_key or generate_envelope_key()
            }
            return True
        return False

    def _ensure_public_route(self) -> bool:
        """Ensure the public route configuration is submitted."""
        # An insecure public route is not applied: the one submitted before stays.
        if (
            self.unit.is_leader()
            and public_route_is_secure(self)
            and self.public_route.is_ready()
            and (config := self._cached_public_route.config)
        ):
            self.public_route.submit_config(config)
        return True

    def _ensure_internal_ingress(self) -> bool:
        """Ensure the internal ingress configuration is submitted."""
        if (
            self.unit.is_leader()
            and self.internal_ingress.is_ready()
            and (config := self._cached_internal_ingress.config)
        ):
            self.internal_ingress.submit_config(config)
        return True

    def _ensure_login_ui_endpoints(self) -> bool:
        """Ensure the ui-endpoint-info relation data is up to date."""
        if (
            self.unit.is_leader()
            and public_route_is_secure(self)
            and (url := self._cached_public_route.url)
        ):
            self.login_ui_endpoints_integration.update_relation_data(str(url))
        return True

    def _ensure_sso_service_info(self) -> bool:
        """Ensure the sso-service-info relation data is published."""
        if self.unit.is_leader():
            self.sso_service_info_integration.update_relations_app_data(self._grpc_url)
        return True

    def _ensure_byo_sso(self) -> bool:
        """Ensure Kratos's byo-sso client and provider are registered.

        The client is registered at hydra-sso, then the provider at Kratos. The
        client's redirect URI is Kratos's byo-sso callback: the one Kratos
        reports over kratos-external-idp, or, before Kratos registered the
        provider, the one derived from its public URL. Not needed to start the
        service, so it never holds the plan back.
        """
        if not self.unit.is_leader():
            return True

        redirect_uri = (
            self.kratos_external_idp_integration.redirect_uri
            or self._cached_kratos_info.byo_sso_callback_url
        )
        if redirect_uri and byo_sso_client_integration_exists(self):
            try:
                self.byo_sso_client_integration.update_relation_data(redirect_uri)
            except ClientConfigError as e:
                logger.error("Cannot register Kratos's byo-sso client: %s", e)
                return True

        client = self.byo_sso_client_integration.get_byo_sso_client()
        if (
            client.client_id
            and client.issuer_url
            and self.kratos_external_idp_integration.is_ready()
        ):
            self.kratos_external_idp_integration.update_relation_data(client)
        return True

    def _ensure_database_migration(self) -> bool:
        """Ensure database migrations are up to date."""
        if migration_is_ready(self):
            return True

        if isinstance(self._cached_migration_check, MigrationCheckError):
            # Whether one is pending is not known: nothing is migrated or planned on that.
            return False

        if not self.unit.is_leader():
            logger.info(
                "Unit does not have leadership. Wait for leader unit to run the migration."
            )
            return False

        database_config = self._cached_database_config
        try:
            self._cli.migrate_up(dsn=database_config.dsn)
        except MigrationError as e:
            logger.error("Auto migration job failed. Please use the run-migration action")
            self._migration_error = str(e)
            return False

        # What the check answered before the migration no longer holds.
        self.__dict__["_cached_migration_check"] = True
        self.peer_data[MIGRATION_COMPLETED] = self._workload_service.version
        return True

    def _ensure_workload_environment(self) -> bool:
        """Ensure everything the service refuses to start without is known."""
        return (
            self._secrets.is_ready()
            and public_route_is_ready(self)
            and tenant_service_info_is_ready(self)
            and self.oauth_integration.is_ready()
            and hydra_endpoints_info_is_ready(self)
            and kratos_info_is_ready(self)
        )

    def _ensure_tls(self) -> bool:
        """Ensure TLS certificates are updated on both the charm and workload."""
        LOCAL_CHARM_CERTIFICATES_FILE.parent.mkdir(parents=True, exist_ok=True)

        certificates = self._cached_ca_bundle
        # No newline translation: a bundle with CRLF line endings has to equal its copy.
        existing = (
            LOCAL_CHARM_CERTIFICATES_FILE.read_bytes().decode()
            if LOCAL_CHARM_CERTIFICATES_FILE.exists()
            else ""
        )

        if certificates == existing:
            return True

        if certificates:
            LOCAL_CHARM_CERTIFICATES_FILE.write_text(certificates)
        else:
            LOCAL_CHARM_CERTIFICATES_FILE.unlink(missing_ok=True)

        try:
            subprocess.run(
                [
                    "update-ca-certificates",
                    "--fresh",
                    "--etccertsdir",
                    str(LOCAL_CERTIFICATES_PATH),
                    "--localcertsdir",
                    str(LOCAL_CHARM_CERTIFICATES_PATH),
                ],
                check=True,
            )
            self._tls_cert_changed = self._workload_service.update_ca_certs()
        # OSError: a request to Pebble that times out, or a missing binary.
        except (subprocess.CalledProcessError, ops.pebble.Error, OSError):
            logger.exception("Failed to update CA certificates")
            # Put the earlier copy back so the next reconciliation retries.
            if existing:
                LOCAL_CHARM_CERTIFICATES_FILE.write_text(existing)
            else:
                LOCAL_CHARM_CERTIFICATES_FILE.unlink(missing_ok=True)
            return False
        return True

    def _on_holistic_handler(self, event: ops.EventBase) -> None:
        """Entry point for the centralized reconciliation handler.

        Sets the unit to MaintenanceStatus while reconciling, then delegates
        to _holistic_handler.
        """
        self.unit.status = ops.MaintenanceStatus("Configuring resources")
        self._holistic_handler(event)

    def _holistic_handler(self, event: ops.EventBase) -> None:
        """Centralized reconciliation handler."""
        # The related applications wait for these, which need neither the workload
        # nor the database: they come before the no-op conditions, and none of
        # them holds another back.
        for f in [
            self._ensure_secrets,
            self._ensure_public_route,
            self._ensure_internal_ingress,
            self._ensure_login_ui_endpoints,
            self._ensure_sso_service_info,
            self._ensure_byo_sso,
        ]:
            try:
                f()
            except CharmError:
                logger.exception("Error in %s", f.__name__)

        if not all(condition(self) for condition in NOOP_CONDITIONS):
            return

        self._tls_cert_changed = False
        can_plan = True
        for f in [
            self._ensure_database_migration,
            self._ensure_workload_environment,
            self._ensure_tls,
        ]:
            try:
                can_plan = can_plan and f()
            except CharmError:
                logger.exception("Error in %s", f.__name__)
                can_plan = False

        if not can_plan:
            return

        try:
            # force_restart=True when the CA bundle changed: Go's crypto/x509
            # loads the system cert pool once via sync.Once on the first TLS
            # dial; pushing a new ca-certificates.crt into the container is
            # not picked up by the running process without a restart.
            self._pebble_service.plan(self._pebble_layer, force_restart=self._tls_cert_changed)
        except PebbleError:
            logger.error(
                "Failed to plan pebble layer, please check the %s container logs",
                WORKLOAD_CONTAINER,
            )

    def _get_migration_status(self) -> ops.StatusBase | None:
        """Migration status for collect-status."""
        if self._migration_error:
            return self._failed("Database migration failed", self._migration_error)

        try:
            is_migration_ready = not self.migration_needed
        except MigrationCheckError as e:
            return self._failed("Migration check failed", str(e))

        if not is_migration_ready:
            if self.unit.is_leader():
                return ops.WaitingStatus("Waiting for database migration")
            return ops.WaitingStatus("Waiting for leader unit to run the migration")
        return None

    def _get_initial_envelope_key_status(self) -> ops.StatusBase | None:
        """Initial envelope key status for collect-status."""
        key = self._secrets.envelope_key if self._secrets.is_ready() else ""
        try:
            initial_key = get_initial_envelope_key(
                self.model, self._config.initial_envelope_key_secret_id
            )
        except InvalidConfigError as e:
            if not key:
                return ops.BlockedStatus(f"Invalid configuration: {e}")
            logger.error("Cannot compare the envelope key in use with the configured one: %s", e)
            return ops.BlockedStatus(
                "Cannot compare initial_envelope_key_secret_id with the key in use (unchanged): "
                "grant or fix its secret, or unset it"
            )
        if key and initial_key and key != initial_key:
            return ops.BlockedStatus(
                "initial_envelope_key_secret_id is not the key in use (unchanged): "
                "remove and redeploy the application to change it"
            )
        return None

    @staticmethod
    def _failed(what: str, reason: str) -> ops.BlockedStatus:
        """Build a blocked status that fits in `juju status`.

        A reason that is too long keeps its end, where the cause is; the log has
        the whole reason.

        Args:
            what: What failed.
            reason: Why it failed.

        Returns:
            The blocked status.
        """
        message = f"{what}: {reason}"
        if len(message) > STATUS_MESSAGE_LENGTH:
            message = f"{what}: ...{reason[len(message) - STATUS_MESSAGE_LENGTH + 3 :]}"
        return ops.BlockedStatus(message)

    # Event handlers

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Handle the pebble-ready event."""
        self._workload_service.open_port()
        # A workload container that restarted has lost the CA bundle: forget
        # the charm's copy, so that the bundle is pushed again.
        LOCAL_CHARM_CERTIFICATES_FILE.unlink(missing_ok=True)
        self._on_holistic_handler(event)
        self._workload_service.set_version()

    def _on_pebble_check_failed(self, event: ops.PebbleCheckFailedEvent) -> None:
        """Handle the pebble-check-failed event."""
        if event.info.name == PEBBLE_READY_CHECK_NAME:
            logger.warning("The service is not running")

    def _on_pebble_check_recovered(self, event: ops.PebbleCheckRecoveredEvent) -> None:
        """Handle the pebble-check-recovered event."""
        if event.info.name == PEBBLE_READY_CHECK_NAME:
            logger.info("The service is online again")

    def _on_database_integration_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle the database relation-broken event."""
        if self._container.can_connect():
            try:
                self._container.stop(WORKLOAD_CONTAINER)
            except ops.pebble.Error:
                logger.warning("Failed to stop workload service after database relation broken")

    def _on_resource_patch_failed(self, event: K8sResourcePatchFailedEvent) -> None:
        """Handle the resource-patch-failed event."""
        logger.error("Resource patching failed: %s", event.message)
        self._on_holistic_handler(event)

    # Status

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Evaluate and report the unit status."""
        can_connect = container_connectivity(self)
        if not can_connect:
            event.add_status(ops.WaitingStatus("Container is not connected yet"))

        if configs := self._config.get_missing_config_keys():
            event.add_status(ops.BlockedStatus(f"Missing required configuration: {configs}"))

        event.add_status(authentication_config_status(self))

        if status := self._get_initial_envelope_key_status():
            event.add_status(status)

        if not self._secrets.is_ready():
            event.add_status(ops.WaitingStatus("Waiting for secrets creation"))

        if not peer_integration_exists(self):
            event.add_status(ops.WaitingStatus(f"Missing integration {PEER_INTEGRATION_NAME}"))

        self._collect_integration_statuses(event)
        self._collect_integration_data_statuses(event)

        # Before the service's own state: a pending migration is why it waits.
        if can_connect and (migration_status := self._get_migration_status()):
            event.add_status(migration_status)

        if can_connect and self._workload_service.is_failing():
            event.add_status(
                ops.BlockedStatus(
                    f"Failed to start the service, please check the "
                    f"{WORKLOAD_CONTAINER} container logs"
                )
            )

        if can_connect and not self._workload_service.is_running():
            event.add_status(ops.WaitingStatus("Waiting for the service to start"))

        event.add_status(self.resources_patch.get_status())
        event.add_status(ops.ActiveStatus())

    def _collect_integration_statuses(self, event: ops.CollectStatusEvent) -> None:
        """Collect statuses for required integrations."""
        if not database_integration_exists(self):
            event.add_status(ops.BlockedStatus(f"Missing integration {DATABASE_INTEGRATION_NAME}"))

        if not public_route_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {PUBLIC_ROUTE_INTEGRATION_NAME}")
            )

        if not oauth_integration_exists(self):
            event.add_status(ops.BlockedStatus(f"Missing integration {OAUTH_INTEGRATION_NAME}"))

        if not kratos_info_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {KRATOS_INFO_INTEGRATION_NAME}")
            )

        if not tenant_service_info_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {TENANT_SERVICE_INFO_INTEGRATION_NAME}")
            )

        if not hydra_endpoints_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {HYDRA_ENDPOINTS_INTEGRATION_NAME}")
            )

        if not login_ui_endpoints_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {LOGIN_UI_ENDPOINTS_INTEGRATION_NAME}")
            )

        if not byo_sso_client_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {BYO_SSO_CLIENT_INTEGRATION_NAME}")
            )

        if not kratos_external_idp_integration_exists(self):
            event.add_status(
                ops.BlockedStatus(f"Missing integration {KRATOS_EXTERNAL_IDP_INTEGRATION_NAME}")
            )

    def _collect_integration_data_statuses(self, event: ops.CollectStatusEvent) -> None:
        """Collect statuses for the data of required integrations."""
        if not public_route_is_secure(self):
            # The browser-binding cookie is __Host- and Secure: browsers drop it
            # over plain HTTP (except on localhost), so SSO sign-ins fail.
            event.add_status(
                ops.BlockedStatus(
                    "Requires a secure (HTTPS) public ingress: "
                    "enable HTTPS on it, or set 'dev' for development"
                )
            )

        if not database_resource_is_created(self):
            event.add_status(ops.WaitingStatus("Waiting for database creation"))

        if not public_route_is_ready(self):
            event.add_status(ops.WaitingStatus("Waiting for the public route"))

        # Before the client, which is asked for with tenant-service's scope.
        if not tenant_service_info_is_ready(self):
            event.add_status(ops.WaitingStatus("Waiting for tenant-service's address"))

        if not self.oauth_integration.is_ready():
            event.add_status(ops.WaitingStatus("Waiting for the oauth client"))

        if not hydra_endpoints_info_is_ready(self):
            event.add_status(ops.WaitingStatus("Waiting for hydra-sso's endpoints"))

        if not kratos_info_is_ready(self):
            event.add_status(ops.WaitingStatus("Waiting for Kratos's info"))

        if not self.byo_sso_client_integration.get_byo_sso_client().client_id:
            event.add_status(
                ops.WaitingStatus("Waiting for hydra-sso to register the byo-sso client")
            )

    # Actions

    def _get_management_token(self) -> str | None:
        """OAuth access token for internal management API calls.

        Returns:
            An access token if OAuth is configured and the exchange succeeds,
            otherwise None. The CLI then sends a placeholder, which the service
            refuses.
        """
        provider_info = self.oauth_requirer.get_provider_info()
        if not provider_info or not provider_info.client_id or not provider_info.client_secret:
            return None
        try:
            with HTTPClient(
                token_url=provider_info.token_endpoint, **self._config.get_proxy_config()
            ) as client:
                return client.get_access_token(
                    client_id=provider_info.client_id,
                    client_secret=provider_info.client_secret,
                )
        except (requests.RequestException, KeyError, ValueError):
            logger.warning("Failed to obtain management token")
            return None

    def _get_client_secret(self, secret_id: str | None) -> str | None:
        """Get an identity provider's client secret from the Juju secret an action names.

        Args:
            secret_id: The value of the action's client-secret-id parameter.

        Returns:
            The client secret, or None when the action names no secret.

        Raises:
            InvalidConfigError: If the secret cannot be read or holds no client secret.
        """
        if not secret_id:
            return None

        try:
            content = self.model.get_secret(id=secret_id).get_content(refresh=True)
        except (ops.SecretNotFoundError, ops.ModelError) as e:
            raise InvalidConfigError(
                f"Cannot read the secret {secret_id}: grant it to this application"
            ) from e

        # A secret added from a file ends with the file's newline.
        if not (client_secret := content.get(CLIENT_SECRET_KEY, "").rstrip("\r\n")):
            raise InvalidConfigError(f"The secret {secret_id} has no `{CLIENT_SECRET_KEY}` entry")
        return client_secret

    def _on_run_migration_action(self, event: ops.ActionEvent) -> None:
        """Handle the run-migration action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return
        if not database_resource_is_created(self):
            event.fail("The database is not ready")
            return
        try:
            self._cli.migrate_up(
                dsn=self._cached_database_config.dsn, timeout=event.params.get("timeout", 120)
            )
        except MigrationError as e:
            event.fail(f"Database migration failed: {e}")
            return
        if self.unit.is_leader():
            self.peer_data[MIGRATION_COMPLETED] = self._workload_service.version
        event.log("Database migration succeeded")
        self._on_holistic_handler(event)

    def _on_get_envelope_key_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-envelope-key action."""
        if not self._secrets.is_ready():
            event.fail("Juju secrets are not ready yet")
            return

        event.log("Successfully fetched the envelope key")
        event.set_results({"key": self._secrets.envelope_key})

    def _on_list_connections_action(self, event: ops.ActionEvent) -> None:
        """Handle the list-connections action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.list_connections(
                tenant_id=event.params.get("tenant-id"),
                page_size=event.params.get("page-size"),
                page_token=event.params.get("page-token"),
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to list connections: {e}")

    def _on_get_connection_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-connection action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.get_connection(
                tenant_id=event.params["tenant-id"],
                connection_id=event.params["connection-id"],
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to get connection: {e}")

    def _on_create_connection_action(self, event: ops.ActionEvent) -> None:
        """Handle the create-connection action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.create_connection(
                tenant_id=event.params["tenant-id"],
                label=event.params["label"],
                issuer=event.params["issuer"],
                client_id=event.params["client-id"],
                client_secret=self._get_client_secret(event.params["client-secret-id"]),
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to create connection: {e}")

    def _on_update_connection_action(self, event: ops.ActionEvent) -> None:
        """Handle the update-connection action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.update_connection(
                tenant_id=event.params["tenant-id"],
                connection_id=event.params["connection-id"],
                label=event.params.get("label"),
                client_secret=self._get_client_secret(event.params.get("client-secret-id")),
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to update connection: {e}")

    def _on_delete_connection_action(self, event: ops.ActionEvent) -> None:
        """Handle the delete-connection action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.delete_connection(
                connection_id=event.params["connection-id"],
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to delete connection: {e}")

    def _on_test_connection_action(self, event: ops.ActionEvent) -> None:
        """Handle the test-connection action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.test_connection(
                tenant_id=event.params["tenant-id"],
                connection_id=event.params["connection-id"],
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to test connection: {e}")

    def _on_get_policy_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-policy action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.get_policy(
                tenant_id=event.params["tenant-id"],
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to get policy: {e}")

    def _on_set_policy_action(self, event: ops.ActionEvent) -> None:
        """Handle the set-policy action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.set_policy(
                tenant_id=event.params["tenant-id"],
                enforcement=event.params["enforcement"],
                bindings=event.params.get("bindings"),
                auto_join=event.params.get("auto-join", False),
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to set policy: {e}")

    def _on_get_domains_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-domains action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.get_domains(
                tenant_id=event.params["tenant-id"],
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to get domains: {e}")

    def _on_set_domains_action(self, event: ops.ActionEvent) -> None:
        """Handle the set-domains action."""
        if not container_connectivity(self):
            event.fail("Workload container is not ready")
            return

        try:
            result = self._cli.set_domains(
                tenant_id=event.params["tenant-id"],
                domains=event.params.get("domains"),
                token=self._get_management_token(),
            )
            event.set_results({"output": result})
        except Exception as e:
            event.fail(f"Failed to set domains: {e}")

    def _resource_reqs_from_config(self) -> ResourceRequirements:
        """Build resource requirements from charm config."""
        limits = {"cpu": self.model.config.get("cpu"), "memory": self.model.config.get("memory")}
        requests = {"cpu": "100m", "memory": "200Mi"}
        return adjust_resource_requirements(limits, requests, adhere_to_requests=True)


if __name__ == "__main__":
    ops.main(SSOServiceOperatorCharm)
