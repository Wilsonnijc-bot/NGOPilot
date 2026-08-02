"""User-facing weekly roster demo API.

Primary demo flow:
1. built-in division workbook supplies fixed base + output template;
2. user uploads HC timetable and escort workbook;
3. user adds temporary changes;
4. system drafts a weekly roster and exports the NGO-format workbook.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import unicodedata
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from ..domain import (
    AuditItem,
    HardViolation,
    ImpactReport,
    ManualOverride,
    MasterDataSet,
    PublicationRecord,
    ReviewDecisionRecord,
    ScheduleEntry,
    ScheduleVersion,
    VersionKind,
    WeeklyRunRecord,
    canonical_json,
    stable_id,
    validate_master_data,
)
from ..exporter import (
    ExportPreflightError,
    GeneratedDivisionExportReport,
    prepare_generated_division_roster_export,
    save_generated_division_roster_workbook,
)
from ..exporter.division_writer import (
    CellMarker,
    GeneratedDivisionExportPlan,
    PlacementTarget,
    validate_prepared_division_export_plan,
)
from ..importer import DivisionImportResult, parse_division_workbook
from ..importer.base import ImportResult
from ..importer.errors import ImporterError
from ..importer.models import ImportAmbiguity, ImportBatchSummary
from ..scheduler import (
    GeneratedDemands,
    SchedulerResult,
    finalize_version_provenance,
    run_scheduler,
    version_content_hash,
)
from ..services.state import get_state
from ..services.master_data_bridge import bootstrap_master_data_from_division
from ..services.weekly_demo import (
    DEFAULT_DIVISION_TEMPLATE,
    WeeklyRosterDemoBuild,
    WeeklyRosterDemoBuilder,
)
from ..services.weekly_review import (
    WeeklyRevalidateCommand,
    WeeklyReviewCommand,
    WeeklyReviewError,
    apply_weekly_review,
    idempotent_decision_matches,
    validate_current_version,
)
from ..services.weekly_publication import (
    WeeklyPublicationCommand,
    publish_weekly_run,
    remove_uncommitted_publication,
    weekly_publication_lock,
)
from ..store import RosterStore, WeeklyRunStoreError

router = APIRouter(prefix="/api/demo", tags=["demo"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ALLOWED_WORKBOOK_SUFFIXES = {".xlsx", ".xlsm"}
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAX_UPLOAD_MB = 10.0


def _max_upload_bytes() -> int:
    """Resolve the per-workbook upload cap (bytes) from the environment."""

    raw = os.getenv("ROSTER_MAX_UPLOAD_MB")
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except (TypeError, ValueError):
        megabytes = DEFAULT_MAX_UPLOAD_MB
    if megabytes <= 0:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return int(megabytes * 1024 * 1024)


@dataclass
class DemoRun:
    run_id: str
    build: WeeklyRosterDemoBuild
    result: SchedulerResult
    review_version: ScheduleVersion
    export_report: GeneratedDivisionExportReport
    export_plan: GeneratedDivisionExportPlan
    upload_names: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    master_data_version: int | str | None = None
    decisions: list[ReviewDecisionRecord] = field(default_factory=list)
    manual_overrides: list[ManualOverride] = field(default_factory=list)
    publications: list[PublicationRecord] = field(default_factory=list)


class WeeklyWorkspaceSaveRequest(BaseModel):
    run_id: str


class WeeklyRunArchiveCreateRequest(BaseModel):
    run_id: str
    title: str | None = None


async def _save_upload(upload: UploadFile, path: Path) -> Path:
    suffix = Path(upload.filename or path.name).suffix or ".xlsx"
    if suffix.lower() not in ALLOWED_WORKBOOK_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_WORKBOOK_TYPE",
                "message": f"不支援此工作簿格式：{suffix}",
                "allowed_extensions": sorted(ALLOWED_WORKBOOK_SUFFIXES),
            },
        )
    max_bytes = _max_upload_bytes()
    target = path.with_suffix(suffix)
    total = 0
    # Stream to disk with a hard size cap instead of reading the whole body
    # into memory; a bounded compressed size also limits ZIP/XLSX-bomb blast
    # radius before openpyxl parses the workbook.
    with target.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "UPLOAD_TOO_LARGE",
                        "message": (
                            "上載的工作簿超過大小上限"
                            f"（{max_bytes // (1024 * 1024)}MB）。"
                        ),
                        "max_bytes": max_bytes,
                    },
                )
            handle.write(chunk)
    if total == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMPTY_UPLOAD",
                "message": f"上載的工作簿沒有內容：{upload.filename}",
            },
        )
    return target


@router.post("/weekly-roster")
async def build_weekly_roster(
    hc_workbook: UploadFile = File(...),
    escort_workbook: UploadFile = File(...),
    week_start: date = Form(...),
    changes_json: str = Form("[]"),
) -> dict[str, Any]:
    """Build a weekly roster from uploaded HC/escort workbooks."""

    with TemporaryDirectory(prefix="rostercopiilot_demo_") as tmp:
        tmpdir = Path(tmp)
        hc_path = await _save_upload(hc_workbook, tmpdir / "hc.xlsx")
        escort_path = await _save_upload(escort_workbook, tmpdir / "escort.xlsx")
        builder = WeeklyRosterDemoBuilder(
            division_template_path=DEFAULT_DIVISION_TEMPLATE,
            master_data_provider=_get_or_bootstrap_master_data,
        )
        try:
            build = builder.build(
                hc_workbook_path=hc_path,
                escort_workbook_path=escort_path,
                week_start=week_start,
                changes_json=changes_json,
            )
            result = run_scheduler(build.snapshot)
            export_plan = prepare_generated_division_roster_export(
                division_layout=build.division,
                dataset=result.dataset,
                version=result.version,
                generated=result.generated,
            )
        except ImporterError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": exc.__class__.__name__,
                    "message": "無法讀取上載的工作簿，請檢查檔案格式及內容。",
                    "source": str(getattr(exc, "source", "")),
                },
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DEMO_BUILD_FAILED",
                    "message": "無法生成排班，請檢查目標週、臨時變更及工作簿內容。",
                },
            ) from exc

    run_id = uuid4().hex[:12]
    demo_run = DemoRun(
        run_id=run_id,
        build=build,
        result=result,
        review_version=export_plan.review_version,
        export_report=export_plan.report,
        export_plan=export_plan,
        upload_names={
            "hc_workbook": _safe_upload_display_name(
                hc_workbook.filename, "HC workbook"
            ),
            "escort_workbook": _safe_upload_display_name(
                escort_workbook.filename, "escort workbook"
            ),
        },
        master_data_version=_current_master_data_version(),
    )
    try:
        payload = _response_payload(demo_run)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PROVENANCE_REGISTRY_INCOMPLETE",
                "message": "排班資料的來源記錄不完整，為保障資料安全已停止生成。",
            },
        ) from exc
    try:
        _persist_demo_run(demo_run)
        _weekly_run_store().save_weekly_workspace(run_id)
    except (ValueError, WeeklyRunStoreError) as exc:
        detail = (
            exc.as_detail()
            if isinstance(exc, WeeklyRunStoreError)
            else {
                "code": "WEEKLY_RUN_PERSIST_FAILED",
                "message": "排班工作未能保存，請稍後再試。",
                "run_id": run_id,
            }
        )
        raise HTTPException(status_code=500, detail=detail) from exc
    return jsonable_encoder(payload)


@router.get("/workspace")
def get_weekly_workspace() -> dict[str, Any]:
    """Return the weekly run that the browser should restore on refresh."""

    workspace = _weekly_run_store().get_weekly_workspace()
    return jsonable_encoder(workspace or {
        "current_run_id": None,
        "saved_at": None,
    })


@router.put("/workspace")
def save_weekly_workspace(
    request: WeeklyWorkspaceSaveRequest,
) -> dict[str, Any]:
    """Save the active weekly run pointer without changing its schedule."""

    try:
        return jsonable_encoder(
            _weekly_run_store().save_weekly_workspace(request.run_id)
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "WEEKLY_RUN_NOT_FOUND",
                "message": f"找不到排班工作：{request.run_id}",
                "run_id": request.run_id,
            },
        ) from exc


@router.get("/archives")
def list_weekly_run_archives() -> dict[str, Any]:
    """List all immutable weekly-run snapshots in one archive module."""

    archives = _weekly_run_store().list_weekly_run_archives()
    return jsonable_encoder({"archives": archives})


@router.post("/archives")
def create_weekly_run_archive(
    request: WeeklyRunArchiveCreateRequest,
) -> dict[str, Any]:
    """Freeze the exact current version of a durable weekly run."""

    run = _load_demo_run_for_api(request.run_id)
    payload = jsonable_encoder(_response_payload(run))
    title = (request.title or "").strip() or f"週排班 {payload['week_start']}"
    try:
        archive = _weekly_run_store().create_weekly_run_archive(
            run_id=request.run_id,
            title=title,
            week_start=payload["week_start"],
            source_version_id=payload["version"]["id"],
            content_hash=payload["reconciliation"]["content_hash"],
            snapshot=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ARCHIVE_INVALID",
                "message": "存檔名稱無效；名稱不可留空或超過 120 個字元。",
                "run_id": request.run_id,
            },
        ) from exc
    return jsonable_encoder(archive)


@router.get("/archives/{archive_id}")
def get_weekly_run_archive(archive_id: str) -> dict[str, Any]:
    """Return one frozen archive; it is never reconstituted from a live run."""

    archive = _weekly_run_store().get_weekly_run_archive(archive_id)
    if archive is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ARCHIVE_NOT_FOUND",
                "message": f"找不到固態存檔：{archive_id}",
                "archive_id": archive_id,
            },
        )
    return jsonable_encoder(archive)


@router.post("/archives/{archive_id}/editable-copy")
def create_editable_copy_from_archive(archive_id: str) -> dict[str, Any]:
    """Fork one frozen archive into a new independently editable weekly run."""

    archive_payload = _weekly_run_store().get_weekly_run_archive(archive_id)
    if archive_payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ARCHIVE_NOT_FOUND",
                "message": f"找不到固態存檔：{archive_id}",
                "archive_id": archive_id,
            },
        )
    try:
        record = _editable_copy_record(archive_payload)
        stored = _weekly_run_store().create_weekly_run(record)
        workspace = _weekly_run_store().save_weekly_workspace(stored.run_id)
        payload = _response_payload(_reconstitute_demo_run(stored))
    except WeeklyRunStoreError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ARCHIVE_EDITABLE_COPY_FAILED",
                "message": "存檔內容與原始排班版本不一致，無法安全建立可編輯副本。",
                "archive_id": archive_id,
            },
        ) from exc
    payload["editable_copy"] = {
        "archive_id": archive_id,
        "source_run_id": archive_payload["archive"]["run_id"],
        "source_version_id": archive_payload["archive"]["source_version_id"],
        "created_run_id": stored.run_id,
        "workspace_saved_at": workspace["saved_at"],
    }
    return jsonable_encoder(payload)


@router.get("/weekly-roster/{run_id}")
def get_weekly_roster(run_id: str) -> dict[str, Any]:
    """Return the durable current weekly version and its canonical report."""

    return jsonable_encoder(_response_payload(_load_demo_run_for_api(run_id)))


@router.post("/weekly-roster/{run_id}/review-decisions")
def decide_weekly_roster_audit(
    run_id: str,
    command: WeeklyReviewCommand,
) -> dict[str, Any]:
    """Apply one atomic approve/reject/edit transition to a durable run."""

    record = _load_weekly_record_for_api(run_id)
    prior = next(
        (
            item for item in record.decisions
            if item.idempotency_key == command.idempotency_key
        ),
        None,
    )
    if prior is not None:
        if not idempotent_decision_matches(prior, command):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "IDEMPOTENCY_KEY_REUSED",
                    "message": "此審核操作識別碼已用於另一個審核請求，請重新載入後再試。",
                    "decision_id": prior.decision_id,
                },
            )
        payload = _response_payload(_reconstitute_demo_run(record))
        payload["decision"] = prior
        payload["idempotent_replay"] = True
        return jsonable_encoder(payload)

    try:
        # The store already validated the immutable current version and cached
        # plan.  The child produced below receives a fresh full preflight, so
        # rebuilding the unchanged parent plan here would duplicate the same
        # safety work on every review action.
        restored = _reconstitute_demo_run(record, rebuild_preflight=False)
        outcome = apply_weekly_review(record, restored.build.division, command)
        stored = _weekly_run_store().save_weekly_run_decision(
            outcome.decision,
            result_version=outcome.version,
            latest_export_report=outcome.report.model_dump(mode="json"),
            latest_export_plan=_serialize_export_plan(outcome.plan),
            manual_override=outcome.manual_override,
        )
    except WeeklyReviewError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except WeeklyRunStoreError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVIEW_PERSISTENCE_CONFLICT",
                "message": "審核結果保存時發生衝突，請重新載入最新排班後再試。",
                "run_id": run_id,
            },
        ) from exc

    if stored.content_hash != outcome.decision.content_hash:
        # A concurrent request with the same idempotency key committed first;
        # the store resolved it as that request's decision. Serve the durable
        # winner instead of this request's uncommitted computation.
        fresh = _load_weekly_record_for_api(run_id)
        payload = _response_payload(_reconstitute_demo_run(fresh))
        payload["decision"] = stored
        payload["idempotent_replay"] = True
        return jsonable_encoder(payload)

    response_run = replace(
        restored,
        review_version=outcome.version,
        export_report=outcome.report,
        export_plan=outcome.plan,
        decisions=[*record.decisions, stored],
        manual_overrides=[
            *record.manual_overrides,
            *([outcome.manual_override] if outcome.manual_override else []),
        ],
    )
    payload = _response_payload(response_run)
    payload["decision"] = stored
    payload["idempotent_replay"] = False
    return jsonable_encoder(payload)


@router.post("/weekly-roster/{run_id}/revalidate")
def revalidate_weekly_roster(
    run_id: str,
    command: WeeklyRevalidateCommand,
) -> dict[str, Any]:
    """Re-run canonical preflight without manufacturing an unchanged child."""

    record = _load_weekly_record_for_api(run_id)
    try:
        validate_current_version(
            record,
            source_version_id=command.source_version_id,
            content_hash=command.content_hash,
        )
        # Restoration rebuilds finalize/reconciliation, independent validator,
        # and the exact export plan, then compares all artifacts with storage.
        run = _reconstitute_demo_run(record)
    except WeeklyReviewError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except WeeklyRunStoreError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REVALIDATION_FAILED",
                "message": "重新驗證失敗，請重新載入目前排班後再試。",
                "run_id": run_id,
            },
        ) from exc
    payload = _response_payload(run)
    payload["revalidated"] = True
    payload["version_unchanged"] = True
    return jsonable_encoder(payload)


@router.post("/weekly-roster/{run_id}/publish")
def publish_weekly_roster(
    run_id: str,
    command: WeeklyPublicationCommand,
) -> dict[str, Any]:
    """Publish one exact ready version as an immutable staff final workbook."""

    output_dir = _export_output_dir()
    try:
        with weekly_publication_lock(
            output_dir=output_dir,
            run_id=run_id,
            source_version_id=command.source_version_id,
            content_hash=command.content_hash,
        ):
            # Loading inside the publication lock makes an exact retry observe
            # the record committed by the preceding request before any write.
            record = _load_weekly_record_for_api(run_id)
            run = _reconstitute_demo_run(record)
            outcome = publish_weekly_run(
                record,
                division_layout=run.build.division,
                command=command,
                output_dir=output_dir,
                template_path=DEFAULT_DIVISION_TEMPLATE,
                source_summary=_source_summary(run),
            )
            try:
                stored = _weekly_run_store().save_weekly_run_publication(
                    outcome.publication
                )
            except (ValueError, KeyError, WeeklyRunStoreError):
                remove_uncommitted_publication(outcome)
                raise
    except WeeklyReviewError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLICATION_PREFLIGHT_FAILED",
                "message": "正式版匯出前檢查失敗，請重新載入並確認所有審核項目。",
                "run_id": run_id,
            },
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PUBLICATION_ARTIFACT_WRITE_FAILED",
                "message": "正式版檔案未能安全寫入，沒有建立發佈記錄。",
                "run_id": run_id,
            },
        ) from exc

    payload = _response_payload(_load_demo_run_for_api(run_id))
    payload["publication"] = _public_publication(stored)
    payload["idempotent_replay"] = not outcome.artifact_written
    payload["final_export_url"] = (
        f"/api/demo/weekly-roster/{run_id}/published/{stored.publication_id}"
    )
    return jsonable_encoder(payload)


@router.get("/weekly-roster/{run_id}/published/{publication_id}")
def download_published_weekly_roster(
    run_id: str,
    publication_id: str,
) -> FileResponse:
    """Download a previously verified immutable staff final workbook."""

    record = _load_weekly_record_for_api(run_id)
    publication = next(
        (
            item for item in record.publications
            if item.publication_id == publication_id
        ),
        None,
    )
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "PUBLICATION_NOT_FOUND",
                "message": "找不到已發佈的正式版工作簿",
                "run_id": run_id,
                "publication_id": publication_id,
            },
        )
    return FileResponse(
        publication.artifact_path,
        media_type=XLSX_MEDIA,
        filename=publication.filename,
    )


@router.get("/weekly-roster/{run_id}/export")
def export_weekly_roster(run_id: str) -> FileResponse:
    run = _load_demo_run_for_api(run_id)
    output_dir = _export_output_dir()
    try:
        path = save_generated_division_roster_workbook(
            template_path=DEFAULT_DIVISION_TEMPLATE,
            division_layout=run.build.division,
            dataset=run.result.dataset,
            version=run.review_version,
            generated=run.result.generated,
            prepared_plan=run.export_plan,
            output_dir=output_dir,
            source_summary=_source_summary(run),
        )
    except ExportPreflightError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPORT_PREFLIGHT_FAILED",
                "message": "審核草稿未通過匯出前檢查，已停止寫入主表。",
                "report": jsonable_encoder(exc.report),
            },
        ) from exc
    return FileResponse(
        path,
        media_type=XLSX_MEDIA,
        filename="照顧員工作分工表_審核草稿.xlsx",
    )


def _persist_demo_run(run: DemoRun) -> WeeklyRunRecord:
    return _weekly_run_store().create_weekly_run(_weekly_run_record(run))


def _weekly_run_record(run: DemoRun) -> WeeklyRunRecord:
    versions = [run.review_version]
    if run.result.baseline.id != run.review_version.id:
        versions.insert(0, run.result.baseline)
    return WeeklyRunRecord(
        run_id=run.run_id,
        week_start=run.build.snapshot.week_start,
        created_at=run.created_at,
        current_version_id=run.review_version.id,
        master_data_version=run.master_data_version,
        snapshot=run.build.snapshot,
        dataset=run.result.dataset,
        generated_payload=run.result.generated.model_dump(mode="json"),
        scheduler_result_payload={
            "baseline": run.result.baseline.model_dump(mode="json"),
            "version": run.result.version.model_dump(mode="json"),
            "reports": [item.model_dump(mode="json") for item in run.result.reports],
            "data_gap_audits": [
                item.model_dump(mode="json") for item in run.result.data_gap_audits
            ],
            "violations": [
                item.model_dump(mode="json") for item in run.result.violations
            ],
        },
        run_context={
            "upload_names": run.upload_names,
            "source_counts": run.build.source_counts,
            "warnings": run.build.warnings,
            "change_summaries": run.build.change_summaries,
            "hc_summary": asdict(run.build.hc.summary),
            "escort_summary": asdict(run.build.escort.summary),
            "hc_ambiguity_count": len(run.build.hc.ambiguities),
            "escort_ambiguity_count": len(run.build.escort.ambiguities),
        },
        versions=versions,
        decisions=list(run.decisions),
        manual_overrides=list(run.manual_overrides),
        publications=list(run.publications),
        latest_export_report=run.export_report.model_dump(mode="json"),
        latest_export_plan=_serialize_export_plan(run.export_plan),
        latest_content_hash=version_content_hash(run.review_version),
    )


def _editable_copy_record(archive_payload: dict[str, Any]) -> WeeklyRunRecord:
    """Flatten an archived version into a new run while retaining its origin."""

    archive = archive_payload["archive"]
    snapshot_payload = archive_payload["snapshot"]
    source_record = _load_weekly_record_for_api(archive["run_id"])
    source_version = next(
        (
            version for version in source_record.versions
            if version.id == archive["source_version_id"]
        ),
        None,
    )
    if source_version is None:
        raise ValueError("archive source version is missing")
    snapshot_version = ScheduleVersion.model_validate(snapshot_payload["version"])
    if (
        canonical_json(snapshot_version.model_dump(mode="json"))
        != canonical_json(source_version.model_dump(mode="json"))
        or version_content_hash(source_version) != archive["content_hash"]
        or snapshot_payload.get("reconciliation", {}).get("content_hash")
        != archive["content_hash"]
    ):
        raise ValueError("archive snapshot does not match its immutable source version")

    new_run_id = uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    copied_version = source_version.model_copy(deep=True, update={
        "id": stable_id("ver_", "weekly_archive_editable_copy", {
            "archive_id": archive["archive_id"],
            "new_run_id": new_run_id,
            "source_version_id": source_version.id,
        }),
        "kind": VersionKind.BASELINE,
        "parent_version_id": None,
        "created_at": now,
        "reconciliation": None,
    })
    reports = [
        ImpactReport.model_validate(item)
        for item in snapshot_payload.get("impact_reports", [])
    ]
    generated = GeneratedDemands.model_validate(source_record.generated_payload)
    finalize_version_provenance(copied_version, generated, reports=reports)
    division = parse_division_workbook(DEFAULT_DIVISION_TEMPLATE)
    plan = prepare_generated_division_roster_export(
        division_layout=division,
        dataset=source_record.dataset,
        version=copied_version,
        generated=generated,
    )
    copied_version = plan.review_version
    context = dict(source_record.run_context)
    context["fork_origin"] = {
        "kind": "archive_editable_copy",
        "archive_id": archive["archive_id"],
        "source_run_id": archive["run_id"],
        "source_version_id": archive["source_version_id"],
        "source_content_hash": archive["content_hash"],
        "copied_at": now.isoformat(),
    }
    return WeeklyRunRecord(
        run_id=new_run_id,
        week_start=source_record.week_start,
        created_at=now,
        current_version_id=copied_version.id,
        master_data_version=source_record.master_data_version,
        snapshot=source_record.snapshot,
        dataset=source_record.dataset,
        generated_payload=source_record.generated_payload,
        scheduler_result_payload={
            "baseline": copied_version.model_dump(mode="json"),
            "version": copied_version.model_dump(mode="json"),
            "reports": [item.model_dump(mode="json") for item in reports],
            "data_gap_audits": [],
            "violations": [
                item.model_dump(mode="json")
                for item in plan.report.validator_violations
            ],
        },
        run_context=context,
        versions=[copied_version],
        decisions=[],
        manual_overrides=[],
        publications=[],
        latest_export_report=plan.report.model_dump(mode="json"),
        latest_export_plan=_serialize_export_plan(plan),
        latest_content_hash=version_content_hash(copied_version),
    )


def _load_demo_run_for_api(run_id: str) -> DemoRun:
    record = _load_weekly_record_for_api(run_id)
    try:
        return _reconstitute_demo_run(record)
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WEEKLY_RUN_DATA_CORRUPT",
                "message": "保存的排班資料不完整或已損壞，無法安全恢復。",
                "run_id": run_id,
            },
        ) from exc


def _load_weekly_record_for_api(run_id: str) -> WeeklyRunRecord:
    try:
        record = _weekly_run_store().get_weekly_run(run_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "WEEKLY_RUN_NOT_FOUND",
                    "message": "找不到指定的排班工作",
                    "run_id": run_id,
                },
            )
        return record
    except HTTPException:
        raise
    except WeeklyRunStoreError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WEEKLY_RUN_DATA_CORRUPT",
                "message": "保存的排班資料不完整或已損壞，無法安全恢復。",
                "run_id": run_id,
            },
        ) from exc


def _reconstitute_demo_run(
    record: WeeklyRunRecord,
    *,
    rebuild_preflight: bool = True,
) -> DemoRun:
    """Restore a run without rerunning generation or scheduling.

    The built-in division template is parsed again as the current layout
    authority.  By default, preflight is rebuilt from the persisted normalized
    dataset, generated demand, and immutable current version, then compared
    with the persisted report/plan cache.  Review transitions may skip only
    that redundant parent rebuild because they fully preflight the new child
    before any commit.
    """

    context = record.run_context
    division = parse_division_workbook(DEFAULT_DIVISION_TEMPLATE)
    hc = _restore_import_result(
        context.get("hc_summary"),
        ambiguity_count=context.get("hc_ambiguity_count", 0),
    )
    escort = _restore_import_result(
        context.get("escort_summary"),
        ambiguity_count=context.get("escort_ambiguity_count", 0),
    )
    build = WeeklyRosterDemoBuild(
        snapshot=record.snapshot,
        division=division,
        hc=hc,
        escort=escort,
        source_counts=dict(context.get("source_counts", {})),
        warnings=list(context.get("warnings", [])),
        change_summaries=list(context.get("change_summaries", [])),
    )
    generated = GeneratedDemands.model_validate(record.generated_payload)
    scheduler_payload = record.scheduler_result_payload
    result = SchedulerResult(
        snapshot=record.snapshot,
        generated=generated,
        dataset=record.dataset,
        baseline=ScheduleVersion.model_validate(scheduler_payload["baseline"]),
        version=ScheduleVersion.model_validate(scheduler_payload["version"]),
        reports=[ImpactReport.model_validate(item)
                 for item in scheduler_payload.get("reports", [])],
        data_gap_audits=[AuditItem.model_validate(item)
                         for item in scheduler_payload.get("data_gap_audits", [])],
        violations=[HardViolation.model_validate(item)
                    for item in scheduler_payload.get("violations", [])],
    )
    current = next(
        version for version in record.versions
        if version.id == record.current_version_id
    )
    if version_content_hash(current) != record.latest_content_hash:
        raise ValueError("restored current version content hash is invalid")

    cached_plan = _deserialize_export_plan(record.latest_export_plan)
    validate_prepared_division_export_plan(cached_plan, current)
    cached_report = GeneratedDivisionExportReport.model_validate(
        record.latest_export_report
    )
    if canonical_json(cached_report.model_dump(mode="json")) != canonical_json(
        cached_plan.report.model_dump(mode="json")
    ):
        raise ValueError("stored export report conflicts with stored plan")

    active_plan = cached_plan
    if rebuild_preflight:
        rebuilt_plan = prepare_generated_division_roster_export(
            division_layout=division,
            dataset=record.dataset,
            version=current,
            generated=generated,
        )
        validate_prepared_division_export_plan(
            rebuilt_plan,
            rebuilt_plan.review_version,
        )
        if _canonical_export_plan(rebuilt_plan) != _canonical_export_plan(cached_plan):
            raise ValueError("stored export plan does not match rebuilt preflight")
        if version_content_hash(rebuilt_plan.review_version) != record.latest_content_hash:
            raise ValueError("rebuilt preflight changed the stored current version")
        active_plan = rebuilt_plan

    upload_names = context.get("upload_names")
    if not isinstance(upload_names, dict):
        raise ValueError("stored upload display names are missing")
    safe_names = {
        "hc_workbook": _safe_upload_display_name(
            upload_names.get("hc_workbook"), "HC workbook"
        ),
        "escort_workbook": _safe_upload_display_name(
            upload_names.get("escort_workbook"), "escort workbook"
        ),
    }
    if safe_names != upload_names:
        raise ValueError("stored upload display names are unsafe")
    return DemoRun(
        run_id=record.run_id,
        build=build,
        result=result,
        review_version=active_plan.review_version,
        export_report=active_plan.report,
        export_plan=active_plan,
        upload_names=safe_names,
        created_at=record.created_at,
        master_data_version=record.master_data_version,
        decisions=list(record.decisions),
        manual_overrides=list(record.manual_overrides),
        publications=list(record.publications),
    )


def _serialize_export_plan(plan: GeneratedDivisionExportPlan) -> dict[str, Any]:
    return {
        "report": plan.report.model_dump(mode="json"),
        "review_version": plan.review_version.model_dump(mode="json"),
        "placements": [
            {
                "entry": target.entry.model_dump(mode="json"),
                "assignment_row": target.assignment_row,
                "detail_row": target.detail_row,
                "col": target.col,
                "session": target.session,
                "occupied_sessions": target.occupied_sessions,
                "assignment_ref": target.assignment_ref,
                "detail_ref": target.detail_ref,
                "audit_ids": target.audit_ids,
            }
            for target in plan.placements
        ],
        "changed_cells": {
            ref: {"note": marker.note, "marker_kind": marker.marker_kind}
            for ref, marker in sorted(plan.changed_cells.items())
        },
        "integrity_hash": plan.integrity_hash,
    }


def _deserialize_export_plan(payload: dict[str, Any]) -> GeneratedDivisionExportPlan:
    return GeneratedDivisionExportPlan(
        report=GeneratedDivisionExportReport.model_validate(payload["report"]),
        review_version=ScheduleVersion.model_validate(payload["review_version"]),
        placements=[
            PlacementTarget(
                entry=ScheduleEntry.model_validate(item["entry"]),
                assignment_row=int(item["assignment_row"]),
                detail_row=(int(item["detail_row"])
                            if item.get("detail_row") is not None else None),
                col=int(item["col"]),
                session=int(item["session"]),
                occupied_sessions=[int(value)
                                   for value in item.get("occupied_sessions", [])],
                assignment_ref=str(item["assignment_ref"]),
                detail_ref=(str(item["detail_ref"])
                            if item.get("detail_ref") is not None else None),
                audit_ids=[str(value) for value in item.get("audit_ids", [])],
            )
            for item in payload["placements"]
        ],
        changed_cells={
            str(ref): CellMarker(
                note=str(marker["note"]),
                marker_kind=marker.get("marker_kind", "changed"),
            )
            for ref, marker in payload["changed_cells"].items()
        },
        integrity_hash=str(payload["integrity_hash"]),
    )


def _canonical_export_plan(plan: GeneratedDivisionExportPlan) -> str:
    return canonical_json(_serialize_export_plan(plan))


def _restore_import_result(
    raw_summary: Any,
    *,
    ambiguity_count: Any,
) -> ImportResult[dict[str, Any]]:
    if not isinstance(raw_summary, dict):
        raise ValueError("stored parser summary is missing")
    summary = ImportBatchSummary(
        **{
            **raw_summary,
            "ignored_sheets": tuple(raw_summary.get("ignored_sheets", ())),
            "notes": tuple(raw_summary.get("notes", ())),
        }
    )
    count = int(ambiguity_count)
    if count < 0:
        raise ValueError("stored ambiguity count is invalid")
    ambiguities = tuple(
        ImportAmbiguity(
            code=f"PERSISTED_AMBIGUITY_{index}",
            message="Persisted parser ambiguity; details remain in normalized evidence.",
        )
        for index in range(1, count + 1)
    )
    return ImportResult(summary=summary, ambiguities=ambiguities)


def _weekly_run_store() -> RosterStore:
    store = get_state().store
    if store is None:
        raise ValueError("weekly run persistence is unavailable")
    return store


def _export_output_dir() -> Path:
    raw_dir = os.getenv("ROSTER_EXPORT_DIR")
    output_dir = Path(raw_dir) if raw_dir else REPO_ROOT / "data" / "exports"
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    return output_dir


def _current_master_data_version() -> int | str | None:
    current = _weekly_run_store().get_master_data()
    return current.get("version") if current is not None else None


def _safe_upload_display_name(value: Any, fallback: str) -> str:
    raw = str(value or fallback).replace("\\", "/")
    name = Path(raw).name
    name = unicodedata.normalize("NFC", name)
    name = "".join(character for character in name
                   if character >= " " and character != "\x7f").strip()
    if not name or name in {".", ".."}:
        name = fallback
    return name[:255]


def _response_payload(run: DemoRun) -> dict[str, Any]:
    try:
        validate_prepared_division_export_plan(
            run.export_plan,
            run.review_version,
        )
    except ValueError as exc:
        raise RuntimeError(f"weekly demo export plan is invalid: {exc}") from exc
    if canonical_json(run.review_version.model_dump(mode="json")) != canonical_json(
        run.export_plan.review_version.model_dump(mode="json")
    ):
        raise RuntimeError("weekly demo review version conflicts with export plan")
    if canonical_json(run.export_report.model_dump(mode="json")) != canonical_json(
        run.export_plan.report.model_dump(mode="json")
    ):
        raise RuntimeError("weekly demo export report conflicts with export plan")

    result = run.result
    build = run.build
    export_report = run.export_report
    review_version = run.review_version
    reconciliation = review_version.reconciliation
    if reconciliation is None:
        raise RuntimeError("weekly demo review version has no reconciliation")
    if reconciliation.content_hash != version_content_hash(review_version):
        raise RuntimeError("weekly demo reconciliation content hash is invalid")
    if (
        reconciliation.model_dump(mode="json")
        != export_report.reconciliation.model_dump(mode="json")
    ):
        raise RuntimeError("weekly demo carries conflicting reconciliations")
    source_evidence, data_gaps = _provenance_registries(run)
    unassigned_items = export_report.unassigned_items
    current_publication = next(
        (
            item for item in run.publications
            if item.source_version_id == review_version.id
            and item.content_hash == reconciliation.content_hash
        ),
        None,
    )
    return {
        "run_id": run.run_id,
        "week_start": build.snapshot.week_start.isoformat(),
        "publication_state": export_report.publication_state,
        "publication_label": export_report.publication_label,
        "review_export_allowed": export_report.review_export_allowed,
        "export_block_reasons": export_report.export_block_reasons,
        "fixed_base": {
            "source": "系統內置照顧員工作分工表2026(HKU).xlsx",
            "worker_columns": len(build.division.workers),
            "fixed_service_candidates": len(build.division.fixed_service_candidates),
            "escort_reserved_slots": sum(
                1 for a in build.division.assignments if a.kind == "escort_slot"
            ),
        },
        "parse_summary": {
            "hc_uploaded_file": run.upload_names["hc_workbook"],
            "hc_parsed": build.hc.summary.parsed_count,
            "hc_selected_for_week": build.source_counts.get("hc_selected", 0),
            "escort_uploaded_file": run.upload_names["escort_workbook"],
            "escort_parsed": build.escort.summary.parsed_count,
            "escort_selected_for_week": build.source_counts.get("escort_selected", 0),
            "ambiguities": build.ambiguity_count,
            "warnings": build.warnings,
        },
        "generation_summary": {
            "entries": len(review_version.entries),
            "unassigned": reconciliation.unassigned,
            "audit_items": len(review_version.audit_items),
            "data_gaps": len(data_gaps),
            "hard_constraint_violations": reconciliation.hard_violation_count,
            "publication_state": reconciliation.publication_state,
            "pending_blocking_audit_items": export_report.pending_blocking_audit_count,
            "needs_review": reconciliation.needs_review,
            "export_failures": reconciliation.export_failure_count,
            "generated_counts": result.generated.counts_by_kind,
            "source_counts": build.source_counts,
        },
        "change_summary": build.change_summaries,
        "version": review_version,
        "impact_reports": result.reports,
        "audit_items": review_version.audit_items,
        "demand_dispositions": reconciliation.dispositions,
        "source_evidence": source_evidence,
        "data_gaps": data_gaps,
        "unassigned_items": unassigned_items,
        "reconciliation": reconciliation,
        "export_report": export_report,
        "review_decisions": run.decisions,
        "manual_overrides": run.manual_overrides,
        "publications": [
            _public_publication(item) for item in run.publications
        ],
        "publication": (
            _public_publication(current_publication)
            if current_publication is not None
            else None
        ),
        "final_export_url": (
            f"/api/demo/weekly-roster/{run.run_id}/published/"
            f"{current_publication.publication_id}"
            if current_publication is not None
            else None
        ),
        "export_token": run.run_id,
        "export_url": f"/api/demo/weekly-roster/{run.run_id}/export",
    }


def _public_publication(publication: PublicationRecord) -> dict[str, Any]:
    """Whitelist publication facts safe for the browser/API consumer."""

    return publication.model_dump(
        mode="json",
        exclude={"artifact_path"},
    )


def _get_or_bootstrap_master_data(division: DivisionImportResult) -> MasterDataSet:
    store = get_state().store
    if store is None:
        return bootstrap_master_data_from_division(division)
    current = store.get_master_data()
    if current is not None:
        return MasterDataSet.model_validate(current["payload"])
    payload = bootstrap_master_data_from_division(division)
    store.save_master_data(
        payload,
        origin=payload.origin,
        issues=validate_master_data(payload),
    )
    return payload


def _source_summary(run: DemoRun) -> dict[str, object]:
    return {
        "目標週": run.build.snapshot.week_start.isoformat(),
        "固定基礎": "內置照顧員工作分工表2026(HKU).xlsx",
        "HC 上傳檔": run.upload_names["hc_workbook"],
        "護送上傳檔": run.upload_names["escort_workbook"],
        "HC 目標週需求": run.build.source_counts.get("hc_selected", 0),
        "護送目標週需求": run.build.source_counts.get("escort_selected", 0),
        "臨時變更": len(run.build.change_summaries),
        "警告": "；".join(run.build.warnings),
    }


def _provenance_registries(run: DemoRun) -> tuple[list[object], list[object]]:
    """Serialize producer registries and reject unresolved or divergent links."""

    evidence_by_id = _strict_producer_registry(
        run.result.generated.source_evidence,
        label="source evidence",
    )
    gap_by_id = _strict_producer_registry(
        run.result.generated.data_gaps,
        label="data gap",
    )
    weekly_demands = run.result.generated.weekly_demands
    demand_ids = _unique_ids(
        [demand.demand_id for demand in weekly_demands],
        label="weekly demand",
    )
    embedded_entries = [
        entry
        for audit in run.review_version.audit_items
        for entry in [audit.original_entry, audit.suggested_entry, *audit.alternatives]
        if entry is not None
    ]
    embedded_entries.extend(
        entry
        for audit in run.review_version.audit_items
        for step in audit.chain
        for entry in [step.entry_before, step.entry_after]
        if entry is not None
    )
    all_entries = [*run.review_version.entries, *embedded_entries]
    entry_ids = _unique_object_payloads(
        all_entries,
        label="schedule entry",
        allow_equal_duplicates=True,
    )
    audit_ids = _unique_ids(
        [audit.id for audit in run.review_version.audit_items],
        label="audit",
    )
    reconciliation = run.review_version.reconciliation
    if reconciliation is None:
        raise RuntimeError("weekly demo review version has no reconciliation")
    _unique_ids(
        [item.demand_id for item in reconciliation.dispositions],
        label="demand disposition",
    )

    for demand in weekly_demands:
        if not demand.demand_id:
            raise RuntimeError("weekly demand has no canonical ID")
        evidence_ids = [item.id for item in demand.source_evidence]
        _unique_ids(evidence_ids, label=f"demand {demand.demand_id} evidence")
        if (
            not evidence_ids
            or not demand.primary_source_evidence_id
            or demand.primary_source_evidence_id not in evidence_ids
        ):
            raise RuntimeError(
                f"weekly demand {demand.demand_id} has invalid primary evidence"
            )
        for evidence in demand.source_evidence:
            _require_payload_match(
                evidence,
                evidence_by_id,
                label=f"demand {demand.demand_id} evidence",
            )
        embedded_gap_ids = {gap.id for gap in demand.data_gaps}
        if set(demand.data_gap_ids) != embedded_gap_ids:
            raise RuntimeError(
                f"weekly demand {demand.demand_id} data-gap IDs drifted"
            )
        _require_ids(
            demand.data_gap_ids,
            gap_by_id,
            label=f"demand {demand.demand_id} data gaps",
        )
        for gap in demand.data_gaps:
            _require_payload_match(
                gap,
                gap_by_id,
                label=f"demand {demand.demand_id} data gap",
            )

    for gap in gap_by_id.values():
        _require_ids(
            gap.source_ref_ids,
            evidence_by_id,
            label=f"data gap {gap.id} evidence",
        )
    for entry in all_entries:
        if entry.demand_id:
            _require_ids(
                [entry.demand_id],
                demand_ids,
                label=f"entry {entry.id} demand",
            )
        _unique_ids(
            [evidence.id for evidence in entry.source_evidence],
            label=f"entry {entry.id} evidence",
        )
        for evidence in entry.source_evidence:
            _require_payload_match(
                evidence,
                evidence_by_id,
                label=f"entry {entry.id} evidence",
            )
        _require_ids(
            entry.data_gap_ids,
            gap_by_id,
            label=f"entry {entry.id} data gaps",
        )
        _require_ids(
            entry.audit_ids,
            audit_ids,
            label=f"entry {entry.id} audits",
        )
    for audit in run.review_version.audit_items:
        _require_ids(audit.demand_ids, demand_ids, label=f"audit {audit.id} demands")
        _require_ids(audit.entry_ids, entry_ids, label=f"audit {audit.id} entries")
        _require_ids(audit.data_gap_ids, gap_by_id, label=f"audit {audit.id} gaps")
        _require_ids(
            audit.evidence_refs,
            evidence_by_id,
            label=f"audit {audit.id} evidence",
        )
    for disposition in reconciliation.dispositions:
        _require_ids(
            [disposition.demand_id],
            demand_ids,
            label="disposition demand",
        )
        _require_ids(
            [disposition.entry_id] if disposition.entry_id else [],
            entry_ids,
            label=f"disposition {disposition.demand_id} entry",
        )
        _require_ids(
            disposition.audit_ids,
            audit_ids,
            label=f"disposition {disposition.demand_id} audits",
        )
        _require_ids(
            disposition.source_ref_ids,
            evidence_by_id,
            label=f"disposition {disposition.demand_id} evidence",
        )
    return (
        [evidence_by_id[key] for key in sorted(evidence_by_id)],
        [gap_by_id[key] for key in sorted(gap_by_id)],
    )


def _strict_producer_registry(items, *, label: str) -> dict[str, object]:
    registry: dict[str, object] = {}
    for item in items:
        if not item.id:
            raise RuntimeError(f"{label} producer has no ID")
        if item.id in registry:
            raise RuntimeError(f"duplicate {label} producer ID: {item.id}")
        payload = item.model_dump(mode="json")
        try:
            validated = type(item).model_validate(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            raise RuntimeError(f"invalid {label} producer {item.id}: {exc}") from exc
        if canonical_json(validated.model_dump(mode="json")) != canonical_json(payload):
            raise RuntimeError(f"invalid {label} producer payload: {item.id}")
        registry[item.id] = item
    return registry


def _unique_ids(items, *, label: str) -> set[str]:
    values = list(items)
    if any(not item for item in values):
        raise RuntimeError(f"{label} has a missing ID")
    unique = set(values)
    if len(unique) != len(values):
        raise RuntimeError(f"duplicate {label} ID")
    return unique


def _unique_object_payloads(
    items,
    *,
    label: str,
    allow_equal_duplicates: bool,
) -> set[str]:
    payloads: dict[str, str] = {}
    for item in items:
        payload = canonical_json(item.model_dump(mode="json"))
        prior = payloads.get(item.id)
        if prior is not None and (
            not allow_equal_duplicates or prior != payload
        ):
            raise RuntimeError(f"conflicting {label} payload for ID: {item.id}")
        payloads[item.id] = payload
    return set(payloads)


def _require_payload_match(item, registry: dict[str, object], *, label: str) -> None:
    producer = registry.get(item.id)
    if producer is None:
        raise RuntimeError(f"{label} references missing producer: {item.id}")
    if canonical_json(item.model_dump(mode="json")) != canonical_json(
        producer.model_dump(mode="json")
    ):
        raise RuntimeError(f"{label} payload differs from producer: {item.id}")


def _require_ids(items, registry, *, label: str) -> None:
    values = list(items)
    if len(values) != len(set(values)):
        raise RuntimeError(f"{label} contains duplicate IDs")
    missing = sorted({item for item in values if item not in registry})
    if missing:
        raise RuntimeError(f"{label} references missing IDs: {missing}")
