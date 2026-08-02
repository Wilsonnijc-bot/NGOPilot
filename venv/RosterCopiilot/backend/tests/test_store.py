from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.domain import AuditDecision, AuditKind, AuditStatus
from app.services import state as state_module
from app.services.state import AppState


def test_state_persists_versions_and_audit_decisions_after_restart(tmp_path):
    db_path = tmp_path / "roster.db"
    state = AppState(db_path=db_path)
    version, _ = state.apply(state.example_events())
    item = next(a for a in version.audit_items
                if a.kind == AuditKind.REPLACEMENT_SUGGESTION
                and a.status == AuditStatus.PENDING)
    state.decide(item.id, AuditDecision(status=AuditStatus.APPROVED))

    restarted = AppState(db_path=db_path, load_existing=True)

    assert restarted.current_id == state.current_id
    assert len(restarted.versions) == len(state.versions)
    decided = next(a for a in restarted.current.audit_items if a.id == item.id)
    assert decided.status == AuditStatus.APPROVED


def test_store_persists_import_batches_and_alias_resolutions(tmp_path):
    from app.store import RosterStore

    store = RosterStore(tmp_path / "roster.db")
    batch = store.create_import_batch(
        summary={"parsed_count": 1, "silently_dropped_cells": 0},
        payload={"records": [1]},
        source_names=["sample.xlsx"],
        ambiguities=[{"code": "X", "message": "needs review", "severity": "warning"}],
    )
    ambiguity = store.list_import_ambiguities(batch_id=batch["id"])[0]
    store.resolve_import_ambiguity(
        ambiguity["id"], status="resolved", resolution={"answer": "ok"})
    alias = store.save_alias_resolution(
        entity_type="worker", alias="娥", canonical_id="W001")

    restarted = RosterStore(tmp_path / "roster.db")
    assert restarted.get_import_batch(batch["id"])["payload"]["records"] == [1]
    assert restarted.list_import_ambiguities(status="resolved")[0]["resolution"]["answer"] == "ok"
    assert restarted.list_alias_resolutions()[0]["id"] == alias["id"]


def test_global_state_initializes_once_under_concurrent_api_load(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTER_DB_PATH", str(tmp_path / "concurrent.db"))
    with state_module._STATE_LOCK:
        state_module._STATE = None

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(lambda _: state_module.get_state(), range(16)))

    assert len({id(state) for state in states}) == 1
    assert states[0].current_id
