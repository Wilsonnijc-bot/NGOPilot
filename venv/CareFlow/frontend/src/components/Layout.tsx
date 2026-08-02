import { NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import PipelineIntroPreloader from "./PipelineIntroPreloader";

type NavItem = { to: string; label: string; num: string; primary?: boolean };
type NavSection = { eyebrow: string; items: NavItem[] };

const sections: NavSection[] = [
  {
    eyebrow: "卷宗",
    items: [
      { to: "/", label: "工作台", num: "00" },
      { to: "/history", label: "歷史紀錄", num: "01" },
      { to: "/templates", label: "輸出模板", num: "02" },
      { to: "/settings", label: "案頭偏好", num: "03" },
    ],
  },
  {
    eyebrow: "處理流水線",
    items: [
      { to: "/volunteer/upload", label: "志工紙本 → Excel", num: "α", primary: true },
      { to: "/home-visit", label: "语音转录 → 報告", num: "β", primary: true },
      { to: "/welfare-form", label: "福利表 → PDF", num: "γ" },
      { to: "/theta/upload", label: "自訂 PDF 表 → 模板", num: "θ", primary: true },
    ],
  },
];

export default function Layout() {
  return (
    <div className="flex min-h-screen">
      <PipelineIntroPreloader />
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 bg-paper-50 border border-cinnabar-500 px-3 py-1 text-sm">跳至內容</a>
      <aside className="w-72 shrink-0 border-r border-ink-900/15 bg-paper-100/60 backdrop-blur-sm flex flex-col">
        <div className="px-6 pt-7 pb-5 border-b border-ink-900/15">
          <div className="flex items-center gap-3">
            <div className="chop">護</div>
            <div>
              <div className="font-serif text-2xl tracking-wide text-ink-900 leading-none">
                護 流
              </div>
              <div className="folio mt-1">CAREFLOW · v0.4.5</div>
            </div>
          </div>
          <p className="mt-4 text-[11px] leading-relaxed text-ink-400">
            為香港社區照護而生的 AI 行政助理 — 將文書時間
            <span className="text-cinnabar-500">  歸 還 </span>
            予長者照護。
          </p>
        </div>

        <nav className="flex-1 px-6 py-5 space-y-7 overflow-y-auto">
          {sections.map((sec) => (
            <div key={sec.eyebrow}>
              <div className="eyebrow mb-3">{sec.eyebrow}</div>
              <ul className="space-y-0.5">
                {sec.items.map((it) => (
                  <li key={it.to}>
                    <NavLink
                      to={it.to}
                      end={it.to === "/"}
                      className={({ isActive }) =>
                        clsx(
                          "group flex items-center gap-3 py-1.5 text-sm transition-colors",
                          isActive
                            ? "text-cinnabar-500"
                            : "text-ink-700 hover:text-cinnabar-500"
                        )
                      }
                    >
                      <span className="folio w-6 shrink-0">{it.num}</span>
                      <span className={clsx("flex-1", it.primary && "font-medium")}>
                        {it.label}
                      </span>
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="px-6 py-4 border-t border-ink-900/15 text-[11px] leading-relaxed text-ink-400">
          <div className="flex items-center gap-2 mb-1">
            <span className="conf-dot conf-high"></span>
            <span>強制人工審查工作流</span>
          </div>
          <div className="folio">DeepSeek-V4 · Qwen3.6-VL · Fun-ASR</div>
        </div>
      </aside>

      <main id="main" className="flex-1 overflow-x-hidden">
        <Outlet />
      </main>
    </div>
  );
}
