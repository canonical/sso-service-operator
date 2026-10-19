## Context

See `proposal.md` for the motivation. The `sso-service` binary has the management commands `connection`, `policy` and `domains`. Each command is a client of the API of a service that runs. A command takes the address of the gRPC listener in `--grpc-endpoint` and a token in `--token`. The commands `connection create` and `connection update` can read the client secret from the environment variable `CLIENT_SECRET`.

The management API authenticates its callers (see `caller-authentication`). The service already has an OAuth client at the main Hydra, for its calls to the Tenant Service (see `platform-integration`).

## Goals / Non-Goals

**Goals:**

- An operator can manage SSO connections, policies and domains with `juju run`.
- No value that the operator types can change where the charm sends its token.
- A client secret of an identity provider is never a parameter of an action and never an argument of a command.

**Non-Goals:**

- A second way into the data of the service. The actions call the API.
- A token for the operator.

## Decisions

### Decision 1: An action runs the command of the service

- **Decision**: Each action runs the matching management command in the workload container of the unit. The command calls the API on `localhost:50051`.
- **Rationale**: The commands are clients of the API of the service that runs. Thus the checks and the errors of an action are those of the service.

### Decision 2: The charm calls the API as the OAuth client of the service

- **Decision**: Before each command, the charm asks the main Hydra for a token of the OAuth client of the service. An action does not fail early when the client is not there. Without a token, the command runs with the placeholder `no-token`, and the service refuses the call.
- **Rationale**: The `oauth` relation already gives the service this client. The failure of an action is then the refusal of the API.
- **Consequence**: When the operator restricts the callers, the service refuses the token of its own client. Thus the charm adds that client to the allowed subjects in that state.
- **Alternative considered**: The alternative was to add the client to the allowed subjects in every state. We turned it down. With no restriction, the service admits every valid token of the issuer. A list that holds only this client refuses every other caller.

### Decision 3: The shape of a command keeps a parameter from the flags

- **Decision**: A command is `<group> <verb> <flags of the charm> <flags of the action> -- <positionals>`. The value of a flag is in the same argument as its name, after `=`.
- **Rationale**: The command reads nothing that the operator types as a flag. Without this shape, a parameter can be read as another `--grpc-endpoint`, and the command then sends the token to that address.

### Decision 4: A client secret comes from a Juju secret and goes into the environment

- **Decision**: `create-connection` and `update-connection` take the id of a Juju secret. The charm reads the client secret from the secret and gives it to the command in `CLIENT_SECRET`.
- **Rationale**: Juju keeps a record of the parameters of an action. A secret that the operator adds from a file ends with a line feed. Thus the charm removes the line ends at the end of the value.

### Decision 5: An action refuses a parameter that it does not define

- **Decision**: Each of the 10 actions sets `additionalProperties` to `false`.
- **Rationale**: Juju before version 4.0 accepts a parameter that the schema of an action does not define. Also, 3 of the actions read an absent parameter as "remove" or as "all". Thus a parameter with a wrong name did damage and did not fail:
  - `set-domains` with `domain` in place of `domains` removed every domain of the tenant.
  - `set-policy` with `binding` in place of `bindings` removed every binding.
  - `list-connections` with `tenant_id` in place of `tenant-id` listed the SSO connections of every tenant.
  - `update-connection` with `client-secret` took a client secret as a parameter, and Juju kept a record of it.

### Decision 6: The request for the token verifies the certificate and has a timeout

- **Decision**: The request verifies the certificate of the token endpoint. It uses the file that the charm builds from the CA bundle when that file exists. In all other cases, it uses the certificates of the HTTP library. The request has a timeout of 10 seconds.
- **Rationale**: The HTTP library has no timeout by default and waits with no end.

## Risks / Trade-offs

- **Another issuer**. When `authn_issuer` names another issuer than the main Hydra, the service does not accept the token of its own client. The actions then fail as unauthenticated.
- **A wider token in a restricted deployment**. The service presents the token of its client to the Tenant Service. When the operator restricts the callers, the management API of the service also admits that token.
- **No message about a client that is not there**. Without the OAuth client, the operator sees the refusal of the API. The message does not say that the client is not there.
- **No cause in the log line**. When the request for the token fails, the log has `Failed to obtain management token` and not the cause. An example is a main Hydra with a certificate from a local certificate authority and no `receive-ca-cert` relation.
- **The failure message relies on the Ops library**. The library leaves the arguments of a failed command out of its error from version 3.6. An older version puts the token in the message.
