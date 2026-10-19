## Why

The SSO Service has no charm, thus an operator cannot deploy it with Juju. A deployment also needs more than the service. The second Hydra, hydra-sso, must know the pages of the service. Kratos must get its `byo-sso` provider, and the login UI must find the service.

## What Changes

This change adds the Kubernetes charm of the SSO Service. The charm does these things:

- It runs `sso-service serve` under Pebble, with settings from options, relations and Juju secrets.
- It gets a PostgreSQL database. The leader migrates the database before the service starts.
- It asks 2 Istio gateways for routes: the pages of an SSO sign-in, and the management API.
- It connects the service to hydra-sso, Kratos, the login UI, the Tenant Service and the main Hydra.
- It keeps the envelope key in a Juju secret.
- It tells the service which issuer signs the tokens of callers.
- It gives the workload the CA certificates that it receives.
- It gives logs, metrics, alert rules, a dashboard and traces to the observability stack.

The charm has the actions `run-migration` and `get-envelope-key`. The repository also gets a Terraform module and the interface package `sso-service-info`.

## Capabilities

### New Capabilities

- `workload-service`: the conditions and the settings of the service, and the unit status.
- `database-migration`: the database and its migration.
- `ingress-routes`: the public routes and the internal route.
- `platform-integration`: the relation data for the other applications of the platform.
- `envelope-key`: the key and the initial key.
- `caller-authentication`: the issuer of the tokens of callers.
- `ca-bundle`: the CA certificates of the workload.
- `observability`: logs, metrics, alert rules, a dashboard and traces.

### Modified Capabilities

<!-- None -->

## Non-goals

- An ingress other than `istio_ingress_route`.
- Actions that manage SSO connections and policies.
- Rotation of the envelope key.
- A network policy for the gRPC port.

## Impact

- **New files**: `charmcraft.yaml`, `pyproject.toml`, `uv.lock`, `tox.ini`, `src/`, `templates/byo-sso.jsonnet`, `lib/charms`, `interfaces/sso_service_info`, `terraform/` and `tests/`.
- **Changed files**: `README.md`.
- **Removed files**: `.github/workflows/release_libs.yaml`.
- **Other charms**: The charm of hydra-sso must accept a login provider with no URL for the device flow. The charm of the Tenant Service must publish `allowed_scope` when the Tenant Service restricts its callers by scope. The charm of the login UI needs the package `sso-service-info`.
- **Image**: `ghcr.io/canonical/sso-service`.
