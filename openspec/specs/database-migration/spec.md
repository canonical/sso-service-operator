# database-migration Specification

## Purpose

The SSO Service keeps the SSO connections in PostgreSQL. The service does not migrate its database when it starts, and it refuses to start while a migration is pending. This capability says these things:

- how the charm gets the database
- which unit migrates the database, and when
- what a unit shows when a migration or its check fails

Key decisions:

- **The leader migrates in the reconciliation, and the other units do not migrate**. Each of the other units plans the service when its own check finds no pending migration. After a migration, the leader writes the version of the workload to the peer relation. A change of that value makes the other units reconcile.
- **One check in a hook**. The check is a command in the workload. The charm asks one time, whatever the answer is, and uses the answer for the plan and for the status.
- **A check that fails migrates nothing**. The charm then does not know if a migration is pending. Thus the charm does not migrate and does not plan the service.
- **A failure shows its cause in `juju status`**. `juju status` shows 120 characters of a message, and the cause of a failed command is at the end of its error. Thus a reason that is too long keeps its end, and the log has the whole reason.
- **The charm percent-encodes the user and the password in the `DSN`**. Without the encoding, a password with `@`, `/` or `?` gives a connection string that does not parse.
- **The log never has a whole command line**, because the `DSN` is an argument and holds the password of the database.

Non-goals:

- A rollback of a migration. The charm runs only `migrate up`.
- A backup of the database before a migration.
- A status of a failed migration that stays after the hook. The Blocked status applies only in the hook in which the migration failed.
- Settings for TLS on the connection to PostgreSQL. The `DSN` has no parameters.

## Requirements
### Requirement: The database connection
The charm SHALL ask PostgreSQL for one database over the `pg-database` relation (interface `postgresql_client`). The name of the database is `<model name>_<application name>`. The charm SHALL give the service the connection string in `DSN`, in the form `postgres://<user>:<password>@<endpoint>/<database>`. The endpoint is the first endpoint that PostgreSQL publishes. The charm SHALL percent-encode the user and the password.

#### Scenario: A password with reserved characters
- **WHEN** PostgreSQL gives the user `u/1` and the password `p@ss/w?rd`
- **THEN** the `DSN` starts with `postgres://u%2F1:p%40ss%2Fw%3Frd@`

### Requirement: The leader migrates the database before the service starts
The charm SHALL ask the workload if a migration is pending with the command `sso-service migrate check --dsn <DSN> -f json`. No migration is pending when the `status` of the answer is `ok`. The time limit of the check is 20 seconds.

When a migration is pending and conditions 1 to 5 of `workload-service` are true, the leader SHALL run `sso-service migrate up --dsn <DSN> -f json` in the workload. The time limit of that command is 120 seconds. After the migration succeeds, the leader SHALL write the version of the workload to `migration_completed` in the peer relation `sso-service`. The leader then continues with the plan of the service in the same hook.

A unit that is not the leader SHALL NOT migrate the database in a reconciliation. Such a unit plans the service when its own check finds no pending migration. A change of the value of `migration_completed` makes the other units reconcile. When a migration does not change the value, the other units find the migrated database in their next reconciliation.

#### Scenario: A database with a pending migration
- **WHEN** the leader reconciles and the workload answers that a migration is pending
- **THEN** the leader runs `sso-service migrate up` in the workload
- **AND** the leader writes the version of the workload to `migration_completed`
- **AND** the leader plans the service in the same hook

#### Scenario: A unit that is not the leader
- **WHEN** a unit that is not the leader reconciles while a migration is pending
- **THEN** the unit runs no migration and does not plan the service
- **AND** the unit is Waiting with `Waiting for leader unit to run the migration`

### Requirement: One migration check in a hook
The charm SHALL ask the workload at most one time in a hook if a migration is pending. The charm uses the answer, or the error of the check, for the rest of the hook. After the leader migrates the database in a hook, the charm SHALL take the database as migrated for the rest of that hook.

The check fails in each of these cases:

- The command exits with an error.
- Pebble cannot run the command.
- The command writes to standard error.

When the check fails, the charm does not know if a migration is pending. Thus the charm SHALL NOT migrate the database and SHALL NOT plan the service in that hook.

