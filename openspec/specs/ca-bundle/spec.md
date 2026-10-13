# ca-bundle Specification

## Purpose

Some endpoints that the service calls have a certificate from a local certificate authority. The workload then needs the certificate of that authority. This capability says how the charm gets the CA certificates over `receive-ca-cert`, how it puts them in the workload, and when it restarts the service.

Key decisions:

- **The charm keeps a copy of the CA bundle that it applied**. The charm acts only when the CA bundle of the relations differs from the copy.
- **One read in a hook**. The library of the interface consumes a bundle that a provider sent as unit data. A second read in the same hook can give another bundle, and then the service restarts for no reason.
- **The comparison is byte for byte**. As text, a bundle with CRLF line ends never equals its copy.
- **A failed update puts the copy back**. The next reconciliation then finds the difference and tries again.
- **The charm applies the CA bundle only in a hook that plans the service**. The service never loads a file that the charm pushes without a restart.
- **A changed file restarts the service**. The service is a Go program and loads the system certificates one time.
- **A workload container that restarted gets the file again**, because such a container lost the file that the charm pushed.

Non-goals:

- A status for a CA bundle that the charm did not apply.
- A check of the certificates. The charm uses the `ca` value of a remote unit as the unit wrote it.
- A stable CA bundle for a provider with one unit that uses the older form of the interface. In a `relation-changed` hook of `receive-ca-cert`, the charm reads no certificate of such a provider.
- Certificates for the listeners of the service.
- Client certificates.

## Requirements
### Requirement: The CA bundle from the relation
The charm SHALL build the CA bundle from all the `receive-ca-cert` relations (interface `certificate_transfer`). The relation is optional. The CA bundle holds these certificates:

- The certificates that the library of the interface gives for the relations.
- The `ca` value in the data of each remote unit that the relation still lists after the read of the library. The charm uses the value as the unit wrote it.

The charm removes duplicates, sorts the certificates and joins them with a line feed. The charm SHALL read the CA bundle from the relations at most one time in a hook, and use that value for the whole hook.

The charm relies on the library for the certificates of each provider. A provider sends its certificates in its application data, or in the data of its units, which is the older form. For the older form, each read of the library takes one unit out of the units of the relation. The library gives the `chain` of that unit. In a `relation-changed` hook of `receive-ca-cert`, the library reads one time before the charm reads.

#### Scenario: A hook that reconciles 2 times
- **WHEN** one hook runs the reconciliation 2 times and a provider sent its certificates as unit data
- **THEN** both reconciliations use the same CA bundle
- **AND** the service does not restart because of the second reconciliation

#### Scenario: A provider with one unit that uses the older form
- **WHEN** a `relation-changed` hook of `receive-ca-cert` runs for a provider with one unit that sends unit data only
- **THEN** the CA bundle of the charm has no certificate of that provider in that hook
- **AND** in a hook of another kind, the CA bundle has the `chain` of that unit

### Requirement: The charm applies a changed CA bundle and restarts the service
The charm SHALL keep a copy of the CA bundle that it last applied, in the file `/tmp/charm/charm-certificates.crt` of the charm container. The charm SHALL compare the CA bundle with the copy, byte for byte. The charm does this in each reconciliation in which conditions 1 to 12 of `workload-service` are true. When they are equal, the charm does nothing. When they differ, the charm SHALL do these steps:

1. Write the CA bundle to the copy. When the CA bundle is empty, the charm deletes the copy.
2. Run `update-ca-certificates --fresh --etccertsdir /tmp --localcertsdir /tmp/charm` in the charm container. The command builds `/tmp/ca-certificates.crt` from the system certificates and the copy.
3. Push `/tmp/ca-certificates.crt` to `/etc/ssl/certs/ca-certificates.crt` in the workload container, when the file there is different.
4. Restart the service in the plan of the same hook, when step 3 changed the file.

The charm SHALL NOT apply the CA bundle in a reconciliation in which one of the conditions 1 to 12 is false.

#### Scenario: A new certificate authority
- **WHEN** a provider sends a certificate in its application data over `receive-ca-cert` while the service runs
- **THEN** the charm pushes the new file to the workload container
- **AND** the charm restarts the service in the same hook

#### Scenario: The certificate authority is removed
- **WHEN** the operator removes the `receive-ca-cert` relation while the service runs
- **THEN** the charm deletes its copy and pushes a file without that certificate
- **AND** the charm restarts the service in the same hook

#### Scenario: A CA bundle with CRLF line ends
- **WHEN** the charm applied a CA bundle whose lines end with CRLF, and the next hook reads the same bundle
- **THEN** the charm does not run `update-ca-certificates` and pushes nothing

#### Scenario: The service cannot be planned yet
- **WHEN** a provider sends a certificate and hydra-sso did not publish its admin endpoint
- **THEN** the charm does not write its copy and pushes nothing
- **AND** the unit is Waiting with `Waiting for hydra-sso's endpoints`

### Requirement: The charm tries a failed update again
When the update of the CA bundle fails, the charm SHALL write the error to its log. The charm SHALL also put its copy back as it was before the update. The charm SHALL NOT plan the service in that reconciliation. The next reconciliation then finds the same difference and does all the steps again. The charm sets no status for a failed update.

The update fails in each of these cases:

- `update-ca-certificates` exits with an error, or the charm cannot run it.
- Pebble refuses the push to the workload container.
- Pebble does not answer in time.

#### Scenario: The push to the workload fails
- **WHEN** Pebble refuses the push of the new file
- **THEN** the charm puts its copy back as it was and does not plan the service
- **AND** the next reconciliation pushes the file again

#### Scenario: The removal of a certificate fails
- **WHEN** the CA bundle becomes empty and `update-ca-certificates` exits with an error
- **THEN** the charm writes the earlier CA bundle to its copy again
- **AND** the next reconciliation tries the removal again

### Requirement: A workload container that restarted gets the CA bundle again
When the workload container becomes ready, the charm SHALL delete its copy of the CA bundle before it reconciles. When the CA bundle is not empty, the reconciliation then finds a difference and applies the CA bundle again. A workload container that restarts alone loses the file that the charm pushed.

#### Scenario: The workload container restarts alone
- **WHEN** the workload container restarts and the charm container does not
- **THEN** the charm pushes the CA bundle to the workload container again

#### Scenario: A hook of another kind
- **WHEN** a `config-changed` hook runs and the CA bundle equals the copy of the charm
- **THEN** the charm pushes nothing

