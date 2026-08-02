export type PipelineIntroId = "desk" | "alpha" | "beta" | "gamma" | "theta";

export type PipelineIntroContent = {
  id: PipelineIntroId;
  eyebrow: string;
  title: string;
  summary: string;
  points: string[];
  animationCandidates: string[];
};

const demoHtml = (...names: string[]) => names.map((name) => `/demo-html/${encodeURIComponent(name)}`);

export const PIPELINE_INTROS: Record<PipelineIntroId, PipelineIntroContent> = {
  desk: {
    id: "desk",
    eyebrow: "工作台 Desk",
    title: "今日案頭",
    summary:
      "CareFlow 的主界面是一張社區照護行政工作台：四條流水線、最近案卷、AI 三通道狀態與啟用模板集中在同一個入口。",
    points: [
      "從四張流水線卡片進入紙本、語音、福利表與自訂 PDF 模板流程。",
      "最近案卷會顯示進度、審查數與狀態印章，方便回到未完成工作。",
      "右側可快速確認文本、視覺、語音三路 AI 是否為 live 或 mock。",
    ],
    animationCandidates: demoHtml("careflow-00-main-desk.html"),
  },
  alpha: {
    id: "alpha",
    eyebrow: "流水線 Alpha",
    title: "志工紙本表 → NGO Excel",
    summary:
      "把手填探訪表照片收進一個案卷，先由 AI 抽取欄位，再由同事逐張覆核，最後按機構 Excel 模板匯出。",
    points: [
      "拖入多張紙本照片，系統會建立同一批次案卷。",
      "抽取完成後進入三欄審查：左側縮圖、中間原圖定位、右側欄位修正。",
      "所有 AI 結果必經人工確認後，才可用印匯出 Excel。",
    ],
    animationCandidates: demoHtml("careflow-α-volunteer-excel.html"),
  },
  beta: {
    id: "beta",
    eyebrow: "流水線 Beta",
    title: "语音转录 → 結構化報告",
    summary:
      "上傳錄音與機構 DOCX 模板，CareFlow 會轉錄、分析模板欄位並草擬報告；同事覆核後才渲染最終 DOCX。",
    points: [
      "可處理家訪錄音或內部會議紀要。",
      "逐字稿以加密方式保存，審查界面只顯示摘要與結構化欄位。",
      "覆核完成後可下載 DOCX，並可執行閱後即焚。",
    ],
    animationCandidates: demoHtml("careflow-β-audio-docx.html"),
  },
  gamma: {
    id: "gamma",
    eyebrow: "流水線 Gamma",
    title: "福利表 → 已填寫 PDF",
    summary:
      "從長者資料或社工筆記抽取個人事實，選擇政府或 NGO 表格模板，預覽欄位對應後生成可下載 PDF。",
    points: [
      "可使用 mock 長者資料，也可從文字或照片抽取 ElderProfile。",
      "每個欄位都會標出來源：直接、預設、AI 推測、缺失或手改。",
      "生成前可逐欄覆核與改寫，生成後直接預覽 PDF。",
    ],
    animationCandidates: demoHtml("careflow-γ-welfare-pdf.html"),
  },
  theta: {
    id: "theta",
    eyebrow: "流水線 Theta",
    title: "自訂 PDF 表 → 可重用模板",
    summary:
      "上傳任意空白 PDF 表單，由 GPT 先識別欄位與位置，再由人手校正 bounding boxes，保存後可在福利表流程重用。",
    points: [
      "上傳 PDF 後會看到逐頁分析的進度遮罩與欄位統計。",
      "審查頁用三欄布局呈現：頁面縮圖、PDF bbox 畫布、欄位編輯器。",
      "儲存後的自訂模板會出現在 Gamma 福利表流程的自訂模板區。",
    ],
    animationCandidates: demoHtml("careflow-θ-custom-template.html"),
  },
};