#### Scenario: The check fails
- **WHEN** the leader reconciles and `sso-service migrate check` exits with an error
- **THEN** the leader does not run `sso-service migrate up`
- **AND** the charm does not plan the service
- **AND** the unit is Blocked with `Migration check failed: <reason>`

#### Scenario: One check in a hook
- **WHEN** an `update-status` hook runs on a unit whose database is migrated
- **THEN** the charm runs `sso-service migrate check` one time in that hook

### Requirement: A failed migration or check blocks with its reason
When the migration fails in a reconciliation, the unit SHALL be Blocked with `Database migration failed: <reason>` at the end of that hook. When the check fails, the unit SHALL be Blocked with `Migration check failed: <reason>`. The reason is one of these texts:

- What the command wrote to standard error, on one line. The charm replaces each run of white space with one space.
- `exit code <n>, nothing on stderr`, when the command failed and wrote nothing to standard error.
- The text of the Pebble error, as it is, for every other failure of the command.
- `Migration check error: <standard error>`, on one line, when the check exits with status 0 and writes to standard error.

`juju status` shows 120 characters of a status message. When the message is longer, the charm SHALL cut the start of the reason and put `...` in its place. The message then has exactly 120 characters and keeps the end of the reason. The log of the unit has the whole reason.

The leader SHALL try the migration again in every reconciliation in which a migration is still pending. The status `Database migration failed: <reason>` applies only in the hook in which the migration failed. After a hook that does not reconcile, the leader is Waiting with `Waiting for database migration`.

#### Scenario: A reason that fits
- **WHEN** the migration of the leader fails and the command writes `lock timeout` to standard error
- **THEN** the unit is Blocked with `Database migration failed: lock timeout`

#### Scenario: A reason that does not fit
- **WHEN** the check fails with a reason that makes the message longer than 120 characters
- **THEN** the message of the status has exactly 120 characters
- **AND** the message starts with `Migration check failed: ...`
- **AND** the message ends with the end of the reason

### Requirement: The run-migration action
The charm SHALL offer the action `run-migration`. Its one parameter is `timeout`, an integer of seconds with a minimum of 1 and a default of 120. The action runs `sso-service migrate up` in the workload of the unit, with `timeout` as the time limit of the command. The operator can run the action on any unit.

The action fails with one of these messages:

| message | when |
|---|---|
| `Workload container is not ready` | the charm cannot connect to the workload container |
| `The database is not ready` | PostgreSQL did not create the database |
| `Database migration failed: <reason>` | the command failed |

When the command succeeds on the leader, the leader SHALL write the version of the workload to `migration_completed`. On every unit, the charm then writes `Database migration succeeded` to the log of the action and runs a reconciliation.

#### Scenario: A migration that needs more time
- **WHEN** the operator runs `run-migration` with `timeout=600`
- **THEN** the charm runs `sso-service migrate up` with a time limit of 600 seconds

#### Scenario: No database
- **WHEN** the operator runs `run-migration` before PostgreSQL created the database
- **THEN** the action fails with `The database is not ready`

### Requirement: A removed database relation stops the service
When the `pg-database` relation is removed, the charm SHALL stop the service, if the charm can connect to the workload container. The status `Missing integration pg-database` then applies. When the relation and the database exist again, a reconciliation plans the service again.

#### Scenario: The relation is removed and added again
- **WHEN** the operator removes the `pg-database` relation while the service runs
- **THEN** the charm stops the service
- **AND** after the operator adds the relation again and PostgreSQL creates the database, the charm starts the service

### Requirement: Command lines stay out of the log
The charm SHALL NOT write the arguments of a workload command to its log, because the `DSN` holds the password of the database. For each command, the charm writes only the first 3 words of the command, at the debug level. When a command fails, the charm writes its exit code, its standard error and the Pebble error. The charm relies on the Ops library to name only the executable in the Pebble error.

#### Scenario: A migration fails
- **WHEN** `sso-service migrate up` fails
- **THEN** the log of the unit has the exit code and the standard error of the command
- **AND** the charm writes no argument of the command to the log

