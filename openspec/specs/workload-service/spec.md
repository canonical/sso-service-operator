# workload-service Specification

## Purpose

The charm runs the SSO Service as one Pebble service in the workload container. This capability says these things:

- when the charm plans the service
- which settings the service gets
- when the service restarts
- what the status of a unit means

Key decisions:

- **The charm checks every input before it plans the service**. The service refuses to start when a required setting is missing or a migration is pending. Thus each input is a condition with a status of its own, and the status names what the unit waits for.
- **A condition that is false changes nothing**. The charm does not change the layer and does not stop the service. A service that runs continues with the settings that it started with. The one exception is the removal of the database relation, which stops the service.
- **The status comes from the state, in every hook**. The charm computes the status again at the end of each hook, also in a hook that does not reconcile.
- **The check of the service decides if a start failed**. A start counts as failed only when Pebble reports the service as active and the check `ready` is down. In the other cases in which the service is not up, the unit waits.
- **The client and the provider of Kratos do not stop the plan**. The service does not need them to start.

Non-goals:

- A restriction of the ports `8080` and `50051`. The charm opens both ports and restricts neither. The deployment must restrict port `50051` to the login UI, because the sign-in API on that port takes no token.
- A level for the check `ready`.
- A check of the value of `log_level`.
- Options for the settings of the service that the environment table does not name.

## Requirements
### Requirement: Conditions before the charm plans the service
The charm SHALL plan the service only in a reconciliation in which all the conditions of this table are true. The charm checks the conditions in the order of the table and stops at the first condition that is false.

| # | condition | status of the condition |
|---|---|---|
| 1 | The charm can connect to the workload container | Waiting, `Container is not connected yet` |
| 2 | The `pg-database` relation exists | Blocked, `Missing integration pg-database` |
| 3 | PostgreSQL created the database of the charm | Waiting, `Waiting for database creation` |
| 4 | The public route is not on plain HTTP, or the `dev` option is on (see `ingress-routes`) | Blocked, `Requires a secure (HTTPS) public ingress: enable HTTPS on it, or set 'dev' for development` |
| 5 | The authentication options are valid (see `caller-authentication`) | Blocked, `Invalid configuration: authn_jwks_url is set without authn_issuer` |
| 6 | No migration of the database is pending (see `database-migration`) | see `database-migration` |
| 7 | The envelope key exists (see `envelope-key`) | Waiting, `Waiting for secrets creation` |
| 8 | The public gateway published its host | Waiting, `Waiting for the public route` |
| 9 | The Tenant Service published its `service_url` and its `grpc_url` | Waiting, `Waiting for tenant-service's address` |
| 10 | The main Hydra created the OAuth client of the service | Waiting, `Waiting for the oauth client` |
| 11 | hydra-sso published its `admin_endpoint` and its `public_endpoint` | Waiting, `Waiting for hydra-sso's endpoints` |
| 12 | Kratos published its admin endpoint | Waiting, `Waiting for Kratos's info` |
| 13 | The charm applied the CA bundle (see `ca-bundle`) | none |

Because of the order, the leader migrates the database when conditions 1 to 5 are true. The charm applies the CA bundle only when conditions 1 to 12 are true.

When a condition is false, the charm SHALL NOT change the layer of the service, and SHALL NOT stop or restart the service. A service that runs keeps the settings that it started with. The one exception is the removal of the `pg-database` relation, which stops the service (see `database-migration`). The requirement "Unit status" says which status the unit shows when more than one status applies.

#### Scenario: An option becomes invalid while the service runs
- **WHEN** the operator sets `authn_jwks_url` and leaves `authn_issuer` empty while the service runs
- **THEN** the unit is Blocked with `Invalid configuration: authn_jwks_url is set without authn_issuer`
- **AND** the service continues to run with the layer that it had

#### Scenario: An input of the service is not there yet
- **WHEN** all the other conditions are true and hydra-sso did not publish its admin endpoint
- **THEN** the charm does not plan the service
- **AND** the unit is Waiting with `Waiting for hydra-sso's endpoints`

### Requirement: The Pebble layer
The charm SHALL give Pebble the layer of the service, with the name `sso-service`. The layer has one service and one check:

- The service `sso-service` runs the command `sso-service serve`. Its startup is `disabled`.
- The check `ready` is an HTTP request to `http://localhost:8080/api/v0/status`. The charm gives the check no level.

