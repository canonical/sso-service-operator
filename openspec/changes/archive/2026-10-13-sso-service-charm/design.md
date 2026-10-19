## Context

See `proposal.md` for the motivation. The SSO Service is one binary. `sso-service serve` runs the service, and `sso-service migrate` changes the schema of its PostgreSQL database. The service reads all its settings from environment variables and refuses to start when a required setting is missing or a migration is pending.

An SSO sign-in passes through several applications of the platform. The charm talks to each of them over a relation:

| relation | interface | other side | what passes |
|---|---|---|---|
| `pg-database` | `postgresql_client` | PostgreSQL | the database of the service |
| `public-route` | `istio_ingress_route` | the public gateway | the routes of the sign-in pages, and the host of the gateway |
| `internal-route` | `istio_ingress_route` | the internal gateway | the route of the management API |
| `hydra-endpoint-info` | `hydra_endpoints` | hydra-sso | the admin endpoint of hydra-sso |
| `ui-endpoint-info` | `login_ui_endpoints` | hydra-sso | the URLs of the login, consent and error pages |
| `byo-sso-client` | `oauth` | hydra-sso | the OAuth client of Kratos, and the issuer of hydra-sso |
| `kratos-info` | `kratos_info` | Kratos | the admin endpoint and the login endpoint of Kratos |
| `kratos-external-idp` | `external_provider` | Kratos | the `byo-sso` provider |
| `oauth` | `oauth` | the main Hydra | the OAuth client of the service, and the issuer of the tokens of callers |
| `tenant-service-info` | `tenant_service_info` | the Tenant Service | the gRPC address of the Tenant Service and its scope |
| `sso-service-info` | `sso_service_info` | the login UI | the gRPC address of the service |
| `receive-ca-cert` | `certificate_transfer` | a certificate provider | CA certificates |
| `logging`, `metrics-endpoint`, `grafana-dashboard`, `tracing` | `loki_push_api`, `prometheus_scrape`, `grafana_dashboard`, `tracing` | the observability stack | logs, metrics with alert rules, the dashboard and traces |

The charm has one handler, the reconciliation, for almost every event. The reconciliation also runs in every `update-status` hook.

## Goals / Non-Goals

**Goals:**

- The related applications get their data as early as possible.
- The unit status names what the unit waits for.
- When the operator gives the key of a restored database, the charm never starts the service with another key.
- More than one unit can run the service.

**Non-Goals:**

- An ingress other than Istio.
- Rotation of the envelope key.
- Authorization of management requests. The internal gateway does that.
- Network restrictions between the applications of the cluster.

## Decisions

### Decision 1: The leader publishes first, then the charm plans the service

- **Decision**: The reconciliation has 2 parts. In the first part the leader creates the envelope key, submits its routes and writes its relation data. In the second part the charm checks the conditions of the service, migrates the database and plans the service. A step of the first part never stops another step.
- **Rationale**: The related applications wait for these data. The data need neither the workload nor the database.
- **Alternative considered**: The alternative was to publish after the conditions of the service. We turned it down. With it, each related application waits for a database that it does not need.

### Decision 2: Conditions come before the plan, with one status each

- **Decision**: The charm checks each thing that the service refuses to start without before it plans the service. Each condition has one status. When a condition is false, the charm leaves the layer and the service as they are. The one exception is the removal of the database relation, which stops the service.
- **Rationale**: The service refuses to start without these inputs. One status for each condition names what the unit waits for.

### Decision 3: Only the pages of a sign-in are public, and only over HTTPS

- **Decision**: The public gateway gets 4 routes under `/sso`: 3 exact paths and the prefix of the callback. The gateway rewrites each path to the path of the service. The charm blocks when the public gateway publishes its host without TLS, unless the `dev` option is on.
- **Rationale**: The callback is one path for each SSO connection, thus it needs a prefix. The service sets a browser cookie with the `__Host-` prefix and the `Secure` attribute. Browsers drop such a cookie over plain HTTP, except on localhost, and then no SSO sign-in can finish. The Gateway API allows a prefix rewrite only in a rule with one match, thus each path has its own route.
- **Consequence**: Nothing else of the service is public. The management API, the status route and the metrics route have no public route.

### Decision 4: Only the leader migrates, with one check in a hook

- **Decision**: The charm asks the workload one time in a hook if a migration is pending. The leader migrates in the reconciliation. The other units do not migrate, and each of them plans the service when its own check finds no pending migration. After a migration, the leader writes the version of the workload to the peer relation. A change of that value makes the other units reconcile. A check that fails migrates nothing. A failed migration or check blocks the unit with the end of its reason.
- **Rationale**: When the check fails, the charm does not know if a migration is pending. `juju status` shows 120 characters of a message, and the cause of a failed command is at the end of its error.

### Decision 5: The envelope key is written one time

- **Decision**: The leader creates the key in a Juju secret when the application has none. The charm never replaces the content of that secret. When the `initial_envelope_key_secret_id` option names a key that the leader cannot read, the leader creates no key and the unit blocks.
- **Rationale**: The service encrypts the client secrets of the SSO connections with this key. A restore that cannot read its key must not start with a new key. With a new key, the service cannot read the client secrets in the database.
- **Alternative considered**: The alternative was to make a new key when the charm cannot read the configured key. We turned it down for the reason above.

### Decision 6: This charm asks for the client of Kratos

