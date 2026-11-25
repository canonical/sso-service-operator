# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The interface library this repository owns: sso_service_info."""

import ops
from ops import testing
from sso_service_info import SSOServiceInfoProvider, SSOServiceInfoRequirer

PROVIDER_META = {
    "name": "sso-service",
    "provides": {"sso-service-info": {"interface": "sso_service_info"}},
}
REQUIRER_META = {
    "name": "login-ui",
    "requires": {"sso-service-info": {"interface": "sso_service_info"}},
}
SEEN: list[str | None] = []


class ProviderCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self.info = SSOServiceInfoProvider(self)
        framework.observe(self.on.config_changed, self._publish)

    def _publish(self, _: ops.EventBase) -> None:
        self.info.update_relations_app_data(grpc_url="sso-service.m.svc:50051")


class RequirerCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self.info = SSOServiceInfoRequirer(self)
        framework.observe(self.info.on.sso_service_info_changed, self._read)

    def _read(self, _: ops.EventBase) -> None:
        SEEN.append(self.info.get_grpc_url())


class TestSSOServiceInfo:
    def test_provider_publishes_on_the_leader(self) -> None:
        relation = testing.Relation("sso-service-info")
        context = testing.Context(ProviderCharm, meta=PROVIDER_META)

        state_out = context.run(
            context.on.config_changed(), testing.State(leader=True, relations=[relation])
        )

        assert state_out.get_relation(relation.id).local_app_data == {
            "grpc_url": "sso-service.m.svc:50051"
        }

    def test_provider_follower_publishes_nothing(self) -> None:
        relation = testing.Relation("sso-service-info")
        context = testing.Context(ProviderCharm, meta=PROVIDER_META)

        state_out = context.run(
            context.on.config_changed(), testing.State(leader=False, relations=[relation])
        )

        assert not state_out.get_relation(relation.id).local_app_data

    def test_requirer_reads(self) -> None:
        relation = testing.Relation(
            "sso-service-info", remote_app_data={"grpc_url": "sso-service.m.svc:50051"}
        )
        context = testing.Context(RequirerCharm, meta=REQUIRER_META)

        context.run(context.on.relation_changed(relation), testing.State(relations=[relation]))

        assert SEEN == ["sso-service.m.svc:50051"]
