/**
 * # Terraform Module for SSO Service K8s Operator
 *
 * This is a Terraform module facilitating the deployment of the
 * sso-service charm using the Juju Terraform provider.
 */

resource "juju_application" "application" {
  name       = var.app_name
  model_uuid = var.model
  trust      = true
  config = merge(
    var.config,
  )
  constraints = var.constraints
  resources   = var.resources
  units       = var.units

  charm {
    name     = "sso-service"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }
}
