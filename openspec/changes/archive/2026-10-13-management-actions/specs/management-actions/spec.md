## ADDED Requirements

### Requirement: The management actions
The charm SHALL offer these 10 actions. Each action runs one management command of the `sso-service` binary in the workload container of the unit. The operator can run an action on any unit.

| action | required parameters | optional parameters | what the action does |
|---|---|---|---|
| `list-connections` | none | `tenant-id`, `page-size`, `page-token` | lists the SSO connections of a tenant, or of every tenant when `tenant-id` is not given |
| `get-connection` | `tenant-id`, `connection-id` | none | gets one SSO connection |
| `create-connection` | `tenant-id`, `label`, `issuer`, `client-id`, `client-secret-id` | none | creates an SSO connection to the identity provider of a tenant |
| `update-connection` | `tenant-id`, `connection-id` | `label`, `client-secret-id` | changes the label or the client secret of an SSO connection |
| `delete-connection` | `connection-id` | none | deletes an SSO connection of any tenant |
| `test-connection` | `tenant-id`, `connection-id` | none | gets the URL of a test sign-in through an SSO connection |
| `get-policy` | `tenant-id` | none | gets the SSO policy of a tenant |
| `set-policy` | `tenant-id`, `enforcement` | `bindings`, `auto-join` | replaces the enforcement, the bindings and the auto-join setting of a tenant |
| `get-domains` | `tenant-id` | none | gets the email domains of a tenant |
| `set-domains` | `tenant-id` | `domains` | replaces the email domains of a tenant |

`page-size` is an integer. `auto-join` is a boolean with the default `false`. Every other parameter is a string. `bindings` and `domains` are lists with commas.

#### Scenario: The connections of one tenant
- **WHEN** the operator runs `list-connections` with `tenant-id=t1`
- **THEN** the charm runs the command `connection list` for the tenant `t1` in the workload of that unit
- **AND** the action returns what the command printed

#### Scenario: An action on a unit that is not the leader
- **WHEN** the operator runs `get-policy` on a unit that is not the leader
- **THEN** the charm runs the command in the workload of that unit

### Requirement: The command of an action
The charm SHALL build the command of each action in this shape: `sso-service <group> <verb> <flags of the charm> <flags of the action> -- <positionals>`. The parts are these:

- The flags of the charm are `--grpc-endpoint=localhost:50051` and `--token=<token>`, in this order.
- A flag of the action has its value in the same argument, after `=`. The charm leaves out a flag whose parameter is empty or not given.
- Every value that is not a flag comes after the `--` argument.

| action | group and verb | flags of the action | positionals |
|---|---|---|---|
| `list-connections` | `connection list` | `--page-size`, `--page-token` | `tenant-id`, when the operator gives it |
| `get-connection` | `connection get` | none | `tenant-id`, `connection-id` |
| `create-connection` | `connection create` | `--label`, `--issuer`, `--client-id` | `tenant-id` |
| `update-connection` | `connection update` | `--label` | `tenant-id`, `connection-id` |
| `delete-connection` | `connection delete` | none | `connection-id` |
| `test-connection` | `connection test` | none | `tenant-id`, `connection-id` |
| `get-policy` | `policy get` | none | `tenant-id` |
| `set-policy` | `policy set` | `--enforcement`, one `--binding` for each item of `bindings`, and `--auto-join` with no value when `auto-join` is true | `tenant-id` |
| `get-domains` | `domains get` | none | `tenant-id` |
| `set-domains` | `domains set` | none | `tenant-id`, then each item of `domains` |

The charm splits `bindings` and `domains` at each comma and at white space. The charm gives the command to Pebble as a list of arguments, and uses no shell. Thus the command reads nothing that the operator types in a parameter as a flag. The time limit of a command is 20 seconds. The command does not get the environment of the service.

#### Scenario: A new SSO connection
- **WHEN** the operator runs `create-connection` with `tenant-id=t`, `label=Okta`, `issuer=https://idp.example.com`, `client-id=portal` and a `client-secret-id`
- **THEN** the arguments are `sso-service connection create --grpc-endpoint=localhost:50051 --token=<token> --label=Okta --issuer=https://idp.example.com --client-id=portal -- t`

#### Scenario: A value that starts with a dash
- **WHEN** the operator runs `update-connection` with `tenant-id=--grpc-endpoint=other:1`, `connection-id=c` and `label=--token=other`
- **THEN** the charm passes `--label=--token=other` as one argument
- **AND** `--grpc-endpoint=other:1` and `c` come after the `--` argument
- **AND** the first 2 flags of the command are still the flags of the charm

#### Scenario: Bindings of a policy
- **WHEN** the operator runs `set-policy` with `tenant-id=t`, `enforcement=required` and `bindings=c1,c2:inactive`
- **THEN** the flags of the action are `--enforcement=required`, `--binding=c1` and `--binding=c2:inactive`

#### Scenario: A policy with no bindings
- **WHEN** the operator runs `set-policy` with `tenant-id=t` and `enforcement=optional` only
- **THEN** the command has the flag `--enforcement=optional`, and no `--binding` flag and no `--auto-join` flag

#### Scenario: No domains
- **WHEN** the operator runs `set-domains` with `tenant-id=t` and no `domains`
- **THEN** the command has the one positional `t`

### Requirement: The token of the OAuth client of the service
Before each command, the charm SHALL ask the main Hydra for an access token of the OAuth client of the service. The charm gives the token to the command in the `--token` flag. The request for the token has these properties:

