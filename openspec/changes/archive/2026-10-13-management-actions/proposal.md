## Why

There is no console for the management API of the SSO Service yet. An operator needs a way to register the identity provider of a tenant, or to change the SSO policy of a tenant, without hand-written requests. The `sso-service` binary has management commands for these tasks. The charm must let an operator run them, with a token and without a client secret on a command line.

## What Changes

- The charm gets 10 actions: `list-connections`, `get-connection`, `create-connection`, `update-connection`, `delete-connection`, `test-connection`, `get-policy`, `set-policy`, `get-domains` and `set-domains`.
- Each action runs the matching management command in the workload, and returns what the command printed.
- The charm gives each command a token of the OAuth client of the service.
- `create-connection` and `update-connection` read the client secret of the identity provider from a Juju secret. The command gets the client secret in its environment.
- An action refuses a parameter that it does not define.
- When the operator restricts the callers of the management API, the charm also admits the OAuth client of the service.

## Capabilities

### New Capabilities

- `management-actions`: the 10 actions, their commands, the token, the client secret, results and failures.

### Modified Capabilities

- `caller-authentication`: the requirement "Restriction of callers by subject or scope" now also admits the OAuth client of the service.

## Non-goals

- Actions for the sign-in API of the service.
- An action that returns a token.
- A check of the values of the parameters in the charm. The command and the API check them.
- Management actions in a deployment in which `authn_issuer` names another issuer than the main Hydra.

## Impact

- `charmcraft.yaml`: the 10 actions, and the description of `authn_allowed_subjects`.
- `src/clients.py`: new, the request for the token.
- `src/cli.py`: one method for each management command.
- `src/charm.py`: the handlers of the actions, the token and the client secret.
- `src/integrations.py`: the client of the service in the allowed subjects.
- `src/constants.py`: the name of the entry of the client secret.
- `pyproject.toml` and `uv.lock`: the new dependency `requests`, and `types-requests` for development.
- `tests/unit/`: `test_actions.py`, `test_cli.py`, `test_clients.py`, `test_integrations.py`, `test_charm.py` and `conftest.py`.
- **Image**: the image of the service must have the management commands.
