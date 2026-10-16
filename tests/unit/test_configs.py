# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest

from configs import CharmConfig


class TestCharmConfig:
    @pytest.fixture
    def full_config(self) -> dict:
        return {
            "log_level": "debug",
            "http_proxy": "http://proxy:6666",
            "https_proxy": "http://proxy:6666",
            "no_proxy": "localhost",
            "dev": True,
            "initial_envelope_key_secret_id": "secret:abc",
            "authn_allowed_subjects": "user1",
            "authn_allowed_scope": "email",
            "authn_issuer": "https://issuer.example.com",
            "authn_jwks_url": "https://jwks.example.com",
        }

    @pytest.fixture
    def minimal_config(self) -> dict:
        return {
            "log_level": "info",
        }

    def test_to_env_vars(self, full_config: dict) -> None:
        config = CharmConfig(full_config)
        env = config.to_env_vars()

        assert env == {
            "LOG_LEVEL": "DEBUG",
            "HTTP_PROXY": "http://proxy:6666",
            "HTTPS_PROXY": "http://proxy:6666",
            "NO_PROXY": "localhost",
            "DEV": "true",
        }

    def test_to_env_vars_defaults(self, minimal_config: dict) -> None:
        """Without dev nothing is set: not DEV=false."""
        config = CharmConfig(minimal_config)
        env = config.to_env_vars()

        assert env == {
            "LOG_LEVEL": "INFO",
            "HTTP_PROXY": None,
            "HTTPS_PROXY": None,
            "NO_PROXY": None,
        }

    def test_get_oauth_config(self, full_config: dict) -> None:
        config = CharmConfig(full_config)
        oauth = config.get_oauth_config()

        assert oauth["authn_allowed_subjects"] == "user1"
        assert oauth["authn_allowed_scope"] == "email"
        assert oauth["authn_issuer"] == "https://issuer.example.com"
        assert oauth["authn_jwks_url"] == "https://jwks.example.com"

    def test_get_oauth_config_empty(self, minimal_config: dict) -> None:
        config = CharmConfig(minimal_config)
        oauth = config.get_oauth_config()

        assert oauth == {}

    def test_get_missing_config_keys(self, minimal_config: dict) -> None:
        config = CharmConfig(minimal_config)
        missing = config.get_missing_config_keys()

        assert missing == []
