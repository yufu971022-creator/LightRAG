from __future__ import annotations

from lightrag_ext.us_dsl.lifecycle_storage_adapter import LocalLifecycleStorageAdapter
from lightrag_ext.us_dsl.lifecycle_storage_capability import LifecycleStorageCapabilityProbe


class MissingNodeDeleteAdapter(LocalLifecycleStorageAdapter):
    def delete_pfss_node(self, node_id: str):
        raise RuntimeError("delete node unsupported")


def test_storage_capability_probe_runs_once():
    probe = LifecycleStorageCapabilityProbe(LocalLifecycleStorageAdapter())
    first = probe.run()
    second = probe.run()
    assert probe.run_count == 1
    assert first == second


def test_direct_file_edit_is_not_used():
    capabilities = LifecycleStorageCapabilityProbe(LocalLifecycleStorageAdapter()).run()
    assert capabilities.direct_storage_file_edit_used is False


def test_missing_safe_delete_capability_blocks_execution():
    capabilities = LifecycleStorageCapabilityProbe(MissingNodeDeleteAdapter()).run()
    assert capabilities.blocked_by_core_gap is True
    assert capabilities.supports_safe_document_delete is False
