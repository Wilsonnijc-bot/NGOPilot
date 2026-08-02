"""應用設定 — 讀取 .env。"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── AI 三路供應商（v0.4.0-rc6 重構） ──────────────────────────────────
    # 文字推理 → DeepSeek 官方 API（OpenAI 相容）
    # 視覺抽取 → OpenAI 官方 API · GPT-5-mini
    # 語音轉錄 → Bailian / DashScope · fun-asr
    # 三路完全獨立，不再共用 `llm_provider` 開關。
    # 舊 `llm_provider` 欄位保留只供 /api/health 與 legacy 日誌讀取，不再控制路由。

    # 文字（DeepSeek 官方）
    # v0.4.5: 預設由 deepseek-v4-pro（reasoning model，重模板 ~7.5 min）
    # 改為 deepseek-v4-flash（非推理，~4x 加速、同等 JSON 結構化品質）。
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_text_model: str = "deepseek-v4-flash"

    # 視覺（Azure OpenAI · GPT-5-mini）
    # rc6.1 修正：依用戶要求，視覺改回 Azure OpenAI（不走 api.openai.com）
    # `openai_*` 欄位保留純為 .env 相容；主視覺路由請看 azure_openai_*。
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_vision_model: str = "gpt-5-mini"

    # 語音（Bailian / DashScope · fun-asr）
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_asr_model: str = "fun-asr"

    # ── Legacy 欄位（保留 .env 相容，不再用於主流程） ────────────────────
    llm_provider: Literal["bailian", "deepseek_official", "tencent_hunyuan", "mock", "auto"] = "auto"
    llm_text_model: str = "deepseek-v4-flash"   # legacy alias of deepseek_text_model
    llm_vision_model: str = "gpt-5-mini"      # legacy alias of openai_vision_model
    llm_asr_model: str = "fun-asr"            # legacy alias of bailian_asr_model
    hunyuan_api_key: str = ""
    hunyuan_base_url: str = "https://api.hunyuan.cloud.tencent.com/v1"

    # ── Azure OpenAI（rc6.1：主視覺路徑，使用 GPT-5-mini deployment） ──────
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "careflow-gpt-5-mini"
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_model: str = "gpt-5-mini"
    azure_fallback_enabled: bool = False  # 不再雙路 fallback；單路 Azure
    primary_vision_provider: str = "azure"  # rc6.1: 固定走 Azure OpenAI

    # ── 應用 ─────────────────────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    data_dir: str = "./data"
    asset_dir: str = "../asset"  # 後端內部資源（mock 表照片、字型示例…），不對外暴露
    database_url: str = "sqlite:///./data/careflow.db"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # ── 抽取參數 ─────────────────────────────────────────────────────────────
    # v0.3.9: Qwen 主路徑改為「快敗、早交給 Azure」
    #   - retries 1→0：不再多 attempt 一輪 corrective prompt（單張 attempt 已含內部 timeout）
    #   - timeout 60→45 秒：實測 Qwen 抽不到的張，60s 也大多回不來，提早交棒
    vision_max_retries: int = 0
    vision_timeout_seconds: float = 45.0
    vision_confidence_threshold: float = 0.7

    # ── Helpers ─────────────────────────────────────────────────────────────
    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir).resolve()
        for sub in ("uploads", "exports", "samples", "templates"):
            (p / sub).mkdir(parents=True, exist_ok=True)
        return p

    @property
    def asset_path(self) -> Path:
        """後端內部資源資料夾（mock 表照片等），不會被 /api/files 暴露。"""
        p = Path(self.asset_dir).resolve()
        for sub in ("mock_forms",):
            (p / sub).mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_mock_mode(self) -> bool:
        """全 mock 判定：當三路 key 皆缺、且未顯式選 mock provider 時為 True。

        注意：個別 caller 應改用更精細的 `is_text_mock` / `is_vision_mock` /
        `is_asr_mock`；此屬性僅保留給尚未遷移的 legacy 程式碼（welfare /
        diagnose 等）。
        """
        if self.llm_provider == "mock":
            return True
        return not (
            self.deepseek_api_key or self.azure_openai_api_key or self.dashscope_api_key
        )

    @property
    def is_text_mock(self) -> bool:
        return self.llm_provider == "mock" or not self.deepseek_api_key

    @property
    def is_vision_mock(self) -> bool:
        # rc6.1：視覺改走 Azure OpenAI；需要 key + endpoint 才算就緒
        return self.llm_provider == "mock" or not (
            self.azure_openai_api_key and self.azure_openai_endpoint
        )

    @property
    def is_asr_mock(self) -> bool:
        return self.llm_provider == "mock" or not self.dashscope_api_key


settings = Settings()
