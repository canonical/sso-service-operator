# platform-integration Specification

## Purpose

An SSO sign-in passes through Kratos, hydra-sso, the SSO Service and the login UI, and the service calls the Tenant Service. Each of these applications needs data from the others. This capability says what the charm writes to each relation, what it reads, and when.

Key decisions:

- **The leader publishes before the workload and the database are ready**. The related applications wait for these data, and the data need neither the workload nor the database. No step stops another step.
- **This charm asks hydra-sso for the client of Kratos**. hydra-sso must know the client, and Kratos must get its credentials. This charm has a relation with both.
- **The issuer of hydra-sso comes from `byo-sso-client`**. `hydra-endpoint-info` publishes the address inside the cluster, which is not the address that browsers reach.
- **The charm derives the callback of Kratos until Kratos reports it**. Kratos reports its callback only after it registered the provider. The report of Kratos wins when it comes.
- **The client and the provider of Kratos never stop the plan of the service**. The service does not need them to start.
- **The client secret of Kratos is in the relation data**. The `external_provider` interface has it there for every provider.
- **The scope of the service token comes from the Tenant Service**. The client must hold the scope by which the Tenant Service admits its callers. While the data of the Tenant Service is missing, the charm leaves the client as it is. A service that runs still asks for that scope.
- **The library of `sso_service_info` is a package of this repository**, because Charmhub does not take new libraries.

Non-goals:

- A Juju secret for the client secret of Kratos.
- A check that the login UI has the feature on. The leader gives Kratos the provider when hydra-sso created the client.
- URLs for the device flow of hydra-sso.
- A check that the Tenant Service accepts the token of the service.
- A way to take the provider away from Kratos while the relations exist.

## Requirements
### Requirement: The leader publishes before the service can start
In every reconciliation, the leader SHALL do these steps before it checks the conditions of the service (see `workload-service`):

1. Create the envelope key, when the application has none (see `envelope-key`).
2. Submit the public routes and the internal route (see `ingress-routes`).
3. Give hydra-sso the URLs of the login, consent and error pages.
4. Give the login UI the gRPC address of the service.
5. Ask hydra-sso for the client of Kratos, and give Kratos the `byo-sso` provider.

The steps need neither the workload nor the database. A step that the leader cannot do yet SHALL NOT stop the steps after it. A unit that is not the leader does none of the steps.

#### Scenario: The database is not ready
- **WHEN** every other relation has its data and PostgreSQL did not create the database
- **THEN** the leader writes its data to `ui-endpoint-info`, `sso-service-info` and `kratos-external-idp`
- **AND** the charm does not plan the service

#### Scenario: A unit that is not the leader
- **WHEN** a unit that is not the leader reconciles
- **THEN** the unit writes nothing to `ui-endpoint-info`, `sso-service-info`, `byo-sso-client` or `kratos-external-idp`

### Requirement: The login and consent URLs for hydra-sso
The leader SHALL write these fields to the `ui-endpoint-info` relation (interface `login_ui_endpoints`), and no other field:

| field | value |
|---|---|
| `login_url` | `<PUBLIC_URL>/login` |
| `consent_url` | `<PUBLIC_URL>/consent` |
| `error_url` | `<PUBLIC_URL>/error` |
| `oidc_error_url` | `<PUBLIC_URL>/error` |

The leader writes the fields after the public gateway published its host. The leader does not write them while the public route is on plain HTTP with the `dev` option off. The charm publishes no URL for the device flow. The charm relies on the charm of hydra-sso to accept a login provider that publishes no such URL.

#### Scenario: The public URL is known
- **WHEN** the public URL of the service is `https://login.example.com/sso`
- **THEN** the leader writes `https://login.example.com/sso/login` as `login_url`
- **AND** the relation data has no `device_verification_url`

#### Scenario: The gateway did not publish its host
- **WHEN** the leader reconciles before the public gateway published its host
- **THEN** the leader writes nothing to `ui-endpoint-info`

### Requirement: The client of Kratos at hydra-sso
The leader SHALL ask hydra-sso for an OAuth client over the `byo-sso-client` relation (interface `oauth`). Kratos uses this client when it sends a user to hydra-sso. The leader asks for the client with these values:

| field | value |
|---|---|
| `redirect_uri` | the callback of Kratos for the `byo-sso` provider |
| `scope` | `openid email` |
| `grant_types` | `authorization_code` |

The callback is the redirect URI that Kratos reports over `kratos-external-idp`. Before Kratos reports one, the leader derives the callback from the `login_browser_endpoint` that Kratos publishes over `kratos-info`. The leader replaces `self-service/login/browser` at the end of that endpoint with `self-service/methods/oidc/callback/byo-sso`. When the endpoint does not end with that path, the leader has no callback. The leader then asks for no client until Kratos reports a redirect URI.

When the OAuth library refuses the values of the client, the leader SHALL write the error to its log. The leader SHALL NOT write the provider for Kratos in that hook.

#### Scenario: Kratos did not report its callback yet
- **WHEN** Kratos publishes the `login_browser_endpoint` `https://id.example.com/kratos/self-service/login/browser` and reports no redirect URI
- **THEN** the leader asks for the client with the `redirect_uri` `https://id.example.com/kratos/self-service/methods/oidc/callback/byo-sso`

#### Scenario: Kratos reports its callback
- **WHEN** Kratos reports the redirect URI `https://id.example.com/cb` over `kratos-external-idp`
- **THEN** the leader writes `https://id.example.com/cb` as the `redirect_uri` of the client