#### Scenario: The service answers on its status route
- **WHEN** the service runs and answers `GET /api/v0/status` on port `8080`
- **THEN** the check `ready` is up

### Requirement: The environment of the service
The charm SHALL set these environment variables of the service, and no other variable:

| variable | value |
|---|---|
| `PORT` | `8080` |
| `GRPC_PORT` | `50051` |
| `LOG_LEVEL` | the value of the `log_level` option, in capital letters. The default of the option is `info` |
| `DEV` | `true` when the `dev` option is on. When the option is off, the charm does not set the variable |
| `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` | the values of the `http_proxy`, `https_proxy` and `no_proxy` options. The defaults of the options are empty |
| `DSN` | see `database-migration` |
| `ENVELOPE_KEY` | see `envelope-key` |
| `PUBLIC_URL` | see `ingress-routes` |
| `HYDRA_SSO_ADMIN_URL` | the `admin_endpoint` that hydra-sso publishes over `hydra-endpoint-info` |
| `KRATOS_ADMIN_URL` | the `admin_endpoint` that Kratos publishes over `kratos-info` |
| `TENANT_SERVICE_GRPC_ADDRESS` | the `grpc_url` that the Tenant Service publishes over `tenant-service-info` |
| `SERVICE_TOKEN_URL`, `SERVICE_CLIENT_ID`, `SERVICE_CLIENT_SECRET`, `SERVICE_TOKEN_SCOPES` | see `platform-integration` |
| `AUTHENTICATION_ISSUER`, `AUTHENTICATION_JWKS_URL`, `AUTHENTICATION_ALLOWED_SUBJECTS`, `AUTHENTICATION_REQUIRED_SCOPE` | see `caller-authentication` |
| `TRACING_ENABLED`, `OTEL_HTTP_ENDPOINT`, `OTEL_GRPC_ENDPOINT` | see `observability` |

The defaults of the service apply to every setting that this table does not name. The charm does not check the value of `log_level`.

#### Scenario: The dev option is off
- **WHEN** the charm plans the service with the `dev` option off
- **THEN** the environment of the service has no `DEV` variable

#### Scenario: A log level in small letters
- **WHEN** the operator sets `log_level` to `debug`
- **THEN** the charm plans the service with `LOG_LEVEL` set to `DEBUG`

### Requirement: Start and restart of the service
When the charm plans the service, the charm SHALL add the layer to Pebble. Then the charm SHALL do the first of these steps that applies:

1. When the CA bundle of the workload changed in this hook, the charm restarts the service.
2. When the service does not run, the charm starts the service.
3. In all other cases, the charm asks Pebble to replan.

The charm relies on Pebble to restart the service on a replan only when the layer of the service changed. When Pebble cannot start or restart the service, the charm SHALL write `Failed to plan pebble layer, please check the sso-service container logs` to its log. The charm sets no status for that error.

#### Scenario: A setting changes while the service runs
- **WHEN** Kratos publishes another admin endpoint while the service runs
- **THEN** the charm plans the service with the new `KRATOS_ADMIN_URL`
- **AND** Pebble restarts the service

#### Scenario: Nothing changed
- **WHEN** the service runs and a reconciliation finds the same layer and the same CA bundle as before
- **THEN** the service does not restart

### Requirement: Ports, version and resource limits
When the workload container becomes ready, the charm SHALL open the TCP ports `8080` and `50051` of the unit. Port `8080` is the HTTP listener of the service and port `50051` is its gRPC listener. The charm SHALL then set the workload version of the unit to the version that `sso-service version` prints.

The charm SHALL use the `cpu` and `memory` options as the resource limits of the workload container. The charm asks for `100m` of CPU and `200Mi` of memory as the resource requests. When a limit is lower than its request, the charm uses the request as the limit. Both options are unset by default, which gives no limit.

#### Scenario: A memory limit
- **WHEN** the operator sets the `memory` option to `1Gi`
- **THEN** the charm asks Kubernetes for a memory limit of `1Gi` on the workload container

### Requirement: Unit status
The charm SHALL compute the status of the unit at the end of every hook, from the state at that time. The charm collects every status of the 2 lists below that applies. The unit shows the first Blocked status that applies. When no Blocked status applies, the unit shows the first Waiting status that applies. When no status of the lists applies, the unit is Active with no message.

