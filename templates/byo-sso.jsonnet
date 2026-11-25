// The byo-sso provider's mapper.
// Kratos runs it only for a subject with no link: sso-service lets one through
// only for a member's address (an account with it exists: Kratos's registration
// stops at the unique address and turns into account linking, so the account's
// owner signs in before Kratos adds the link) or for an address a pending
// invitation or auto-join admits (no account: Kratos registers it). The mapper
// never runs at login. The address is marked verified only when the id_token
// says so; otherwise login-ui's verification step proves it (VERIFICATION_ENABLED).
local claims = std.extVar('claims');

{
  identity: {
    traits: {
      email: claims.email,
    },
    verified_addresses: std.prune([
      if std.objectHas(claims, 'email_verified') && claims.email_verified == true then
        { via: 'email', value: claims.email },
    ]),
  },
}
