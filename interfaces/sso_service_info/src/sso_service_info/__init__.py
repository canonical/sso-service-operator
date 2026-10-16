# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Interface library for sharing sso-service's address with other charms.

login-ui calls sso-service's SSOSignInService over gRPC; this relation tells it where.

## Getting Started

The library is a Python package in sso-service-operator's repository. Add it to the
charm's dependencies at a commit of that repository:

```
sso-service-info @ git+https://github.com/canonical/sso-service-operator@<commit>#subdirectory=interfaces/sso_service_info
```

and add `git` to the `build-packages` of the charm's part in `charmcraft.yaml`.

Provider side (sso-service):

```yaml
provides:
  sso-service-info:
    interface: sso_service_info
```

```python
from sso_service_info import SSOServiceInfoProvider

class SSOServiceCharm(CharmBase):
    def __init__(self, *args):
        self.sso_service_info = SSOServiceInfoProvider(self)
        self.framework.observe(self.sso_service_info.on.ready, self._on_ready)

    def _on_ready(self, event):
        self.sso_service_info.update_relations_app_data(grpc_url="sso-service.model.svc:50051")
```

Requirer side (login-ui):

```yaml
requires:
  sso-service-info:
    interface: sso_service_info
    limit: 1
```

```python
from sso_service_info import SSOServiceInfoRequirer

class LoginUICharm(CharmBase):
    def __init__(self, *args):
        self.sso_service_info = SSOServiceInfoRequirer(self)
        self.framework.observe(
            self.sso_service_info.on.sso_service_info_changed, self._on_changed
        )

    def _on_changed(self, event):
        grpc_url = self.sso_service_info.get_grpc_url()
```
"""

import logging
from typing import Optional

from ops.charm import CharmBase, RelationBrokenEvent, RelationChangedEvent, RelationCreatedEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from pydantic import BaseModel, ValidationError

RELATION_NAME = "sso-service-info"
INTERFACE_NAME = "sso_service_info"

logger = logging.getLogger(__name__)


class ProviderData(BaseModel):
    """Data published by sso-service into the relation databag."""

    grpc_url: str


class SSOServiceInfoReadyEvent(EventBase):
    """Event emitted when the relation is created (provider) or has data (requirer)."""


class SSOServiceInfoRemovedEvent(EventBase):
    """Event emitted when the relation is removed."""


class SSOServiceInfoProviderEvents(ObjectEvents):
    """Events for SSOServiceInfoProvider."""

    ready = EventSource(SSOServiceInfoReadyEvent)


class SSOServiceInfoRequirerEvents(ObjectEvents):
    """Events for SSOServiceInfoRequirer."""

    sso_service_info_changed = EventSource(SSOServiceInfoReadyEvent)
    sso_service_info_removed = EventSource(SSOServiceInfoRemovedEvent)


class SSOServiceInfoProvider(Object):
    """Provider side of the sso-service-info relation."""

    on = SSOServiceInfoProviderEvents()

    def __init__(self, charm: CharmBase, relation_name: str = RELATION_NAME) -> None:
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[relation_name].relation_created,
            self._on_relation_created,
        )

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        self.on.ready.emit()

    def update_relations_app_data(self, grpc_url: str) -> None:
        """Write grpc_url into all active relation databags."""
        if not self._charm.unit.is_leader():
            return

        for relation in self._charm.model.relations.get(self._relation_name, []):
            relation.data[self._charm.app].update(ProviderData(grpc_url=grpc_url).model_dump())


class SSOServiceInfoRequirer(Object):
    """Requirer side of the sso-service-info relation."""

    on = SSOServiceInfoRequirerEvents()

    def __init__(self, charm: CharmBase, relation_name: str = RELATION_NAME) -> None:
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[relation_name].relation_changed,
            self._on_relation_changed,
        )
        self.framework.observe(
            self._charm.on[relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        if not event.relation.app or not event.relation.data.get(event.relation.app):
            return
        self.on.sso_service_info_changed.emit()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        self.on.sso_service_info_removed.emit()

    def is_ready(self) -> bool:
        """Return True if the relation exists and holds a gRPC address."""
        return self.get_grpc_url() is not None

    def get_grpc_url(self) -> Optional[str]:
        """Return sso-service's gRPC address, or None if unavailable."""
        relation = self._charm.model.get_relation(self._relation_name)
        if not relation or not relation.app:
            return None
        raw = dict(relation.data[relation.app])
        if not raw.get("grpc_url"):
            return None
        try:
            return ProviderData(**raw).grpc_url
        except ValidationError:
            logger.warning("Invalid data in sso-service-info relation databag")
            return None
