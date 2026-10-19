## 1. Token

- [x] 1.1 Add the request for the token, with its certificate check and its timeout, in `src/clients.py`.
- [x] 1.2 Add `requests`, and `types-requests` for development, to `pyproject.toml` and `uv.lock`.

## 2. Commands

- [x] 2.1 Add the flags of the charm and one method for each management command in `src/cli.py`.
- [x] 2.2 Pass the client secret of `connection create` and `connection update` in the environment, in `src/cli.py`.

## 3. Actions

- [x] 3.1 Declare the 10 actions in `charmcraft.yaml`, each with `additionalProperties` set to `false`.
- [x] 3.2 Add the handler of each action in `src/charm.py`.
- [x] 3.3 Add the token of the OAuth client of the service in `src/charm.py`.
- [x] 3.4 Read the client secret from a Juju secret in `src/charm.py`, with the name of its entry in `src/constants.py`.

## 4. Caller authentication

- [x] 4.1 Add the client of the service to the allowed subjects, when the operator restricts the callers, in `src/integrations.py`.
- [x] 4.2 Describe that rule in the `authn_allowed_subjects` option in `charmcraft.yaml`.

## 5. Tests

- [x] 5.1 Add the tests of the actions, the token and the client secret in `tests/unit/test_actions.py`.
- [x] 5.2 Add the tests of the commands in `tests/unit/test_cli.py` and of the token request in `tests/unit/test_clients.py`.
- [x] 5.3 Add the test of the allowed subjects in `tests/unit/test_integrations.py`.
- [x] 5.4 Move the tests of `run-migration` and `get-envelope-key` from `tests/unit/test_charm.py` to `tests/unit/test_actions.py`.
- [x] 5.5 Add the fixtures of the action tests in `tests/unit/conftest.py`.

## 6. Verification

- [x] 6.1 Run `openspec validate management-actions --strict`.
