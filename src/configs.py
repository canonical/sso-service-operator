# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper class to manage the charm's config."""

from typing import cast

from ops import ConfigData

from env_vars import EnvVars


class CharmConfig:
    """A class representing the data source of charm configurations."""

    def __init__(self, config: ConfigData) -> None:
        self._config = config

    @property
    def dev(self) -> bool:
        """Whether this is a development deployment.

        It allows a public route without HTTPS, and sets DEV for sso-service:
        identity providers over plain http and at private addresses.
        """
        return bool(self._config.get("dev"))

    @property
    def initial_envelope_key_secret_id(self) -> str | None:
        """The id of the Juju secret holding the envelope key to start with, if any."""
        secret_id = self._config.get("initial_envelope_key_secret_id")
        return str(secret_id) if secret_id else None

    def get_oauth_config(self) -> dict[str, str | None]:
        """Get OAuth config."""
        return {
            k: cast(str, v)
            for k in [
                "authn_allowed_subjects",
                "authn_allowed_scope",
                "authn_issuer",
                "authn_jwks_url",
            ]
            if (v := self._config.get(k))
        }

    def get_proxy_config(self) -> dict[str, str]:
        """Get the proxy options, for the charm's own requests."""
        return {
            k: str(self._config.get(k) or "") for k in ["http_proxy", "https_proxy", "no_proxy"]
        }

    def get_missing_config_keys(self) -> list:
        """Get missing config keys."""
        return []

    def to_env_vars(self) -> EnvVars:
        """Get config env vars."""
        env_vars: dict[str, str | bool] = {
            "LOG_LEVEL": self._config["log_level"].upper(),
            "HTTP_PROXY": self._config.get("http_proxy"),
            "HTTPS_PROXY": self._config.get("https_proxy"),
            "NO_PROXY": self._config.get("no_proxy"),
        }
        # DEV only with dev: nothing, not DEV=false, without.
        if self.dev:
            env_vars["DEV"] = "true"
        return env_vars
