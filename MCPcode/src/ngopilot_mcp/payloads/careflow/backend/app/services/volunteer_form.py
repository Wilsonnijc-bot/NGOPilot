"""志工探訪表服務 — 功能 2 核心。

職責：
- 建立批次 + 接收照片
- 觸發 OpenAI GPT-5-mini 視覺抽取（並行 / ThreadPoolExecutor）  ← rc6 改單路
- 寫入 VolunteerRecord，狀態流轉到 pending_review
- 提供 auto_complete_record：使用者開「自動補全」時呼叫
"""
from __future__ import annotations

import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from ..config import settings
from ..llm.vision import (
    FIELD_KEYS,
    VOLUNTEER_FORM_FIELDS,
    assess_completeness,
    auto_complete_fields,
    extract_volunteer_form,
)
from ..llm.text import review_volunteer_extraction
from ..llm.text import _log_event  # type: ignore[attr-defined]
from ..models import BatchStatus, FieldCorrection, VolunteerBatch, VolunteerRecord

EXTRACTION_PARALLELISM = 2


def get_field_schema() -> list[dict]:
    return VOLUNTEER_FORM_FIELDS


def create_batch(
    session: Session,
    *,
    title: str,
    volunteer_team: str | None = None,
    visit_date: str | None = None,
    note: str | None = None,
) -> VolunteerBatch:
    batch = VolunteerBatch(
        title=title,
        volunteer_team=volunteer_team,
        visit_date=visit_date,
        note=note,
        status=BatchStatus.UPLOADED,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def add_photos(
    session: Session,
    batch_id: int,
    files: list[tuple[str, bytes]],  # (filename, bytes)
) -> list[VolunteerRecord]:
    """寫入照片檔到 data/uploads/<batch_id>/，建立 VolunteerRecord。"""
    upload_dir = settings.data_path / "uploads" / f"batch_{batch_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    created: list[VolunteerRecord] = []
    for filename, content in files:
        safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
        target = upload_dir / safe_name
        target.write_bytes(content)
        rec = VolunteerRecord(
            batch_id=batch_id,
            photo_path=str(target.relative_to(settings.data_path)),
            original_filename=filename,
        )
        session.add(rec)
        created.append(rec)

    # 更新 batch.total_photos
    batch = session.get(VolunteerBatch, batch_id)
    if batch:
        batch.total_photos += len(files)
        batch.updated_at = datetime.utcnow()
        session.add(batch)
    session.commit()
    for r in created:
        session.refresh(r)
    return created


def import_existing_photos(
    session: Session,
    batch_id: int,
    photo_paths: list[Path],
) -> list[VolunteerRecord]:
    """從已存在的檔案路徑建立紀錄（seed 用）。"""
    upload_dir = settings.data_path / "uploads" / f"batch_{batch_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    files = [(p.name, p.read_bytes()) for p in photo_paths]
    return add_photos(session, batch_id, files)


def run_extraction(session: Session, batch_id: int, *, auto_complete: bool = False) -> None:
    """對一個批次內所有尚未抽取的紀錄跑 VLM（並行）。

    auto_complete=True 時，每份抽取完成後若判定「不完整」會立即呼叫 LLM 補全。
    """
    batch = session.get(VolunteerBatch, batch_id)
    if not batch:
        return
    batch.status = BatchStatus.EXTRACTING
    batch.updated_at = datetime.utcnow()
    session.add(batch)
    session.commit()

    try:
        records = session.exec(
            select(VolunteerRecord).where(VolunteerRecord.batch_id == batch_id)
        ).all()
        pending = [(idx, rec) for idx, rec in enumerate(records) if not rec.ai_extracted]

        # ── 並行處理：ThreadPoolExecutor 並發打 VLM API ─────────────────────────────
        # rc6: 視覺單路 — OpenAI 官方 GPT-5-mini，移除 Qwen/Azure 雙路 fallback 邏輯。
        def _extract_one(idx: int, photo_full: Path):
            try:
                return extract_volunteer_form(photo_full, photo_index=idx), None
            except Exception as exc:  # noqa: BLE001
                return None, str(exc)

        results: dict[int, tuple[dict | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=EXTRACTION_PARALLELISM) as ex:
            futures = {
                ex.submit(_extract_one, idx, settings.data_path / rec.photo_path): (idx, rec.id)
                for idx, rec in pending
            }
            for fut in as_completed(futures):
                idx, rec_id = futures[fut]
                results[rec_id] = fut.result()

        _log_event(
            "extraction_phase_done",
            n_pending=len(pending),
            provider="openai",
            model=settings.openai_vision_model,
        )

        # ── 回寫 DB（主線程 serial，避免 SQLite 並發寫話） ──────────────────────────
        for _idx, rec in pending:
            result, err = results.get(rec.id, (None, "no_result"))

            if err or not result:
                # 視覺單路失敗 → 人工介入
                rec.ai_error = (
                    f"OpenAI GPT-5-mini 視覺抽取失敗，請手動填入。（err: {err or 'no_result'}）"
                )
                rec.ai_extracted = {"__needs_human_input__": True}
                rec.updated_at = datetime.utcnow()
                session.add(rec)
                continue

            meta = result.pop("_meta", {})
            fields = result["fields"]
            non_empty_count = sum(
                1 for v in fields.values()
                if v is not None and v != "" and v != []
            )

            if non_empty_count == 0:
                fields = dict(fields)
                fields["__needs_human_input__"] = True
                rec.ai_error = (
                    "視覺模型返回空白 — 影像可能模糊或內容不清，請手動填入。"
                )
            rec.ai_extracted = fields
            rec.ai_confidence = result["confidence"]
            rec.ai_bbox = result["bbox"]
            rec.ai_provider = meta.get("provider")
            rec.ai_model = meta.get("model")
            rec.ai_latency_ms = meta.get("latency_ms")
            rec.ai_raw_response = meta.get("raw")
            rec.ai_error = meta.get("error") or rec.ai_error
            rec.final_fields = dict(result["fields"])
            rec.updated_at = datetime.utcnow()
            session.add(rec)
        # 先 flip 狀態為 PENDING_REVIEW，讓使用者立刻看到結果；autocomplete 在後面跑
        batch.status = BatchStatus.PENDING_REVIEW
        batch.updated_at = datetime.utcnow()
        session.add(batch)
        session.commit()
    except Exception:
        # rc6.audit-H：抽取階段 uncaught → 批次絕不能停在 EXTRACTING（前端會永遠
        # 轉圈圈）。flip 到 FAILED，server-side log 留 traceback。
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        try:
            batch = session.get(VolunteerBatch, batch_id)
            if batch:
                batch.status = BatchStatus.FAILED
                batch.updated_at = datetime.utcnow()
                session.add(batch)
                session.commit()
        except Exception:  # noqa: BLE001
            pass
        _log_event(
            "extraction_phase_uncaught",
            batch_id=batch_id,
        )
        import logging
        logging.getLogger(__name__).exception("run_extraction uncaught (batch_id=%s)", batch_id)
        raise

    # ── DeepSeek 二次審查 + 自動補全（永遠並行跑；預設自動套用）────────────────
    # 流程：
    #   1) **永遠**呼叫 DeepSeek 審查（不再只審「疑似」欄位）
    #      → 把所有非 meta 欄位都丟給 DeepSeek，並把預先判定的 missing/partial/low_conf
    #         做為「重點關注」提示
    #   2) DeepSeek 自行判斷哪些 key 需要修，並回傳 `{key: {value, reason, confidence}}`
    #   3) serial writeback：把 Qwen 原值存到 `__qwen_original__` 供撤回
    #   4) 標記 `__reviewed_keys__` / `__reviewed_reasons__` / `__reviewed_confidence__`
    try:
        _run_deepseek_review(session, pending)
    except Exception as e:  # 不能讓 review 階段擋住批次完成
        _log_event(
            "review_phase_error",
            batch_id=batch_id,
            error_type=type(e).__name__,
            error=str(e)[:300],
        )


def _run_deepseek_review(session: Session, pending: list[tuple[int, VolunteerRecord]]) -> None:
    _log_event("review_phase_start", n_pending=len(pending))
    targets: list[tuple[VolunteerRecord, list[str], list[str]]] = []
    for _idx, rec in pending:
        session.refresh(rec)
        ai = _strip_meta_dict(rec.ai_extracted or {})
        if not ai:  # Qwen 完全空白 → 沒有上下文可審查
            _log_event("review_skip_empty", record_id=rec.id, reason="qwen_returned_empty")
            continue
        comp = assess_completeness(rec.ai_extracted, rec.ai_confidence)
        partial_keys = list((comp.get("partial_fields") or {}).keys())
        flagged = list(dict.fromkeys(
            list(comp["missing_fields"])
            + partial_keys
            + list(comp["low_confidence_fields"])
        ))
        all_keys = list(ai.keys())
        # 把 missing/partial/low_conf 放到 candidate_keys 最前面（提示優先級）
        candidate = list(dict.fromkeys(flagged + all_keys))
        targets.append((rec, candidate, flagged))

    if targets:
        def _review_one(rec: VolunteerRecord, candidate: list[str], flagged: list[str]):
            try:
                res = review_volunteer_extraction(
                    fields=_strip_meta_dict(rec.ai_extracted or {}),
                    confidence=rec.ai_confidence or {},
                    suspicious_keys=candidate,
                    field_schema=VOLUNTEER_FORM_FIELDS,
                    flagged_keys=flagged,
                )
                return rec.id, res, None
            except Exception as exc:  # noqa: BLE001
                return rec.id, None, str(exc)

        rv_results: dict[int, tuple[dict | None, str | None]] = {}
        with ThreadPoolExecutor(max_workers=EXTRACTION_PARALLELISM) as ex:
            futs = {ex.submit(_review_one, rec, cand, flag): rec.id for rec, cand, flag in targets}
            for fut in as_completed(futs):
                rid, res, err = fut.result()
                rv_results[rid] = (res, err)

        # serial writeback
        for rec, _cand, _flag in targets:
            res, err = rv_results.get(rec.id, (None, "no_result"))
            if err or not res:
                continue
            reviewed: dict = res.get("reviewed") or {}
            if not reviewed:
                continue
            new_fields = dict(rec.ai_extracted or {})
            new_conf = dict(rec.ai_confidence or {})
            qwen_original = dict(new_fields.get("__qwen_original__") or {})
            reviewed_keys: list[str] = list(new_fields.get("__reviewed_keys__") or [])
            reasons: dict = dict(new_fields.get("__reviewed_reasons__") or {})
            rev_conf: dict = dict(new_fields.get("__reviewed_confidence__") or {})

            applied_count = 0
            for k, info in reviewed.items():
                if k.startswith("__"):
                    continue
                new_value = info.get("value")
                old_value = _strip_meta_dict(new_fields).get(k)
                # 若新舊值完全一樣（DeepSeek 認可原值），不算「修改」，不打標
                if new_value == old_value:
                    continue
                # 寧缺勿造假：DeepSeek 設 null 而原本也是 None → 不改動
                if new_value is None and old_value is None:
                    continue
                if k not in qwen_original:
                    qwen_original[k] = new_fields.get(k)
                new_fields[k] = new_value
                new_conf[k] = float(info.get("confidence") or 0.5)
                if k not in reviewed_keys:
                    reviewed_keys.append(k)
                reasons[k] = str(info.get("reason") or "")
                rev_conf[k] = float(info.get("confidence") or 0.5)
                applied_count += 1

            if applied_count == 0:
                continue  # DeepSeek 看過但沒改動任何欄位

            new_fields["__qwen_original__"] = qwen_original
            new_fields["__reviewed_keys__"] = reviewed_keys
            new_fields["__reviewed_reasons__"] = reasons
            new_fields["__reviewed_confidence__"] = rev_conf
            rec.ai_extracted = new_fields
            rec.ai_confidence = new_conf
            # final_fields 永遠反映目前最終值（不含 meta key）
            rec.final_fields = {k: new_fields.get(k) for k in FIELD_KEYS}
            rec.updated_at = datetime.utcnow()
            session.add(rec)
        session.commit()


def _strip_meta_dict(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("__")}


def delete_record(session: Session, record_id: int) -> dict:
    """刪除一張紀錄（v0.3.9 — 「這頁沒價值」場景）。

    步驟：
    1. 刪除附屬的 FieldCorrection
    2. 刪除照片檔（best-effort，不擋失敗）
    3. 從 DB 移除 record
    4. 更新 batch.total_photos / confirmed_count；若全 batch 都審完，狀態自動進 CONFIRMED
    回傳 `{deleted: True, record_id, batch_id, photo_unlinked, batch}`。
    """
    rec = session.get(VolunteerRecord, record_id)
    if not rec:
        raise ValueError(f"record {record_id} not found")

    batch_id = rec.batch_id

    # v0.3.9 補丁：不能刪掉一個 batch 內的最後一張
    # （那會留下一個空殼 batch，狀態邏輯也無意義；刪整批請走未來 DELETE /batches/{id}）
    sibling_count = session.exec(
        select(VolunteerRecord).where(VolunteerRecord.batch_id == batch_id)
    ).all()
    if len(sibling_count) <= 1:
        raise ValueError("此批次只剩這一張，不能刪除；若整批不需要，請改用「取消批次」功能。")

    was_reviewed = bool(rec.is_reviewed)
    photo_rel = rec.photo_path
    photo_unlinked = False
    photo_full = settings.data_path / photo_rel if photo_rel else None

    # 1. corrections
    corrections = session.exec(
        select(FieldCorrection).where(FieldCorrection.record_id == record_id)
    ).all()
    for c in corrections:
        session.delete(c)

    # 2. disk file（best-effort）
    if photo_full and photo_full.exists():
        try:
            photo_full.unlink()
            photo_unlinked = True
        except OSError:
            photo_unlinked = False

    # 3. record
    session.delete(rec)

    # 4. batch counters
    batch = session.get(VolunteerBatch, batch_id)
    if batch:
        if batch.total_photos > 0:
            batch.total_photos -= 1
        if was_reviewed and batch.confirmed_count > 0:
            batch.confirmed_count -= 1
        # 若刪掉之後 confirmed_count == total_photos 且 total_photos > 0 → 進 CONFIRMED
        if batch.total_photos > 0 and batch.confirmed_count >= batch.total_photos \
                and batch.status != BatchStatus.EXPORTED:
            batch.status = BatchStatus.CONFIRMED
            batch.confirmed_at = datetime.utcnow()
        batch.updated_at = datetime.utcnow()
        session.add(batch)

    session.commit()

    return {
        "deleted": True,
        "record_id": record_id,
        "batch_id": batch_id,
        "photo_unlinked": photo_unlinked,
        "remaining_in_batch": batch.total_photos if batch else 0,
    }


def revert_reviewed_field(session: Session, record_id: int, field_key: str) -> VolunteerRecord:
    """前端「撤回」按鈕：把某欄位從 DeepSeek 審查值還原為 Qwen 原值。"""
    rec = session.get(VolunteerRecord, record_id)
    if not rec:
        raise ValueError(f"record {record_id} not found")
    ai = dict(rec.ai_extracted or {})
    qwen_orig: dict = ai.get("__qwen_original__") or {}
    reviewed_keys: list = list(ai.get("__reviewed_keys__") or [])
    reasons: dict = dict(ai.get("__reviewed_reasons__") or {})
    rev_conf: dict = dict(ai.get("__reviewed_confidence__") or {})
    if field_key not in reviewed_keys:
        return rec  # 沒被審查過，無事可做
    # 把欄位還原為 Qwen 原值
    ai[field_key] = qwen_orig.get(field_key)
    reviewed_keys.remove(field_key)
    reasons.pop(field_key, None)
    rev_conf.pop(field_key, None)
    # 清掉 qwen_original 中此 key 的紀錄（已還原）
    if field_key in qwen_orig:
        qwen_orig.pop(field_key)
    ai["__qwen_original__"] = qwen_orig
    ai["__reviewed_keys__"] = reviewed_keys
    ai["__reviewed_reasons__"] = reasons
    ai["__reviewed_confidence__"] = rev_conf
    rec.ai_extracted = ai
    rec.final_fields = {k: ai.get(k) for k in FIELD_KEYS}
    rec.updated_at = datetime.utcnow()
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def _apply_auto_complete(session: Session, rec: VolunteerRecord, completeness: dict) -> None:
    """呼叫 LLM 補全，寫回 rec.ai_extracted + final_fields + ai_confidence。

    同時在 ai_extracted 中記載「哪些欄位是補全來的」（__auto_filled_keys__），
    供前端顯示「AI 推測」徽記。
    """
    photo_full = settings.data_path / rec.photo_path
    res = auto_complete_fields(
        photo_full,
        present_fields=rec.ai_extracted or {},
        missing_fields=completeness["missing_fields"],
        low_confidence_fields=completeness["low_confidence_fields"],
    )
    filled = res.get("auto_filled") or {}
    confs = res.get("auto_filled_confidence") or {}
    if not filled:
        return

    new_fields = dict(rec.ai_extracted or {})
    new_conf = dict(rec.ai_confidence or {})
    auto_keys: list[str] = []
    for k, v in filled.items():
        new_fields[k] = v
        new_conf[k] = float(confs.get(k) or 0.5)
        auto_keys.append(k)
    # 記載補全來源（透過 ai_extracted 進 JSON，免 schema 變動）
    new_fields["__auto_filled_keys__"] = auto_keys
    rec.ai_extracted = new_fields
    rec.ai_confidence = new_conf
    rec.final_fields = {k: new_fields.get(k) for k in FIELD_KEYS}
    rec.updated_at = datetime.utcnow()
    session.add(rec)


def auto_complete_record(session: Session, record_id: int) -> VolunteerRecord:
    """手動觸發某一份紀錄的 AI 補全。"""
    rec = session.get(VolunteerRecord, record_id)
    if not rec:
        raise ValueError(f"record {record_id} not found")
    comp = assess_completeness(rec.ai_extracted, rec.ai_confidence)
    if comp["is_complete"] and not comp["low_confidence_fields"]:
        return rec
    _apply_auto_complete(session, rec, comp)
    session.commit()
    session.refresh(rec)
    return rec


def review_record(
    session: Session,
    record_id: int,
    final_fields: dict,
    reviewer: str | None = None,
) -> VolunteerRecord:
    """社工提交一張照片的審查結果（記入 corrections）。"""
    rec = session.get(VolunteerRecord, record_id)
    if not rec:
        raise ValueError(f"record {record_id} not found")

    ai = rec.ai_extracted or {}
    conf = rec.ai_confidence or {}

    # 逐欄 diff 寫入 corrections
    for k in FIELD_KEYS:
        ai_val = ai.get(k)
        new_val = final_fields.get(k)
        if _normalise_for_compare(ai_val) != _normalise_for_compare(new_val):
            session.add(FieldCorrection(
                record_id=rec.id,
                batch_id=rec.batch_id,
                field_name=k,
                ai_value=None if ai_val is None else str(ai_val),
                final_value=None if new_val is None else str(new_val),
                ai_confidence=float(conf.get(k) or 0.0),
                reviewer=reviewer,
            ))

    rec.final_fields = {k: final_fields.get(k) for k in FIELD_KEYS}
    rec.is_reviewed = True
    rec.reviewer = reviewer
    rec.reviewed_at = datetime.utcnow()
    rec.updated_at = datetime.utcnow()
    session.add(rec)

    # 更新 batch.confirmed_count
    batch = session.get(VolunteerBatch, rec.batch_id)
    if batch:
        confirmed = session.exec(
            select(VolunteerRecord).where(
                VolunteerRecord.batch_id == rec.batch_id,
                VolunteerRecord.is_reviewed == True,  # noqa: E712
            )
        ).all()
        batch.confirmed_count = len(confirmed)
        if batch.confirmed_count >= batch.total_photos and batch.status != BatchStatus.EXPORTED:
            batch.status = BatchStatus.CONFIRMED
            batch.confirmed_at = datetime.utcnow()
        batch.updated_at = datetime.utcnow()
        session.add(batch)
    session.commit()
    session.refresh(rec)
    return rec


def _normalise_for_compare(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip()
    return v


def compute_diff_stats(session: Session, batch_id: int) -> dict:
    """供歷史頁顯示：本批次哪些欄位最常被修改、平均 AI 信心。"""
    corrections = session.exec(
        select(FieldCorrection).where(FieldCorrection.batch_id == batch_id)
    ).all()
    by_field: dict[str, dict] = {}
    for c in corrections:
        f = by_field.setdefault(c.field_name, {"count": 0, "avg_conf": 0.0, "samples": []})
        f["count"] += 1
        f["avg_conf"] += c.ai_confidence or 0.0
        if len(f["samples"]) < 3:
            f["samples"].append({"ai": c.ai_value, "final": c.final_value})
    for f in by_field.values():
        if f["count"]:
            f["avg_conf"] = round(f["avg_conf"] / f["count"], 3)
    return {"total_corrections": len(corrections), "by_field": by_field}
