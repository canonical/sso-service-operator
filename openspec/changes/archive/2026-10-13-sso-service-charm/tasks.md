## 1. Metadata and packaging

- [x] 1.1 Declare the options, the 2 actions, the relations, the container and the image resource in `charmcraft.yaml`.
- [x] 1.2 Add the dependencies in `pyproject.toml` and `uv.lock`, and the test environments in `tox.ini`.
- [x] 1.3 Add the relation libraries of the other charms under `lib/charms`.
- [x] 1.4 Add the interface package `sso-service-info`, with its provider and its requirer, in `interfaces/sso_service_info`.
- [x] 1.5 Remove `.github/workflows/release_libs.yaml`, because the repository releases no library to Charmhub.

## 2. Workload

- [x] 2.1 Add the constants in `src/constants.py`, the default environment in `src/env_vars.py` and the errors in `src/exceptions.py`.
- [x] 2.2 Add the Pebble layer, the check `ready`, the plan and the push of the CA file in `src/services.py`.
- [x] 2.3 Add the commands `version`, `migrate check` and `migrate up`, and the one-line reason of a failure, in `src/cli.py`.
- [x] 2.4 Add the options and their environment variables in `src/configs.py`.
- [x] 2.5 Add the conditions of the service and the check of the authentication options in `src/utils.py`.

## 3. Relations

- [x] 3.1 Add the data of the database, hydra-sso, Kratos, the Tenant Service and tracing in `src/integrations.py`.
- [x] 3.2 Add the public routes and the internal route in `src/integrations.py`.
- [x] 3.3 Add the 2 OAuth clients, the `byo-sso` provider and the URLs for hydra-sso in `src/integrations.py`.
- [x] 3.4 Add the mapper of the `byo-sso` provider in `templates/byo-sso.jsonnet`.
- [x] 3.5 Add the peer data and the CA bundle in `src/integrations.py`.

## 4. Secrets

- [x] 4.1 Add the envelope key, the check of a key and the initial key in `src/secret.py`.

## 5. Charm

- [x] 5.1 Add the observers and the reconciliation with its steps in `src/charm.py`.
- [x] 5.2 Add the unit status and the failure statuses of the migration in `src/charm.py`.
- [x] 5.3 Add the update of the CA bundle, with its copy and its retry, in `src/charm.py`.
- [x] 5.4 Add the actions `run-migration` and `get-envelope-key` in `src/charm.py`.

## 6. Observability

- [x] 6.1 Add the alert rules in `src/prometheus_alert_rules/sso-service.rules` and `src/loki_alert_rules/sso_service_high_severity_log.rule`.
- [x] 6.2 Add the dashboard in `src/grafana_dashboards/sso-service.json.tmpl`.

## 7. Deployment and documentation

- [x] 7.1 Add the Terraform module in `terraform/`.
- [x] 7.2 Describe the network and the envelope key in `README.md`.

## 8. Tests

- [x] 8.1 Add the unit tests of the charm in `tests/unit/test_charm.py`, with their fixtures in `tests/unit/conftest.py`.
- [x] 8.2 Add the unit tests of the helpers in `tests/unit/test_cli.py`, `test_configs.py`, `test_integrations.py` and `test_secret.py`.
- [x] 8.3 Add the unit tests of the interface package in `tests/unit/test_libs.py`.
- [x] 8.4 Add the integration tests in `tests/integration/`. They deploy the charm with PostgreSQL only.

## 9. Verification

- [x] 9.1 Run `openspec validate sso-service-charm --strict`.