The Blocked statuses, in order:

1. `Invalid configuration: authn_jwks_url is set without authn_issuer` (see `caller-authentication`).
2. A status about the `initial_envelope_key_secret_id` option (see `envelope-key`).
3. `Missing integration <endpoint>`, for the first of these relations that does not exist: `pg-database`, `public-route`, `oauth`, `kratos-info`, `tenant-service-info`, `hydra-endpoint-info`, `ui-endpoint-info`, `byo-sso-client`, `kratos-external-idp`.
4. `Requires a secure (HTTPS) public ingress: enable HTTPS on it, or set 'dev' for development` (see `ingress-routes`).
5. `Database migration failed: <reason>` or `Migration check failed: <reason>` (see `database-migration`).
6. `Failed to start the service, please check the sso-service container logs`. This status applies when Pebble reports the service as active and the check `ready` is down.
7. The status of the resource limits, when the charm cannot apply them.

The Waiting statuses, in order:

1. `Container is not connected yet`.
2. `Waiting for secrets creation`.
3. `Missing integration sso-service`, when the peer relation `sso-service` does not exist.
4. `Waiting for database creation`.
5. `Waiting for the public route`.
6. `Waiting for tenant-service's address`.
7. `Waiting for the oauth client`.
8. `Waiting for hydra-sso's endpoints`.
9. `Waiting for Kratos's info`.
10. `Waiting for hydra-sso to register the byo-sso client`, when hydra-sso did not create the client of Kratos (see `platform-integration`).
11. `Waiting for database migration` on the leader, or `Waiting for leader unit to run the migration` on another unit.
12. `Waiting for the service to start`. This status applies when Pebble does not report the service as active, or the check `ready` is not up.
13. The status of the resource limits, while their change is in progress.

Some statuses apply only when the charm can connect to the workload container. They are statuses 5 and 6 of the first list, and statuses 11 and 12 of the second list.

Thus an Active unit means that the service runs, that the check `ready` is up, and that no status of the 2 lists applies. A unit that is not Active can still run the service. These statuses do not stop the plan of the service:

- `Missing integration ui-endpoint-info`, `Missing integration byo-sso-client` and `Missing integration kratos-external-idp`
- `Waiting for hydra-sso to register the byo-sso client`
- a status about `initial_envelope_key_secret_id` when the envelope key exists

While a reconciliation runs, the unit shows Maintenance with `Configuring resources`.

#### Scenario: A new application with no relations
- **WHEN** the operator deploys the application and adds no relation
- **THEN** the unit is Blocked with `Missing integration pg-database`

#### Scenario: The service runs before Kratos has its client
- **WHEN** conditions 1 to 13 are true and hydra-sso did not create the client of Kratos
- **THEN** the charm plans the service
- **AND** the unit is Waiting with `Waiting for hydra-sso to register the byo-sso client`

#### Scenario: The service starts and its check fails
- **WHEN** Pebble reports the service as active and the check `ready` is down
- **THEN** the unit is Blocked with `Failed to start the service, please check the sso-service container logs`

#### Scenario: The service did not start yet
- **WHEN** no other status of the 2 lists applies and Pebble does not report the service as active
- **THEN** the unit is Waiting with `Waiting for the service to start`

### Requirement: Units that are not the leader
A unit that is not the leader SHALL plan the service under the same conditions and with the same environment as the leader. The requirement "Tracing" of `observability` has the one exception. Such a unit SHALL NOT do these things:

- create the envelope key
- migrate the database in a reconciliation
- publish the relation data of `platform-integration`, or submit a route (see `ingress-routes`)

When the operator adds units, each new unit waits for the envelope key and for the migration of the leader. Then the unit plans the service.

#### Scenario: A second unit joins
- **WHEN** a second unit starts after the leader created the envelope key and migrated the database
- **THEN** the second unit plans the service with the same environment as the leader
- **AND** the second unit publishes nothing to hydra-sso, to Kratos or to the login UI, and submits no route

#### Scenario: A unit starts before the leader created the key
- **WHEN** a unit that is not the leader reconciles and the application has no envelope key
- **THEN** the unit does not plan the service
- **AND** the unit is Waiting with `Waiting for secrets creation`

