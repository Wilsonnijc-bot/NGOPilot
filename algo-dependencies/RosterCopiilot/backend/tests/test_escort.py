"""Escort-specific behaviour: assignment quality, preferences, quotas."""
from app.domain import EntryStatus, ReviewReasonCode, ServiceCode

ACTIVE = {EntryStatus.SCHEDULED, EntryStatus.NEEDS_REVIEW}


def test_escorts_occupy_whole_period(dataset, baseline):
    escort_workers = {(e.worker_id, e.schedule_date, e.period)
                      for e in baseline.entries
                      if e.service_code == ServiceCode.ESCORT
                      and e.status in ACTIVE and e.worker_id}
    for e in baseline.entries:
        if e.service_code == ServiceCode.ESCORT:
            continue
        if e.status in ACTIVE and e.worker_id:
            assert (e.worker_id, e.schedule_date, e.period) not in escort_workers, \
                f"{e.id}: worker double-used during an escort half-day"


def test_escort_workers_are_escort_skilled(dataset, baseline):
    workers = dataset.employee_map()
    for e in baseline.entries:
        if e.service_code == ServiceCode.ESCORT and e.status in ACTIVE and e.worker_id:
            assert ServiceCode.ESCORT in workers[e.worker_id].skills


def test_must_preference_blocks_rather_than_substitutes(dataset, baseline):
    """The '只要娥姐' escort: W001 is busy, so the request must surface as
    unassigned + review, never be given to someone else (RB-EXCL-03)."""
    must = [r for r in dataset.escort_requests if r.preference_strength == "must"]
    assert must
    for req in must:
        entries = [e for e in baseline.entries
                   if e.origin_escort_request_id == req.id]
        assert entries
        for e in entries:
            if e.status in ACTIVE:
                assert e.worker_id == req.preferred_worker_id
            else:
                assert e.status == EntryStatus.UNASSIGNED
                assert any(r.code == ReviewReasonCode.PREFERENCE_UNMET
                           for r in e.review_reasons)


def test_escort_fulfillment_counts_only_real_demand(dataset, baseline):
    m = baseline.summary
    assert 0.9 <= m["escort_fulfillment_rate"] <= 1.0
    # exactly the two designed-unassignable escorts are open
    assert m["unassigned_escort"] == 2
