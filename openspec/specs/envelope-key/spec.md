# envelope-key Specification

## Purpose

The SSO Service encrypts the client secrets of the SSO connections with one key, the envelope key. The service cannot read the client secrets of a database without the key of that database. This capability says where the key comes from, that the charm never changes it, and how an operator saves and restores it.

Key decisions:

- **The leader creates the key one time**, in a Juju secret of the application. The charm never writes that secret again.
- **A restore must use its own key**. When the option names a key that the leader cannot read, the leader creates no key and the unit blocks. With a new key, the service cannot read the client secrets of the restored database.
- **The charm checks an initial key as the service checks it**. The key is the base64 text of 32 bytes. The charm removes white space around the value, because a key that the operator adds from a file ends with a line feed.
- **The option cannot change a key that exists**. The charm blocks and says so, and the service continues with the key in use.
- **The operator gets the key with an action**, to keep it with the backups of the database.

Non-goals:

- Rotation of the envelope key.
- A link between the key and the database. An application that the operator removes and deploys again makes a new key, unless the option gives the old key.
- A result of `get-envelope-key` that only some users can read. Whoever can read the model can read the result.
- A key management service.

## Requirements
### Requirement: The leader creates the envelope key one time
When the application has no envelope key, the leader SHALL create a Juju secret of the application with the label `envelopekey`. The secret has one entry, `key`. The value of `key` is one of these:

- The initial key, when the `initial_envelope_key_secret_id` option is set (see the next requirement).
- A new key in all other cases. A new key is the base64 text of 32 random bytes.

When the secret exists, the charm SHALL NOT change its content. A unit that is not the leader SHALL NOT create the secret. The charm SHALL give the service the key in `ENVELOPE_KEY`. Each unit reads the latest revision of the secret.

#### Scenario: The first reconciliation of the leader
- **WHEN** the leader reconciles, the application has no envelope key and the option is not set
- **THEN** the leader creates the secret `envelopekey` with a new key of 44 base64 characters
- **AND** the charm plans the service with that key in `ENVELOPE_KEY`

#### Scenario: A unit that is not the leader
- **WHEN** a unit that is not the leader reconciles and the application has no envelope key
- **THEN** the unit creates no secret and does not plan the service
- **AND** the unit is Waiting with `Waiting for secrets creation`

### Requirement: The initial envelope key
The `initial_envelope_key_secret_id` option SHALL name a Juju secret that holds the envelope key to start with, in the entry `key`. The charm removes white space at the start and at the end of the value. The key is usable only when it is the base64 text of exactly 32 bytes.

When the leader cannot read the secret, or the key is not usable, the leader SHALL NOT create an envelope key. While the application has no envelope key, the unit is then Blocked with `Invalid configuration: <reason>`. The reason is one of these:

| reason | when |
|---|---|
| `initial_envelope_key_secret_id: secret not found` | the secret does not exist |
| `initial_envelope_key_secret_id: cannot read the secret, grant it to the application` | the charm cannot read the secret for another cause |
| ``initial_envelope_key_secret_id: the secret has no `key` entry`` | the secret has no entry `key` |
| `initial_envelope_key_secret_id: the key is not base64` | the value is not base64 text |
| `initial_envelope_key_secret_id: the key is not 32 bytes` | the value does not decode to 32 bytes |

#### Scenario: A restore into a new deployment
- **WHEN** the operator deploys the application with the option set to a secret that holds a usable key
- **AND** the operator grants the secret to the application
- **THEN** the leader creates the secret `envelopekey` with the key of the operator
- **AND** the charm plans the service with that key in `ENVELOPE_KEY`

#### Scenario: A key that is too short
- **WHEN** the option names a secret whose `key` decodes to fewer than 32 bytes
- **THEN** the leader creates no envelope key
- **AND** the unit is Blocked with `Invalid configuration: initial_envelope_key_secret_id: the key is not 32 bytes`

### Requirement: The option does not change a key that exists
When the application has an envelope key, the charm SHALL NOT change the key, whatever the value of `initial_envelope_key_secret_id`. The charm compares the option with the key in use in every hook:

| the option | status |
|---|---|
| is not set, or names the key in use | none |
| names a usable key that is not the key in use | Blocked, `initial_envelope_key_secret_id is not the key in use (unchanged): remove and redeploy the application to change it` |
| names a secret that the charm cannot read, or a key that is not usable | Blocked, `Cannot compare initial_envelope_key_secret_id with the key in use (unchanged): grant or fix its secret, or unset it` |

These 2 statuses SHALL NOT stop the plan of the service. The service continues to run with the key in use.

#### Scenario: The option is set to another key after the first start
- **WHEN** the application has an envelope key and the operator sets the option to a secret with another key
- **THEN** the unit is Blocked with the status that says that the option is not the key in use
- **AND** the charm plans the service with the key in use in `ENVELOPE_KEY`

### Requirement: The get-envelope-key action
The charm SHALL offer the action `get-envelope-key`, with no parameter. The action returns the envelope key in the result `key`. The operator can run the action on any unit. When the application has no envelope key, the action fails with `Juju secrets are not ready yet`.

#### Scenario: A backup of the key
- **WHEN** the operator runs `get-envelope-key` on a unit of an application that has an envelope key
- **THEN** the result `key` is the envelope key

#### Scenario: No key yet
- **WHEN** the operator runs `get-envelope-key` before the leader created the envelope key
- **THEN** the action fails with `Juju secrets are not ready yet`

