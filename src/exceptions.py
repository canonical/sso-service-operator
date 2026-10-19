# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Exceptions."""


class CharmError(Exception):
    """Base class for custom charm errors."""


class PebbleError(CharmError):
    """Error for pebble related operations."""


class MigrationError(CharmError):
    """Error for database migration."""


class MigrationCheckError(CharmError):
    """Error for database migration check."""


class InvalidEnvelopeKeyError(CharmError):
    """An envelope key sso-service would refuse."""


class InvalidConfigError(CharmError):
    """Charm configuration that cannot be used."""
