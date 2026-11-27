# caller-authentication Specification

## Purpose

The SSO Service verifies the token of every call to its management API. This capability says these things:

- which issuer the charm tells the service to trust
- where the service finds the keys of that issuer
- how an operator restricts the callers

Key decisions:

- **The main Hydra is the default issuer**. The `oauth` relation gives the issuer and its keys, and the operator sets no option.
- **The operator can name another issuer**, for a deployment in which the callers present tokens of another issuer.
- **The service never checks another issuer with the keys of the main Hydra**. With `authn_issuer` set, the keys come from `authn_jwks_url`, or the service discovers them from the issuer.
- **`authn_jwks_url` without `authn_issuer` is not valid**. The charm blocks and leaves the service as it is.
- **The token of the service itself always comes from the main Hydra**. The options change only which tokens the service accepts.
- **A restriction of callers still admits the OAuth client of the service**. The management actions call the API with a token of that client (see `management-actions`).

Non-goals:

- Authorization. The internal gateway must authorize each request.
- An option that turns authentication off. The charm does not set `AUTHENTICATION_ENABLED`.
- A check that `authn_issuer` or `authn_jwks_url` is a URL that answers.
- The sign-in API on the gRPC port. That API takes no token, and these options do not apply to it.

## Requirements
### Requirement: The issuer of the tokens of callers
The charm SHALL tell the service which issuer signs the tokens of the callers of the management API. The charm takes the issuer and the location of its keys from the options `authn_issuer` and `authn_jwks_url`, or from the `oauth` relation:

| `authn_issuer` | `authn_jwks_url` | `AUTHENTICATION_ISSUER` | `AUTHENTICATION_JWKS_URL` |
|---|---|---|---|
| not set | not set | the issuer that the main Hydra publishes over `oauth` | the JWKS endpoint that the main Hydra publishes over `oauth` |
| set | set | the value of `authn_issuer` | the value of `authn_jwks_url` |
| set | not set | the value of `authn_issuer` | empty. The service then discovers the keys from the issuer |
| not set | set | not valid (see the next requirement) | not valid |

When `authn_issuer` is set, the charm SHALL NOT give the service the JWKS endpoint of the main Hydra. The options do not change the variables `SERVICE_TOKEN_URL`, `SERVICE_CLIENT_ID` and `SERVICE_CLIENT_SECRET`. Those variables come from the `oauth` relation in every case.

#### Scenario: The default issuer
- **WHEN** the operator sets no `authn_` option
- **THEN** the charm plans the service with the issuer and the JWKS endpoint of the main Hydra

#### Scenario: Another issuer with keys that the service discovers
- **WHEN** the operator sets `authn_issuer` to `https://sts.example.com` and does not set `authn_jwks_url`
- **THEN** the charm plans the service with `AUTHENTICATION_ISSUER` set to `https://sts.example.com`
- **AND** `AUTHENTICATION_JWKS_URL` is empty
- **AND** `SERVICE_TOKEN_URL` is still the token endpoint of the main Hydra

### Requirement: An invalid combination of the options
When `authn_jwks_url` is set and `authn_issuer` is not set, the unit SHALL be Blocked with `Invalid configuration: authn_jwks_url is set without authn_issuer`. In that state the charm SHALL NOT plan the service, and SHALL NOT migrate the database in a reconciliation. The charm leaves the layer of the service as it is, and a service that runs continues to run. The leader still publishes its relation data and its routes.

#### Scenario: The operator sets only the JWKS URL
- **WHEN** the operator sets `authn_jwks_url` and not `authn_issuer` while the service runs
- **THEN** the unit is Blocked with `Invalid configuration: authn_jwks_url is set without authn_issuer`
- **AND** the service continues to run with the issuer that it started with

### Requirement: Restriction of callers by subject or scope
The charm SHALL give the service the callers that the operator admits, from the options `authn_allowed_subjects` and `authn_allowed_scope`:

| variable | value |
|---|---|
| `AUTHENTICATION_ALLOWED_SUBJECTS` | the items of `authn_allowed_subjects`, which is a list with commas. The charm removes the spaces around each item and removes empty items. When the operator restricts the callers, the charm adds the client id of the OAuth client of the service at the end |
| `AUTHENTICATION_REQUIRED_SCOPE` | the value of `authn_allowed_scope` |

The operator restricts the callers when `authn_allowed_subjects` has an item or `authn_allowed_scope` is set. In that state the charm SHALL add the client id of the OAuth client of the service to the list. The charm adds it only when the main Hydra created that client. The management actions call the API with a token of that client, and the service must admit it. When the operator does not restrict the callers, the charm SHALL NOT add the client id. A list that holds only that client admits no other caller.

Both options are empty by default. The charm relies on the service for the rule of admission. The service admits a valid token whose subject is in the list, or whose scope contains the required scope. When both variables are empty, the service admits every valid token of the issuer.

#### Scenario: A list with spaces and an empty item
- **WHEN** the operator sets `authn_allowed_subjects` to `a , b,,c` and the client id of the service is `sso-service-client`
- **THEN** the charm plans the service with `AUTHENTICATION_ALLOWED_SUBJECTS` set to `a,b,c,sso-service-client`

#### Scenario: A restriction by scope only
- **WHEN** the operator sets only `authn_allowed_scope`, to `sso`, and the client id of the service is `sso-service-client`
- **THEN** the charm plans the service with `AUTHENTICATION_ALLOWED_SUBJECTS` set to `sso-service-client`
- **AND** `AUTHENTICATION_REQUIRED_SCOPE` is `sso`

#### Scenario: No restriction
- **WHEN** the operator sets neither `authn_allowed_subjects` nor `authn_allowed_scope`
- **THEN** both variables are empty
- **AND** the service admits every valid token of the issuer