- **Decision**: The charm asks hydra-sso for the OAuth client that Kratos uses, and gives Kratos the provider with the credentials of that client. The issuer in the provider comes from `byo-sso-client`. Until Kratos reports its callback, the charm derives the redirect URI from the login endpoint of Kratos.
- **Rationale**: hydra-sso must know the client, and Kratos must get its credentials. This charm has a relation with both. `hydra-endpoint-info` publishes the address of hydra-sso inside the cluster, which is not the address that browsers reach. Kratos reports its callback only after it registered the provider. Before that, the charm derives the callback, so that it can ask for the client.
- **Alternative considered**: The alternative was a Juju secret for the client secret in the provider. That needs a change of the library of the `external_provider` interface, which is not part of this change. The client secret is a value in the relation data, as it is for the other providers of that interface.

### Decision 7: The scope of the service token comes from the Tenant Service

- **Decision**: The OAuth client of the service asks for `openid` and for the scope that the Tenant Service publishes. The service asks for the same scope in its token. The charm changes the client only when the Tenant Service published its address.
- **Rationale**: The Tenant Service admits its callers by that scope, and a client must hold a scope before it can ask for it. A service that runs still asks for the scope that it started with. Thus the charm does not take the scope from the client while the relation data is missing.

### Decision 8: The charm keeps a copy of the CA bundle that it applied

- **Decision**: The charm compares the CA bundle of the relation with its copy and acts only on a difference. It reads the CA bundle one time in a hook, compares byte for byte, and puts the copy back when the update fails. It applies the CA bundle only in a hook that plans the service, and restarts the service when the file of the workload changes.
- **Rationale**:
  - The library of the interface consumes a bundle that a provider sent as unit data when the charm reads it. A second read in the same hook can give another bundle.
  - A comparison as text changes CRLF line ends, and a bundle with such line ends then never equals its copy.
  - A copy that stays after a failed update says that the work is done, and the charm then never tries again.
  - The service is a Go program. It loads the system certificates one time, thus it needs a restart to use a new file.
- **Alternative considered**: The alternative was to apply the CA bundle also in a hook that does not plan the service. We turned it down, because the service never loads a file that the charm pushes without a restart.

### Decision 9: The interface library is a package of this repository

- **Decision**: The library of the `sso_service_info` interface is the Python package `sso-service-info` in `interfaces/sso_service_info`. The charm installs it from its own tree. A charm on the other side of the relation installs it from this repository at a commit.
- **Rationale**: Charmhub does not take new libraries, thus the library cannot be a file under `lib/`. Nothing of it goes to Charmhub, and the workflow that released libraries is removed.

### Decision 10: The log alert selects on a label that the streams have

- **Decision**: The log alert has the selector `{charm="sso-service"}` in its expression. The charm turns off the topology labels that the library adds to log alert rules.
- **Rationale**: The streams that Pebble forwards have the labels `charm`, `job`, `juju_application`, `juju_model`, `juju_model_uuid` and `juju_unit`. They have no `juju_charm` label. A Loki charm with an older library selects on `juju_charm` for a rule with topology labels, and such a rule matches no stream. The rule groups by `juju_model_uuid` also, because 2 models can have one name.

## Risks / Trade-offs

- **The gRPC port takes calls with no token**. The service serves its sign-in API on port `50051` without a token, because the login UI calls it before a user has one. The charm opens the port and does not restrict it. The deployment must restrict the port to the login UI.
- **The public gateway must be the gateway of the login UI**. The login UI reads a cookie that the service sets. The charm does not check that the 2 applications share a host.
- **The client secret of Kratos is in the relation data** of `kratos-external-idp`.
- **`get-envelope-key` returns the key as the result of an action**. Whoever can read the model can read the result.
- **Kratos gets the provider as soon as hydra-sso created the client**. The charm does not know if the login UI has the feature on.
- **Nothing ties the envelope key to the database**. An application that the operator removes and deploys again makes a new key, unless the option gives the old key. The service cannot read the client secrets of a database that it gets back with a new key.
- **The check `ready` has no level.**
- **The charm uses the `ca` value of a remote unit as the unit wrote it**. The charm does not decode or check that value.
- **The charm builds `PUBLIC_URL` through a URL type**. The type writes the host in small letters and drops a default port. The redirect URI of each SSO connection has that spelling.
- **A failed migration shows as Blocked only in the hook in which it failed**. After a hook that does not reconcile, the leader shows `Waiting for database migration` until the next reconciliation tries again.
- **A failed update of the CA bundle has no status**. The log of the unit has the error, and the next reconciliation tries again.
- **A Tenant Service that restricts by scope and publishes no scope**. The token of the service then asks for no scope. The charm cannot see that the Tenant Service refuses the calls.
- **A provider of CA certificates with one unit that uses the older form of the interface**. In a `relation-changed` hook of `receive-ca-cert`, the library reads before the charm and consumes the unit. The charm then reads no certificate of that provider in that hook. When the charm applied that certificate before, it removes the certificate and restarts the service. The next reconciliation applies the certificate again and restarts the service again.
- **A plan that fails after a new CA file**. When the push of the file succeeds and Pebble then cannot restart the service, the copy of the charm already equals the CA bundle. No later reconciliation restarts the service for that file.
- **A tracing provider that sent only one endpoint, on a unit that is not the leader**. The tracing library then reads application data that only the leader can read, and the hook of that unit fails.
- **A second migration with the same workload version**. The value in the peer relation does not change. The other units then reconcile only at their next hook.
