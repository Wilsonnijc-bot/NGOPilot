# 護流 CareFlow

> **CareFlow — AI 照護工作站**
> 你護老，我護你。

香港前線長者照護工作者的 AI 行政助理。系統強制「AI 擬稿、人工複核」工作流：所有 AI 抽取結果都必須經社工確認後才寫入正式檔案，個資錄音稿支援「閱後即焚」。

---

## 一、四條流水線

| 代號 | 流程 | 輸入 | 輸出 | 狀態 |
|---|---|---|---|---|
| **α** | 志工紙本表 → NGO Excel | 多張手填表照片 | 對應 NGO 模板的 `.xlsx` | ✅ 上線 |
| **β** | 家訪語音 → 結構化報告 | 粵語錄音 + 模板 | 結構化 JSON / docx | ✅ 上線 |
| **γ** | 政府福利表 → 已填寫 PDF | 長者資料 + 表格 | 已填 PDF | ✅ 上線 |
| **θ** | 自訂 PDF 空表 → 可重用模板 | 任意 PDF 空白表 | 欄位座標 + bbox 模板 | ✅ 上線 |

每條流水線都進入相同的「左圖右表 / 左音右表」人工審查介面：信心值色標、欄位 bbox 溯源、所有修改寫入 `corrections` 表用於 prompt 反饋。

---

## 二、技術棧

| 層 | 選擇 |
|---|---|
| 文字 / 推理 LLM | **DeepSeek-V4-Pro / Flash**（OpenAI 兼容，streaming 模式） |
| 視覺 VLM | **Azure AI Foundry · GPT-5.1**（azure-ai-inference SDK，wrapper 自動處理 Foundry projects endpoint） |
| 語音 ASR | **DashScope · fun-asr / fun-asr-realtime**（阿里雲百煉，粵語） |
| 後端 | Python 3.11+ + FastAPI + SQLModel |
| 任務隊列 | Celery（背景 LLM / 渲染任務） |
| 資料庫 | SQLite（單機部署） |
| 前端 | Vite + React 18 + TypeScript + TailwindCSS（古文卷宗設計系統） |
| Excel | `openpyxl`（保留模板格式 / 合併格 / 公式） |
| PDF | PyMuPDF + Qwen-VL bbox 抽取 |
| 加密 | Fernet（錄音稿 at-rest 對稱加密 + 閱後即焚） |
| 部署 | Docker Compose |

> 三路 LLM client（[backend/app/llm/client.py](backend/app/llm/client.py)）互相獨立，任一路缺 key 即各自退回 mock，不影響其餘兩路。

---

## 三、快速啟動

### 1. 準備 `.env`

```bash
cp backend/.env.example backend/.env
```

打開 `backend/.env`，填入三組 key（缺一可，會自動降級為 mock）：

```env
# 文字推理（DeepSeek 官方）
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 視覺抽取（Azure AI Foundry · GPT-5.1）
AZURE_OPENAI_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-5.1
AZURE_OPENAI_API_VERSION=2024-05-01-preview
AZURE_OPENAI_MODEL=gpt-5.1

# 語音轉錄（DashScope · fun-asr）
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

> Azure 端點可直接貼 Foundry「project」URL（`/api/projects/<project>`）— `_FoundryWrapper` 會自動降到 resource root 並掛 `/models`。

### 2. 本地開發

```bash
# 後端
cd backend
uv venv && source .venv/bin/activate
uv pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### 3. Docker 部署

```bash
cp .env.example .env

# 只在第一次建立公网 demo 密码文件；不要提交这个文件。
printf "careflow-demo:$(openssl passwd -apr1 '<change-this-password>')\n" > frontend/.htpasswd.local

docker compose build backend frontend
docker compose up -d
# 本机打开 http://localhost:8080；公网 demo 用 Cloudflare Tunnel 指向 localhost:8080。
```

默认镜像版本为 `0.4.8`，由 `CAREFLOW_VERSION` 控制。生产机若使用已推送镜像，可运行：

```bash
docker compose -f docker-compose.deploy.yml up -d
```

停止：`docker compose down`

---

## 四、目錄結構

