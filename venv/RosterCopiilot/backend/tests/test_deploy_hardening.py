"""Regression tests for pre-deployment security and hardening changes.

Covers: Excel formula-injection guard, environment-driven CORS/docs gating,
the optional API-token middleware, the upload size cap, and the SQLite
durability PRAGMAs.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.domain.enums import Period, ServiceCode
from app.domain.schedule import ScheduleEntry
from app.exporter.division_writer import (
    _export_unassigned_row,
    _formula_safe,
    _write_rows,
    render_export_placement_values,
)
from app.services import state as state_module
from app.store import RosterStore

import app.main as main_module
from app.main import app


# --------------------------------------------------------------- formula guard
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+1+1", "'+1+1"),
        ("-2", "'-2"),
        ("@cmd", "'@cmd"),
        ("\tTAB", "'\tTAB"),
        ("\rCR", "'\rCR"),
        ("D(李婆婆)", "D(李婆婆)"),
        ("Esc:王伯伯", "Esc:王伯伯"),
        ("", ""),
        ("09:00-17:00 港島", "09:00-17:00 港島"),
    ],
)
def test_formula_safe_neutralises_trigger_prefixes(raw, expected):
    assert _formula_safe(raw) == expected


def test_render_placement_values_guard_workbook_derived_detail():
    entry = ScheduleEntry(
        id="e1",
        schedule_date=date(2026, 1, 5),
        weekday=1,
        period=Period.AM,
        service_code=ServiceCode.ESCORT,
        notes="=HYPERLINK(\"http://evil\",\"x\")",
    )
    assignment, detail = render_export_placement_values(entry)
    # The assignment cell is always code-prefixed; the detail cell carries the
    # free text and must be neutralised.
    assert not assignment.startswith(("=", "+", "-", "@"))
    assert detail.startswith("'=HYPERLINK")


def test_unassigned_row_guards_free_text():
    entry = ScheduleEntry(
        id="e2",
        schedule_date=date(2026, 1, 5),
        weekday=1,
        period=Period.PM,
        service_code=ServiceCode.ESCORT,
        elder_name="=cmd|' /C calc'!A1",
    )
    row = _export_unassigned_row(entry, "=EVIL()")
    assert row[4].startswith("'=cmd")
    assert row[5].startswith("'=EVIL")


def test_rc_sheet_writer_guards_all_workbook_derived_text():
    workbook = Workbook()
    sheet = workbook.active
    _write_rows(
        sheet,
        ["label", "value"],
        [["source summary", "=HYPERLINK(\"http://evil\",\"x\")"]],
    )
    assert sheet.cell(2, 2).value.startswith("'=HYPERLINK")


# --------------------------------------------------------------- CORS / docs
def test_cors_origins_default_and_env(monkeypatch):
    monkeypatch.delenv("ROSTER_CORS_ORIGINS", raising=False)
    assert "http://localhost:3000" in main_module._cors_origins()
    # Explicit empty value == same-origin only (no cross-origin allowed).
    monkeypatch.setenv("ROSTER_CORS_ORIGINS", "")
    assert main_module._cors_origins() == []
    monkeypatch.setenv("ROSTER_CORS_ORIGINS", "https://a.example, https://b.example")
    assert main_module._cors_origins() == ["https://a.example", "https://b.example"]


def test_docs_disabled_in_production(monkeypatch):
    monkeypatch.delenv("ROSTER_ENABLE_DOCS", raising=False)
    monkeypatch.setenv("ROSTER_ENV", "production")
    assert main_module._docs_enabled() is False
    monkeypatch.setenv("ROSTER_ENABLE_DOCS", "1")
    assert main_module._docs_enabled() is True
    monkeypatch.delenv("ROSTER_ENABLE_DOCS", raising=False)
    monkeypatch.setenv("ROSTER_ENV", "development")
    assert main_module._docs_enabled() is True


# --------------------------------------------------------------- API token gate
@pytest.fixture()
def client():
    state_module.reset_state()
    return TestClient(app)


def test_api_open_when_token_unset(client, monkeypatch):
    monkeypatch.delenv("ROSTER_API_TOKEN", raising=False)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/schedule/mock-data").status_code == 200


def test_api_token_gate_blocks_and_allows(client, monkeypatch):
    monkeypatch.setenv("ROSTER_API_TOKEN", "s3cret-token")
    # Health stays public for proxy/uptime checks.
    assert client.get("/api/health").status_code == 200
    # Protected route rejected without a token.
    assert client.get("/api/schedule/mock-data").status_code == 401
    # Accepted with a correct bearer token...
    ok = client.get(
        "/api/schedule/mock-data",
        headers={"Authorization": "Bearer s3cret-token"},
    )
    assert ok.status_code == 200
    # ...or the X-API-Key header.
    assert client.get(
        "/api/schedule/mock-data", headers={"X-API-Key": "s3cret-token"}
    ).status_code == 200
    # Wrong token rejected.
    assert client.get(
        "/api/schedule/mock-data", headers={"Authorization": "Bearer nope"}
    ).status_code == 401


# --------------------------------------------------------------- upload cap
def test_weekly_roster_upload_size_cap(client, monkeypatch):
    monkeypatch.delenv("ROSTER_API_TOKEN", raising=False)
    # ~1 byte cap: any non-empty workbook part exceeds it.
    monkeypatch.setenv("ROSTER_MAX_UPLOAD_MB", "0.000001")
    files = {
        "hc_workbook": ("hc.xlsx", b"PK\x03\x04 padded body", "application/octet-stream"),
        "escort_workbook": ("escort.xlsx", b"PK\x03\x04 padded body", "application/octet-stream"),
    }
    resp = client.post(
        "/api/demo/weekly-roster",
        files=files,
        data={"week_start": "2026-01-05", "changes_json": "[]"},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"


# --------------------------------------------------------------- sqlite pragmas
def test_store_enables_wal_and_busy_timeout(tmp_path):
    store = RosterStore(db_path=tmp_path / "pragma.db")
    with store.engine.connect() as conn:
        journal = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    assert str(journal).lower() == "wal"
    assert int(busy) == 30000


# ---------------------------------------------------------- deployment assets
def test_nginx_tls_bootstrap_precedes_final_https_site():
    repo_root = Path(__file__).resolve().parents[2]
    bootstrap = (repo_root / "deploy/ubuntu/nginx-bootstrap.conf").read_text()
    final = (repo_root / "deploy/ubuntu/nginx.conf").read_text()
    runbook = (repo_root / "deploy/ubuntu/README.md").read_text()

    assert "listen 80" in bootstrap
    assert "ssl_certificate" not in bootstrap
    assert "return 503" in bootstrap
    assert "ssl_certificate" in final
    assert runbook.index("certbot certonly") < runbook.index(
        "sites-available/rostercopiilot /etc/nginx/sites-enabled/rostercopiilot"
    )
