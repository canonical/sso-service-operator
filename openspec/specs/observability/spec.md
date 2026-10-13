# observability Specification

## Purpose

Operators need to see if SSO sign-ins work and if the service answers. This capability says what the charm gives to the observability stack:

- the logs of the workload, with one log alert
- a scrape job, with alert rules
- a dashboard
- the settings for traces

Key decisions:

- **The log alert selects on a label that the streams have**. The streams that Pebble forwards have the label `charm` and no label `juju_charm`. A rule with the topology labels of the library can select on `juju_charm`, and it then matches no stream. Thus the rule has its own selector, and the charm turns the topology labels off.
- **The log alert also groups by the UUID of the model**, because 2 models can have one name.
- **2 alert rules use the metrics of the service**. One rule is for sign-ins that end as unavailable. The other rule is for writes to the Tenant Service that fail.
- **The leader accepts a tracing provider that sent only one endpoint**. A unit that is not the leader does not (see the requirement "Tracing").

Non-goals:

- The content of the logs and the list of the metrics. They belong to the service.
- Alert rules for one tenant or for one SSO connection.

## Requirements
### Requirement: Logs and the log alert
The charm SHALL send the logs of the workload to each provider of the `logging` relation (interface `loki_push_api`), through the log forwarding of Pebble. The relation is optional. The charm SHALL give the provider one alert rule, `HighFrequencyHighSeverityLog`, with the label `severity: error`. The rule counts log lines in this way:

- The rule selects the streams with the label `charm="sso-service"`.
- The rule reads each line as JSON and ignores a line that is not JSON.
- The rule counts a line whose `level` is `error`, `dpanic`, `panic` or `fatal`, in any letter case.
- The rule groups the count by `juju_model`, `juju_model_uuid`, `juju_application` and `level`.

The rule fires when a group has more than 100 such lines in 5 minutes. The charm SHALL NOT let the library add topology labels to the rule.

#### Scenario: Many error lines
- **WHEN** one application writes 150 log lines with the level `error` in 5 minutes
- **THEN** the alert `HighFrequencyHighSeverityLog` fires for that application

#### Scenario: The rule in the relation data
- **WHEN** the `logging` relation exists
- **THEN** the expression of the rule in the relation data has the selector `{charm="sso-service"}`
- **AND** the only label of the rule is `severity`

### Requirement: Metrics and alert rules
The charm SHALL offer one scrape job over the `metrics-endpoint` relation (interface `prometheus_scrape`). The relation is optional. The name of the job is `sso_service_metrics`. The job reads the path `/api/v0/metrics` on port `8080` of every unit. The charm SHALL give the provider these alert rules:

| alert | fires when | severity |
|---|---|---|
| `SSOServiceUnavailable-multiple` | less than 70% of the units of the application are up, for 1 minute | `error` |
| `SSOServiceUnavailable-all` | no unit of the application is up, for 1 minute | `fatal` |
| `SSOSignInsUnavailable` | the rate of `sso_callback_outcomes_total` with the reason `unavailable` over 10 minutes is above 0.1 a second, for 10 minutes | `warning` |
| `SSOTenantServiceWritesFailing` | `sso_tenant_service_write_failures_total` goes up by more than 5 in 15 minutes | `warning` |

Each rule groups its result by `juju_model` and `juju_application`.

#### Scenario: All units are down
- **WHEN** Prometheus can scrape no unit of the application for 1 minute
- **THEN** the alert `SSOServiceUnavailable-all` fires with the severity `fatal`

#### Scenario: Sign-ins end as unavailable
- **WHEN** SSO sign-ins end as `unavailable` at more than 0.1 a second for 10 minutes
- **THEN** the alert `SSOSignInsUnavailable` fires with the severity `warning`

### Requirement: The dashboard
The charm SHALL give one dashboard over the `grafana-dashboard` relation (interface `grafana_dashboard`). The relation is optional. The title of the dashboard is `SSO Service` and its uid is `sso-service`. The dashboard has these 6 panels, each for the selected model and application:

| panel | shows |
|---|---|
| `SSO sign-in callbacks by outcome` | the rate of `sso_callback_outcomes_total` for each `reason` |
| `First sign-ins let through to Kratos` | the rate of `sso_first_sign_ins_total` for each `outcome` |
| `Attempts completed and refused at login-ui` | the rates of `sso_attempts_completed_total` and `sso_complete_attempt_refused_total` |
| `Database query time (p95)` | the 95th percentile of `storage_query_duration_seconds` for each `operation` |
| `HTTP response time (p95)` | the 95th percentile of `http_response_time_seconds` for each `route` |
| `tenant-service write failures` | the increase of `sso_tenant_service_write_failures_total` in 15 minutes for each `rpc` |

#### Scenario: Grafana is related
- **WHEN** the operator adds the `grafana-dashboard` relation
- **THEN** Grafana gets the dashboard `SSO Service` with the 6 panels

### Requirement: Tracing
The charm SHALL ask the provider of the `tracing` relation (interface `tracing`) for the protocols `otlp_http` and `otlp_grpc`. The relation is optional and takes one provider. The charm sets these variables of the service:

| variable | with a provider that is ready | without one |
|---|---|---|
| `TRACING_ENABLED` | true | false |
| `OTEL_HTTP_ENDPOINT` | the `otlp_http` endpoint without its scheme | empty |
| `OTEL_GRPC_ENDPOINT` | the `otlp_grpc` endpoint without its scheme | empty |

When the provider did not send one of the 2 endpoints, the leader SHALL leave the variable of that endpoint empty. The leader still sets the other variable. This rule does not hold on a unit that is not the leader. There, the tracing library reads application data that only the leader can read. The charm does not handle that error, and the hook fails when the unit plans the service. The charm reconciles when an endpoint changes and when the provider removes it.

#### Scenario: The provider sends only the HTTP endpoint
- **WHEN** the provider is ready and sends `http://tempo:4318` for `otlp_http` and nothing for `otlp_grpc`
- **THEN** the leader plans the service with `TRACING_ENABLED` true and `OTEL_HTTP_ENDPOINT` set to `tempo:4318`
- **AND** `OTEL_GRPC_ENDPOINT` is empty

#### Scenario: No tracing relation
- **WHEN** the operator does not add the `tracing` relation
- **THEN** the charm plans the service with `TRACING_ENABLED` false and both endpoints empty

