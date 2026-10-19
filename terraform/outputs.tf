# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "The Juju application name"
  value       = juju_application.application.name
}

output "requires" {
  description = "The Juju integrations that the charm requires"
  value = {
    pg-database         = "pg-database"
    hydra-endpoint-info = "hydra-endpoint-info"
    byo-sso-client      = "byo-sso-client"
    kratos-info         = "kratos-info"
    oauth               = "oauth"
    tenant-service-info = "tenant-service-info"
    public-route        = "public-route"
    internal-route      = "internal-route"
    logging             = "logging"
    tracing             = "tracing"
    receive-ca-cert     = "receive-ca-cert"
  }
}

output "provides" {
  description = "The Juju integrations that the charm provides"
  value = {
    ui-endpoint-info    = "ui-endpoint-info"
    kratos-external-idp = "kratos-external-idp"
    sso-service-info    = "sso-service-info"
    metrics-endpoint    = "metrics-endpoint"
    grafana-dashboard   = "grafana-dashboard"
  }
}
