# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock

import pytest
from ops import ModelError, SecretNotFoundError

from constants import ENVELOPE_KEY_SECRET_KEY, ENVELOPE_KEY_SECRET_LABEL
from exceptions import InvalidConfigError, InvalidEnvelopeKeyError
from secret import Secrets, get_initial_envelope_key, validate_envelope_key

KEY = "A" * 43 + "="


class TestValidateEnvelopeKey:
    @pytest.mark.parametrize("key", ["short", "!" * 44])
    def test_refused(self, key: str) -> None:
        with pytest.raises(InvalidEnvelopeKeyError):
            validate_envelope_key(key)


class TestGetInitialEnvelopeKey:
    def test_not_configured(self) -> None:
        assert get_initial_envelope_key(MagicMock(), None) is None

    @pytest.mark.parametrize("stored", [KEY, KEY + "\n"], ids=["key", "key from a file"])
    def test_read_with_refresh(self, stored: str) -> None:
        model = MagicMock()
        model.get_secret.return_value.get_content.return_value = {"key": stored}

        assert get_initial_envelope_key(model, "secret:abc") == KEY
        model.get_secret.assert_called_once_with(id="secret:abc")
        model.get_secret.return_value.get_content.assert_called_once_with(refresh=True)

    @pytest.mark.parametrize(
        "error, reason",
        [(SecretNotFoundError(), "secret not found"), (ModelError("permission denied"), "grant")],
    )
    def test_unreadable_secret(self, error: Exception, reason: str) -> None:
        """A restore that cannot read its key must not start with a new one."""
        model = MagicMock()
        model.get_secret.side_effect = error

        with pytest.raises(InvalidConfigError, match=reason):
            get_initial_envelope_key(model, "secret:abc")

    @pytest.mark.parametrize(
        "content", [{"key": "short"}, {"other": KEY}], ids=["short key", "no key entry"]
    )
    def test_unusable_key(self, content: dict) -> None:
        model = MagicMock()
        model.get_secret.return_value.get_content.return_value = content

        with pytest.raises(InvalidConfigError):
            get_initial_envelope_key(model, "secret:abc")


class TestSecrets:
    def test_reads_with_refresh(self) -> None:
        model = MagicMock()
        model.get_secret.return_value.get_content.return_value = {ENVELOPE_KEY_SECRET_KEY: KEY}

        content = Secrets(model)[ENVELOPE_KEY_SECRET_LABEL]

        assert content == {ENVELOPE_KEY_SECRET_KEY: KEY}
        model.get_secret.return_value.get_content.assert_called_once_with(refresh=True)

    def test_unknown_label(self) -> None:
        with pytest.raises(ValueError):
            Secrets(MagicMock())["other"] = {}