- It goes to the token endpoint that the main Hydra publishes over the `oauth` relation.
- It uses the `client_credentials` grant, with the client id and the client secret as HTTP basic authentication.
- It asks for no scope.
- It has a timeout of 10 seconds. The timeout applies to the connection, and then to each wait for data of the answer.
- It verifies the certificate of the endpoint. When the file `/tmp/ca-certificates.crt` exists in the charm container, the charm verifies against that file (see `ca-bundle`). In all other cases, the charm uses the certificates that come with the HTTP library.

An action SHALL NOT fail before the command because the charm has no token. When the charm has no token, it SHALL give the command `--token=no-token`. The service refuses that value, and the action fails with the error of the command. The charm has no token in these cases:

1. The `oauth` relation gives no client id or no client secret. The charm then does not send the request.
2. The request fails, or the endpoint answers with an error status.
3. The answer is not JSON, or it is a JSON object with no `access_token`.
4. The `access_token` of the answer is empty.

In cases 2 and 3, the charm writes `Failed to obtain management token` to its log. An error of another kind fails the action with `Failed to <verb> <noun>: <error>`, and the management command does not run. Examples are a Juju secret of the client that the charm cannot read, and an answer that is JSON but not an object.

#### Scenario: The main Hydra gives a token
- **WHEN** the operator runs `get-policy` and the main Hydra answers the request with a token
- **THEN** the charm runs the command with that token in the `--token` flag

#### Scenario: No OAuth client
- **WHEN** the operator runs `get-policy` and the `oauth` relation gives no client
- **THEN** the charm runs the command with `--token=no-token`
- **AND** the action fails with a message that starts with `Failed to get policy:`

#### Scenario: The token endpoint does not answer
- **WHEN** the operator runs an action and the request for the token fails
- **THEN** the charm writes `Failed to obtain management token` to its log
- **AND** the charm runs the command with `--token=no-token`

### Requirement: The client secret of an identity provider comes from a Juju secret
The actions `create-connection` and `update-connection` SHALL take the client secret of the identity provider from a Juju secret. The `client-secret-id` parameter is the id of that secret. The secret holds the client secret in the entry `client-secret`, and the operator must grant the secret to the application. The charm reads the latest revision of the secret, and removes the line ends at the end of the value.

The charm SHALL give the client secret to the command in the environment variable `CLIENT_SECRET`. The charm SHALL NOT put the client secret in the arguments of the command. When `update-connection` has no `client-secret-id`, the charm does not set `CLIENT_SECRET`.

When the charm cannot use the secret, the action fails before the charm asks for a token, and the management command does not run. The message of the failure ends with one of these texts:

| text | when |
|---|---|
| `Cannot read the secret <id>: grant it to this application` | the secret does not exist, or the charm cannot read it |
| ``The secret <id> has no `client-secret` entry`` | the secret has no entry `client-secret`, or the entry is empty |

#### Scenario: A secret that the operator added from a file
- **WHEN** the entry `client-secret` of the secret is `idp-secret` and a line feed
- **THEN** the command runs with `CLIENT_SECRET` set to `idp-secret`
- **AND** no argument of the command holds the client secret

#### Scenario: A secret that the operator did not grant
- **WHEN** the operator runs `update-connection` with the id of a secret that the application cannot read
- **THEN** the action fails with `Failed to update connection: Cannot read the secret <id>: grant it to this application`
- **AND** the charm does not run the management command

### Requirement: Results and failures of an action
When the command succeeds, the action SHALL return what the command wrote to standard output, in the result `output`. When the charm cannot connect to the workload container, the action SHALL fail with `Workload container is not ready`. For every other error, the action SHALL fail with `Failed to <verb> <noun>: <error>`. The verb and the noun are these:

| action | start of the message |
|---|---|
| `list-connections` | `Failed to list connections:` |
| `get-connection` | `Failed to get connection:` |
| `create-connection` | `Failed to create connection:` |
| `update-connection` | `Failed to update connection:` |
| `delete-connection` | `Failed to delete connection:` |
| `test-connection` | `Failed to test connection:` |
| `get-policy` | `Failed to get policy:` |
| `set-policy` | `Failed to set policy:` |
| `get-domains` | `Failed to get domains:` |
| `set-domains` | `Failed to set domains:` |

When the command exits with an error, `<error>` is the text of the Pebble error. That text has the exit code, the name of the executable, and the standard output and standard error of the command. The Ops library cuts each of these 2 outputs at 1024 characters. The charm relies on the Ops library to leave the arguments of the command out of that text. Thus the message does not hold the token.

The charm SHALL NOT write the arguments of a command to its log, because the token is an argument. The charm writes only the first 3 words of each command, at the debug level. When a command fails, the charm also writes its exit code and its standard error to the log.

#### Scenario: The API answers
- **WHEN** the operator runs `get-policy` and the command prints the policy as JSON
- **THEN** the result `output` of the action is that JSON text

#### Scenario: The API refuses the call
- **WHEN** the operator runs `get-policy` and the command exits with an error
- **THEN** the action fails with a message that starts with `Failed to get policy:`
- **AND** the message has the standard error of the command and does not have the token

#### Scenario: The workload container is not ready
- **WHEN** the operator runs an action and the charm cannot connect to the workload container
- **THEN** the action fails with `Workload container is not ready`
- **AND** the charm runs no command and asks for no token

### Requirement: An action refuses a parameter that it does not define
Each of the 10 management actions SHALL set `additionalProperties` to `false` in its schema. Juju then refuses a run of the action with a parameter that the action does not define. Juju also refuses a run without a required parameter. In both cases the charm does not run.

#### Scenario: A parameter with a wrong name
- **WHEN** the operator runs `set-domains` with `tenant-id=t` and `domain=example.com`
- **THEN** Juju refuses the run, because the action defines `domains` and not `domain`
- **AND** the domains of the tenant do not change
