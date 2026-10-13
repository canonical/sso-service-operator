## ADDED Requirements

### Requirement: The public routes
The leader SHALL submit these 4 HTTP routes over the `public-route` relation (interface `istio_ingress_route`). Each route has one path match and one rewrite of the path. Each route sends the request to port `8080` of the Kubernetes service of the application.

| name of the route | path match | the service receives |
|---|---|---|
| `<application>-login` | exactly `/sso/login` | `/login` |
| `<application>-consent` | exactly `/sso/consent` | `/consent` |
| `<application>-error` | exactly `/sso/error` | `/error` |
| `<application>-callback` | the prefix `/sso/callback/` | the path with the prefix `/callback/` in place of `/sso/callback/` |

The routes attach to one HTTP listener of the gateway. The port of the listener is `443` when the gateway says that TLS is enabled, and `80` in all other cases. The charm SHALL NOT ask the public gateway for a route to any other path of the service.

#### Scenario: The callback of an SSO connection
- **WHEN** a browser requests `/sso/callback/<connection id>` on the public gateway
- **THEN** the service receives the request at `/callback/<connection id>`

#### Scenario: A path that is not public
- **WHEN** a browser requests `/sso/api/v0/status` or `/api/v0/sso/connections` on the public gateway
- **THEN** no route of the charm matches the request

### Requirement: When the leader submits the public routes
The leader SHALL submit the public routes in every reconciliation in which the `public-route` relation exists. The leader does this before it checks the conditions of the service, and it does not wait for the gateway to publish its host. The leader SHALL NOT submit the routes while the public route is on plain HTTP with the `dev` option off. A unit that is not the leader SHALL NOT submit a route.

#### Scenario: The gateway did not answer yet
- **WHEN** the `public-route` relation exists and the gateway published nothing
- **THEN** the leader submits the 4 routes with a listener at port `80`
- **AND** the status `Waiting for the public route` applies

#### Scenario: The gateway publishes its host with TLS
- **WHEN** the gateway publishes the host `login.example.com` and says that TLS is enabled
- **THEN** the leader submits the 4 routes with a listener at port `443`

### Requirement: The public URL of the service
The charm SHALL build the public URL as `<scheme>://<host>/sso` and give it to the service in `PUBLIC_URL`. The host is the `external_host` that the public gateway publishes. The scheme is `https` when the gateway says that TLS is enabled, and `http` in all other cases. Every unit SHALL reconcile when the data of the `public-route` relation changes and when the relation is removed.

#### Scenario: A unit that is not the leader learns the host
- **WHEN** the gateway publishes the host `login.example.com` with TLS enabled
- **THEN** each unit plans the service with `PUBLIC_URL` set to `https://login.example.com/sso`

### Requirement: A public route on plain HTTP
The public route is on plain HTTP when the public gateway published its host and does not say that TLS is enabled. While the public route is on plain HTTP and the `dev` option is off, the unit SHALL be Blocked with `Requires a secure (HTTPS) public ingress: enable HTTPS on it, or set 'dev' for development`. In that state the charm SHALL leave these things as they are:

- the public routes that the leader submitted before
- the URLs that the leader gave to hydra-sso (see `platform-integration`)
- the layer of the service, and the service if it runs

When the `dev` option is on, the charm SHALL accept a public route on plain HTTP. The charm then gives the service a `PUBLIC_URL` that starts with `http://`, and `DEV` set to `true`.

#### Scenario: The gateway turns TLS off while the service runs
- **WHEN** the gateway publishes that TLS is not enabled while the service runs with the `dev` option off
- **THEN** the unit is Blocked with the status of this requirement
- **AND** the service continues to run with `PUBLIC_URL` set to the `https` URL
- **AND** the relation data of `public-route` and of `ui-endpoint-info` do not change

#### Scenario: A development deployment on plain HTTP
- **WHEN** the gateway publishes the host `login.example.com` without TLS and the `dev` option is on
- **THEN** the charm plans the service with `PUBLIC_URL` set to `http://login.example.com/sso`
- **AND** the unit is not Blocked because of the public route

### Requirement: The internal route
The `internal-route` relation (interface `istio_ingress_route`) is optional. When the relation exists, the leader SHALL submit one HTTP route with the name `<application>-management` in every reconciliation. The route matches the path prefixes `/api/v0/sso/tenants` and `/api/v0/sso/connections`. The route does not rewrite the path, and it sends the request to port `8080` of the Kubernetes service of the application. The listener follows the same rule as the listener of the public routes.

The charm SHALL NOT check that the internal gateway authorizes the requests. Without the relation, the charm asks for no route to the management API.

#### Scenario: A management request through the internal gateway
- **WHEN** a client requests `/api/v0/sso/tenants/<tenant id>/connections` on the internal gateway
- **THEN** the service receives the request at the same path

#### Scenario: No internal route
- **WHEN** the operator does not add the `internal-route` relation
- **THEN** the charm submits no route for the management API
- **AND** no status of the charm names the relation