### Requirement: The byo-sso provider for Kratos
The leader SHALL give Kratos one OIDC provider in the field `providers` of the `kratos-external-idp` relation (interface `external_provider`). The leader writes the provider when both of these conditions are true:

- hydra-sso created the client of Kratos, and published the client id, the client secret and its issuer.
- The `kratos-external-idp` relation exists.

The provider has these values:

| field | value |
|---|---|
| `provider` | `generic` |
| `id` | `byo-sso` |
| `label` | `SSO` |
| `client_id`, `client_secret` | the client that hydra-sso created |
| `issuer_url` | the issuer that hydra-sso publishes over `byo-sso-client` |
| `scope` | `openid email` |
| `jsonnet_mapper` | the mapper of the charm, from `templates/byo-sso.jsonnet` |

The mapper sets the `email` trait of the account from the `email` claim. The mapper marks the address as verified only when the `email_verified` claim is `true`. The client secret is a plain value in the relation data. The plan of the service SHALL NOT wait for the client or for the provider.

#### Scenario: hydra-sso created the client
- **WHEN** hydra-sso publishes the client id, the client secret and the issuer `https://sso.example.com`
- **THEN** the leader writes one provider with the id `byo-sso` and the `issuer_url` `https://sso.example.com`

#### Scenario: hydra-sso did not create the client yet
- **WHEN** the `byo-sso-client` relation has no client id
- **THEN** the leader writes no provider to `kratos-external-idp`
- **AND** the status `Waiting for hydra-sso to register the byo-sso client` applies

### Requirement: The gRPC address for the login UI
The leader SHALL write the field `grpc_url` to every `sso-service-info` relation (interface `sso_service_info`) in every reconciliation. The value is `<application>.<model>.svc.cluster.local:50051`. The relation is optional.

#### Scenario: The login UI is related
- **WHEN** the application `sso-service` in the model `iam` has an `sso-service-info` relation
- **THEN** the leader writes `sso-service.iam.svc.cluster.local:50051` as `grpc_url`

### Requirement: The interface package sso-service-info
The repository SHALL hold the library of the `sso_service_info` interface as the Python package `sso-service-info`, in the directory `interfaces/sso_service_info`. The charm SHALL install the package from its own source tree. The package is not on Charmhub and not on PyPI. A charm on the other side of the relation installs the package from this repository at a commit.

The package has a provider and a requirer:

- The provider writes `grpc_url` to the application data of every relation, on the leader only.
- The provider emits `ready` when a relation is created.
- The requirer gives the `grpc_url`, or nothing when there is no relation or no `grpc_url`. Its `is_ready` is true when it has a `grpc_url`.
- The requirer emits `sso_service_info_changed` when the relation data of the provider changes and is not empty.
- The requirer emits `sso_service_info_removed` when the relation is removed.

#### Scenario: A requirer reads the address
- **WHEN** the provider wrote `grpc_url` and the relation data changes on the side of the requirer
- **THEN** the requirer emits `sso_service_info_changed`
- **AND** the requirer gives the value of `grpc_url`

### Requirement: The OAuth client of the service at the main Hydra
The leader SHALL ask the main Hydra for an OAuth client over the `oauth` relation (interface `oauth`). The service uses the client to get its own access token for its calls to the Tenant Service. The leader asks for the client with these values:

| field | value |
|---|---|
| `grant_types` | `client_credentials` |
| `scope` | `openid`, then the scope that the Tenant Service publishes |
| `redirect_uri` | the fixed value `https://example.com` |

The scope that the Tenant Service publishes is the field `allowed_scope` of the `tenant-service-info` relation. The Tenant Service admits its callers by that scope. The client must hold the scope before the service can ask for it.

The leader SHALL write the values of the client in every hook in which the Tenant Service published its gRPC address. In a hook without that address, the leader SHALL leave the client as it is. A service that runs still asks for the scope that it started with.

The charm SHALL give the service these variables:

| variable | value |
|---|---|
| `SERVICE_TOKEN_URL` | the token endpoint that the main Hydra publishes over `oauth` |
| `SERVICE_CLIENT_ID`, `SERVICE_CLIENT_SECRET` | the client that the main Hydra created |
| `SERVICE_TOKEN_SCOPES` | the scope that the Tenant Service publishes. The value is empty when the Tenant Service publishes none |

The main Hydra gives the client secret in a Juju secret. The charm reads the latest revision of that secret, and reconciles when a secret changes.

#### Scenario: The Tenant Service publishes a scope
- **WHEN** the Tenant Service publishes its gRPC address and the `allowed_scope` `tenant-service`
- **THEN** the leader asks for the client with the `scope` `openid tenant-service`
- **AND** the charm plans the service with `SERVICE_TOKEN_SCOPES` set to `tenant-service`

#### Scenario: The Tenant Service publishes no scope
- **WHEN** the Tenant Service publishes its gRPC address and no `allowed_scope`
- **THEN** the leader asks for the client with the `scope` `openid`
- **AND** the charm plans the service with an empty `SERVICE_TOKEN_SCOPES`

#### Scenario: The Tenant Service relation is removed while the service runs
- **WHEN** the operator removes the `tenant-service-info` relation while the service runs
- **THEN** the leader does not change the `scope` of the client
- **AND** the service continues to run with the settings that it started with

