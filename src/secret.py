# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the charm's secrets."""

import base64
import binascii
import secrets
from collections.abc import ValuesView

from ops import Model, SecretNotFoundError

from constants import ENVELOPE_KEY_BYTES, ENVELOPE_KEY_SECRET_KEY, ENVELOPE_KEY_SECRET_LABEL
from env_vars import EnvVars
from exceptions import InvalidConfigError, InvalidEnvelopeKeyError


class Secrets:
    """An abstraction of the charm secret management."""

    KEYS = (ENVELOPE_KEY_SECRET_KEY,)
    LABELS = (ENVELOPE_KEY_SECRET_LABEL,)

    def __init__(self, model: Model) -> None:
        self._model = model

    def __getitem__(self, label: str) -> dict[str, str] | None:
        if label not in self.LABELS:
            return None
        try:
            secret = self._model.get_secret(label=label)
        except SecretNotFoundError:
            return None
        # Refresh: since Juju 3.3.1 a secret's owners no longer track its
        # latest revision on their own (https://bugs.launchpad.net/juju/+bug/2037120).
        return secret.get_content(refresh=True)

    def __setitem__(self, label: str, content: dict[str, str]) -> None:
        if label not in self.LABELS:
            raise ValueError(f"Invalid label: '{label}'. Valid labels are: {self.LABELS}.")
        self._model.app.add_secret(content, label=label)

    def values(self) -> ValuesView:
        """All secret values."""
        secret_contents = {}
        for key, label in zip(self.KEYS, self.LABELS):
            try:
                secret = self._model.get_secret(label=label)
            except SecretNotFoundError:
                return ValuesView({})
            else:
                secret_contents[key] = secret.get_content(refresh=True)
        return secret_contents.values()

    def to_env_vars(self) -> EnvVars:
        """Secret env vars."""
        return {
            "ENVELOPE_KEY": self.envelope_key,
        }

    def is_ready(self) -> bool:
        """Check if all secrets are ready."""
        values = self.values()
        return all(values) if values else False

    @property
    def envelope_key(self) -> str:
        """The envelope key.

        Raises:
            ValueError: If the envelope key secret has not been created yet.
        """
        content = self[ENVELOPE_KEY_SECRET_LABEL]
        if content is None:
            raise ValueError("Envelope key secret is not available")
        return content[ENVELOPE_KEY_SECRET_KEY]


def validate_envelope_key(key: str) -> None:
    """Check a key the way sso-service will.

    Args:
        key: The key to check.

    Raises:
        InvalidEnvelopeKeyError: If it is not usable.
    """
    try:
        decoded = base64.b64decode(key, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidEnvelopeKeyError("the key is not base64") from e
    if len(decoded) != ENVELOPE_KEY_BYTES:
        raise InvalidEnvelopeKeyError(f"the key is not {ENVELOPE_KEY_BYTES} bytes")


def generate_envelope_key() -> str:
    """Generate a new key: the base64 of 32 random bytes."""
    return base64.b64encode(secrets.token_bytes(ENVELOPE_KEY_BYTES)).decode()


def get_initial_envelope_key(model: Model, secret_id: str | None) -> str | None:
    """Get the envelope key to start with from the Juju secret the configuration names.

    Args:
        model: The charm's model.
        secret_id: The value of initial_envelope_key_secret_id.

    Returns:
        The key, or None when no secret is configured.

    Raises:
        InvalidConfigError: If the secret cannot be read or holds no usable key.
    """
    if not secret_id:
        return None

    try:
        content = model.get_secret(id=secret_id).get_content(refresh=True)
    except SecretNotFoundError as e:
        # A restore that cannot read its key must not start with a new
        # one: the database's client secrets would be unreadable.
        raise InvalidConfigError("initial_envelope_key_secret_id: secret not found") from e
    except Exception as e:
        raise InvalidConfigError(
            "initial_envelope_key_secret_id: cannot read the secret, grant it to the application"
        ) from e

    if (key := content.get(ENVELOPE_KEY_SECRET_KEY)) is None:
        raise InvalidConfigError(
            f"initial_envelope_key_secret_id: the secret has no `{ENVELOPE_KEY_SECRET_KEY}` entry"
        )
    # As sso-service reads it: a key added from a file ends with a newline.
    key = key.strip()
    try:
        validate_envelope_key(key)
    except InvalidEnvelopeKeyError as e:
        raise InvalidConfigError(f"initial_envelope_key_secret_id: {e}") from e
    return key
