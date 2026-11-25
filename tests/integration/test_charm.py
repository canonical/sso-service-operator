#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import base64
import logging
from pathlib import Path

import jubilant
import pytest
from integration.conftest import integrate_dependencies
from integration.constants import APP_IMAGE, APP_NAME, DB_APP
from integration.utils import (
    StatusPredicate,
    all_active,
    and_,
    any_error,
    get_app_integration_data,
    remove_integration,
    unit_number,
)

from src.constants import DATABASE_INTEGRATION_NAME, PUBLIC_ROUTE_INTEGRATION_NAME

logger = logging.getLogger(__name__)


def missing_integration(integration_name: str) -> StatusPredicate:
    """Every unit of the charm-under-test, at least one, is blocked on the given integration."""
    message = f"Missing integration {integration_name}"
    return lambda status: (
        bool(units := status.apps[APP_NAME].units.values())
        and all(unit.is_blocked and message in unit.workload_status.message for unit in units)
    )


def database_is_created(juju: jubilant.Juju) -> StatusPredicate:
    """The database integration of the charm-under-test carries the database's endpoints."""

    def predicate(status: jubilant.Status) -> bool:
        data = get_app_integration_data(juju, APP_NAME, DATABASE_INTEGRATION_NAME)
        return bool(data and data.get("endpoints"))

    return predicate


@pytest.mark.setup
def test_build_and_deploy(juju: jubilant.Juju, local_charm: Path) -> None:
    """Build and deploy the charm-under-test together with related charms."""
    juju.deploy(
        DB_APP,
        channel="14/stable",
        trust=True,
    )

    juju.deploy(
        str(local_charm),
        app=APP_NAME,
        resources={"oci-image": APP_IMAGE},
        trust=True,
    )

    integrate_dependencies(juju)

    # Without the rest of the identity platform the charm stays blocked on what it misses.
    # That status hides the wait for the database, which the migration needs.
    juju.wait(
        ready=and_(
            all_active(DB_APP),
            missing_integration(PUBLIC_ROUTE_INTEGRATION_NAME),
            database_is_created(juju),
        ),
        error=any_error(APP_NAME, DB_APP),
        timeout=15 * 60,
    )


def test_run_migration_action(juju: jubilant.Juju) -> None:
    """Test that the database migration runs against the related database."""
    result = juju.run(f"{APP_NAME}/leader", "run-migration")
    assert result.status == "completed"


def test_get_envelope_key_action(juju: jubilant.Juju) -> None:
    """Test that the key the leader generated can be read."""
    result = juju.run(f"{APP_NAME}/leader", "get-envelope-key")
    assert result.status == "completed"
    assert len(base64.b64decode(result.results["key"])) == 32


def test_scale_up(juju: jubilant.Juju) -> None:
    """Test scaling up to verify HA and leader election."""
    target_unit_number = 2
    juju.cli("scale-application", APP_NAME, str(target_unit_number))

    juju.wait(
        ready=and_(
            missing_integration(PUBLIC_ROUTE_INTEGRATION_NAME),
            unit_number(APP_NAME, target_unit_number),
        ),
        error=any_error(APP_NAME),
        timeout=5 * 60,
    )


def test_remove_integration(juju: jubilant.Juju) -> None:
    """Test removing and re-adding integration."""
    with remove_integration(juju, DB_APP, DATABASE_INTEGRATION_NAME):
        juju.wait(
            ready=missing_integration(DATABASE_INTEGRATION_NAME),
            error=any_error(APP_NAME),
            timeout=10 * 60,
        )
    juju.wait(
        ready=and_(all_active(DB_APP), missing_integration(PUBLIC_ROUTE_INTEGRATION_NAME)),
        error=any_error(APP_NAME, DB_APP),
        timeout=10 * 60,
    )


def test_scale_down(juju: jubilant.Juju) -> None:
    """Test scaling down to verify cluster stability."""
    target_unit_num = 1
    juju.cli("scale-application", APP_NAME, str(target_unit_num))

    juju.wait(
        ready=and_(
            missing_integration(PUBLIC_ROUTE_INTEGRATION_NAME),
            unit_number(APP_NAME, target_unit_num),
        ),
        error=any_error(APP_NAME),
        timeout=5 * 60,
    )


@pytest.mark.teardown
def test_remove_application(juju: jubilant.Juju) -> None:
    """Test removing the application."""
    juju.remove_application(APP_NAME, destroy_storage=True)
    juju.wait(lambda s: APP_NAME not in s.apps, timeout=1000)
