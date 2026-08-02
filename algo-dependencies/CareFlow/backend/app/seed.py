"""一鍵 seed：生成 mock 照片 + 建立示範批次 + 跑 AI 抽取。

用法：
    python -m app.seed              # 完整 seed（建議 demo 用）
    python -m app.seed --only-photos # 只生成照片不建批次
    python -m app.seed --reset      # 清空現有資料庫後 seed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlmodel import Session, delete

from .config import settings
from .db import engine, init_db
from .models import BatchStatus, FieldCorrection, VolunteerBatch, VolunteerRecord
from .services import excel_export, mock_generator, volunteer_form


def _reset_db():
    init_db()
    with Session(engine) as s:
        s.exec(delete(FieldCorrection))
        s.exec(delete(VolunteerRecord))
        s.exec(delete(VolunteerBatch))
        s.commit()
    print("[seed] 已清空 volunteer 相關資料表")


def _generate_photos(count: int) -> list[Path]:
    print(f"[seed] 生成 {count} 張 mock 志工探訪表照片 …")
    paths = mock_generator.generate_samples(count)
    print(f"[seed] 完成，輸出於 {settings.asset_path / 'mock_forms'}")
    return paths


def _ensure_template():
    p = excel_export.ensure_template_exists()
    print(f"[seed] 確認 Excel 模板：{p}")


def _make_demo_batch(photos: list[Path]):
    with Session(engine) as s:
        batch = volunteer_form.create_batch(
            s,
            title="2026-05-12 深水埗志工探訪示範批次",
            volunteer_team="中大義工隊",
            visit_date="2026-05-12",
            note="seed.py 自動生成的示範批次，含 20 張 mock 照片。",
        )
        print(f"[seed] 建立示範批次 id={batch.id}")
        volunteer_form.import_existing_photos(s, batch.id, photos)  # type: ignore[arg-type]
        print(f"[seed] 已匯入 {len(photos)} 張照片")
        # 跑抽取（mock 模式下會用 _MOCK_POOL，真實模式下會打 VLM）
        print("[seed] 開始抽取 …（若無 API key 將走 mock 模式）")
        volunteer_form.run_extraction(s, batch.id)  # type: ignore[arg-type]
        print(f"[seed] 抽取完成，狀態 → {BatchStatus.PENDING_REVIEW.value}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only-photos", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    if args.reset:
        _reset_db()
    else:
        init_db()

    _ensure_template()
    photos = _generate_photos(args.count)

    if args.only_photos:
        print("[seed] --only-photos 模式，跳過建立批次。")
        return

    _make_demo_batch(photos)
    print("\n[seed] 全部完成 ✅  打開前端後即可看到「2026-05-12 深水埗志工探訪示範批次」")


if __name__ == "__main__":
    main()