```
CareFlow/
├── backend/
│   ├── app/
│   │   ├── main.py              FastAPI 入口
│   │   ├── config.py            pydantic-settings + .env
│   │   ├── db.py                SQLModel + SQLite
│   │   ├── llm/
│   │   │   ├── client.py        三路 client（DeepSeek / Azure Foundry / DashScope）
│   │   │   ├── vision.py        GPT-5.1 視覺抽取（α / θ）
│   │   │   ├── text.py          DeepSeek 文字 / 結構化（β / γ）
│   │   │   └── asr.py           fun-asr 粵語語音
│   │   ├── services/
│   │   │   ├── volunteer_form.py        α 流水線
│   │   │   ├── home_visit.py            β 流水線（含 phase1 抽取）
│   │   │   ├── welfare_form_filler.py   γ 流水線（PDF 半自動填寫）
│   │   │   ├── theta_template.py        θ 流水線（PDF 模板學習）
│   │   │   ├── excel_export.py          openpyxl 寫入
│   │   │   └── pdf_render.py            PyMuPDF 渲染 + 加密
│   │   └── api/
│   │       ├── volunteer.py     α 上傳 / 抽取 / 審查 / 匯出
│   │       ├── home_visit.py    β 錄音上傳 / 抽取 / 焚毀
│   │       ├── welfare_form.py  γ 半自動填寫
│   │       ├── theta.py         θ PDF 模板學習 / 套用
│   │       ├── history.py       歷史 / 篩選 / diff
│   │       ├── elders.py        長者資料 CRUD
│   │       └── diagnose.py      三通道健康檢查
│   └── alembic/                 資料庫遷移
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── VolunteerUpload.tsx / VolunteerReview.tsx
│       │   ├── HomeVisit.tsx / HomeVisitReview.tsx
│       │   ├── WelfareForm.tsx
│       │   ├── ThetaUpload.tsx / ThetaAudit.tsx
│       │   ├── Templates.tsx          NGO Excel / θ 模板管理
│       │   ├── Settings.tsx           三通道偏好
│       │   ├── History.tsx / HistoryDetail.tsx
│       ├── components/
│       │   ├── Layout.tsx             側欄 + skip-link
│       │   ├── DropLabel.tsx          全站拖入元件
│       │   └── StatusStamp.tsx        卷宗風格狀態徽記
│       └── lib/
│           └── visitStatus.ts         STATUS_LABELS / TERMINAL_STATUSES
├── docs/
│   ├── COSTS.md                       NGO 成本估算
│   └── NGO-MEETING-CHEATSHEET.md      面談話術 + Q&A
├── docker-compose.yml
├── docker-compose.deploy.yml
└── backend/.env.example
```

---

## 五、人工審查（強制）

所有 AI 輸出**不允許**直接落到正式檔。四條流水線共用同一審查模型：

```
輸入（照片 / 錄音 / PDF）──► AI 抽取（status = pending_review）
                                  │
                                  ▼
            左輸入 / 右表格審查介面
            ├─ 逐欄信心值色標（紅 < 0.7、黃 0.7–0.9、綠 ≥ 0.9）
            ├─ 點欄位看 AI 從何處抽（α / θ 顯示 bbox）
            └─ 任何修改寫入 corrections 表（後續 prompt 改進）
                                  │
                                  ▼
            社工點「確認並用印」(status = confirmed)
                                  │
                                  ▼
            寫入正式檔（Excel / PDF / docx）
            β 錄音稿可隨時「閱後即焚」(Fernet 解密 key 銷毀)
```

## 六、改動歷史

### v0.4.8-cleanup-docker · 2026-06-29 PDT（repo 清理 + Docker 版本固定 + demo healthcheck）

- 清理已追蹤的本地運行產物：舊 venv、上傳檔、匯出檔、轉錄檔、session 音檔、臨時 PDF / Excel / template、前端 build cache。
- 刪除不再使用的 θ bbox refiner 與歷史 PDF probe/fix scripts。
- `.gitignore` 補齊 runtime data、模板暫存、前端 cache、egg-info、pid/log 等忽略規則。
- Docker compose 從裸 `latest` 改為 `CAREFLOW_VERSION` 固定 tag（預設 `0.4.8`），並把 backend data volume 收斂到 `./backend/data:/app/data`。
- backend 只保留容器內部 `8000`，frontend 只綁定 `127.0.0.1:8080`；Basic Auth 密碼檔由 `frontend/.htpasswd.local` 掛載，不進 image / git。
- frontend nginx 新增 `/healthz`，compose 為 backend/frontend 補 healthcheck；frontend 等 backend healthy 後再啟動。
- `visit_note` 測試更新到目前 package path，移除已不存在的舊 CLI 測試。
