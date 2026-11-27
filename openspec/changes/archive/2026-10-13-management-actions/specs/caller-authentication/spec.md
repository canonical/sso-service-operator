## MODIFIED Requirements

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
