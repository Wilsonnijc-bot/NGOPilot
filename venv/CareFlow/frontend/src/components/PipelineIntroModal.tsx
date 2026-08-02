import { useEffect, useMemo, useRef, useState } from "react";
import type { PipelineIntroContent } from "../lib/pipelineIntroContent";
import {
  getIntroFrameState,
  presentIntroFrame,
  subscribeIntroFrame,
} from "../lib/pipelineIntroFrameRegistry";

type PipelineIntroModalProps = {
  intro: PipelineIntroContent;
};

const LOCAL_PREFIX = "careflow.pipelineIntro.dismissed.";

function safeGet(storage: Storage, key: string) {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(storage: Storage, key: string, value: string) {
  try {
    storage.setItem(key, value);
  } catch {
    // Ignore private-mode or quota errors; the modal can still close in memory.
  }
}

export default function PipelineIntroModal({ intro }: PipelineIntroModalProps) {
  const localKey = useMemo(() => `${LOCAL_PREFIX}${intro.id}`, [intro.id]);
  const frameMountRef = useRef<HTMLDivElement | null>(null);
  const releaseFrameRef = useRef<(() => void) | null>(null);
  const [open, setOpen] = useState(false);
  const [closedForNow, setClosedForNow] = useState(false);
  const [animationFailed, setAnimationFailed] = useState(false);
  const [animationReady, setAnimationReady] = useState(false);

  const animationSrc = intro.animationCandidates[0] || null;

  useEffect(() => {
    setClosedForNow(false);
    setAnimationFailed(false);
    setAnimationReady(false);
  }, [intro.id]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (closedForNow) return;
    if (safeGet(window.localStorage, localKey) === "1") return;

    if (!animationSrc) {
      setOpen(true);
      return;
    }

    const state = getIntroFrameState(animationSrc);
    if (state === "ready") {
      setAnimationReady(true);
      setOpen(true);
      return;
    }
    if (state === "error") {
      setAnimationFailed(true);
      setOpen(true);
      return;
    }

    const unsubscribe = subscribeIntroFrame(animationSrc, (nextState) => {
      if (nextState === "ready") {
        setAnimationReady(true);
        setOpen(true);
      }
      if (nextState === "error") {
        setAnimationFailed(true);
        setOpen(true);
      }
    });

    const fallback = window.setTimeout(() => {
      if (getIntroFrameState(animationSrc) === "ready") {
        setAnimationReady(true);
        setOpen(true);
      }
    }, 5000);

    return () => {
      window.clearTimeout(fallback);
      unsubscribe();
    };
  }, [animationSrc, closedForNow, localKey]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeForNow();
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const closeForNow = () => {
    setClosedForNow(true);
    setOpen(false);
  };

  const closeForever = () => {
    if (typeof window !== "undefined") {
      safeSet(window.localStorage, localKey, "1");
    }
    setClosedForNow(true);
    setOpen(false);
  };

  useEffect(() => {
    if (!open || !animationSrc || !animationReady || animationFailed || !frameMountRef.current) return;

    releaseFrameRef.current?.();
    const release = presentIntroFrame(animationSrc, frameMountRef.current);
    if (!release) {
      setAnimationFailed(true);
      return;
    }
    releaseFrameRef.current = release;

    return () => {
      releaseFrameRef.current?.();
      releaseFrameRef.current = null;
    };
  }, [animationFailed, animationReady, animationSrc, open]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={`pipeline-intro-title-${intro.id}`}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-900/75 px-4 py-5 backdrop-blur-md sm:px-6 sm:py-8"
    >
      <div className="w-[min(920px,calc(100vw-48px))] max-h-[calc(100vh-64px)] overflow-hidden border border-paper-200/80 bg-paper-50">
        <div className="max-h-[calc(100vh-64px)] overflow-y-auto">
          <div className="relative bg-paper-50">
            <div className="relative aspect-video w-full overflow-hidden bg-paper-50">
              {animationSrc && !animationFailed ? (
                <div ref={frameMountRef} className="h-full w-full bg-paper-50" />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-paper-50 px-8 text-center">
                  <div>
                    <div className="font-serif text-2xl text-ink-900">導覽動畫尚未載入</div>
                    <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-400">
                      請將對應 HTML 放入 <span className="font-mono">asset/html</span>。
                      例如本流程可使用{" "}
                      <span className="font-mono">
                        {decodeURIComponent(intro.animationCandidates[0]?.replace("/demo-html/", "") || "")}
                      </span>
                      。
                    </p>
                  </div>
                </div>
              )}

              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-paper-50/90 to-transparent" />
              <div className="absolute left-4 top-4 border border-paper-50/55 bg-paper-50/88 px-3 py-1.5 backdrop-blur-md sm:left-5 sm:top-5">
                <div className="folio text-ink-500">{intro.eyebrow}</div>
              </div>
              <button
                type="button"
                className="absolute right-4 top-4 border border-paper-50/55 bg-paper-50/88 px-3 py-1.5 font-mono text-[11px] tracking-wider text-ink-500 backdrop-blur-md transition-colors hover:border-cinnabar-500/60 hover:text-cinnabar-600 sm:right-5 sm:top-5"
                onClick={closeForNow}
                aria-label="關閉介紹"
              >
                關閉
              </button>
            </div>

            <section className="relative bg-paper-50 px-6 pb-6 pt-5 md:px-8 md:pb-7">
              <div className="grid gap-6 md:grid-cols-[1.12fr_0.88fr]">
                <div>
                  <h2 id={`pipeline-intro-title-${intro.id}`} className="font-serif text-[26px] leading-tight text-ink-900 sm:text-3xl">
                    {intro.title}
                  </h2>
                  <p className="mt-3 font-serif text-base leading-relaxed text-ink-900 sm:text-lg">
                    {intro.summary}
                  </p>
                </div>
                <div className="md:border-l md:border-paper-300/80 md:pl-6">
                  <div className="eyebrow mb-3">你會看到</div>
                  <ul className="space-y-2 text-sm leading-relaxed text-ink-700">
                    {intro.points.map((point) => (
                      <li key={point} className="flex gap-2">
                        <span className="mt-2 h-1.5 w-1.5 shrink-0 bg-cinnabar-500" />
                        <span>{point}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>

            <div className="flex flex-wrap items-center justify-between gap-3 bg-paper-100/55 px-6 py-4 shadow-[inset_0_1px_0_rgba(14,12,10,0.08)] md:px-8">
              <div className="folio text-ink-400">
                可隨時關閉；只有選擇「下次不顯示」才會永久記住。
              </div>
              <div className="flex gap-3">
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={closeForNow}
                >
                  先看界面
                </button>
                <button
                  type="button"
                  className="btn-stamp"
                  onClick={closeForever}
                >
                  關閉且下次不顯示
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
