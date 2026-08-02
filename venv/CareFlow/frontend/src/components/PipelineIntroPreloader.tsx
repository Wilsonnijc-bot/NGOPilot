import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { PIPELINE_INTROS, type PipelineIntroId } from "../lib/pipelineIntroContent";
import {
  markIntroFrameError,
  pollIntroFrameReady,
  registerIntroFrame,
  registerIntroFrameHost,
} from "../lib/pipelineIntroFrameRegistry";

const LOCAL_PREFIX = "careflow.pipelineIntro.dismissed.";

const ROUTE_INTROS: Array<[RegExp, PipelineIntroId]> = [
  [/^\/$/, "desk"],
  [/^\/volunteer\/upload\/?$/, "alpha"],
  [/^\/home-visit\/?$/, "beta"],
  [/^\/welfare-form\/?$/, "gamma"],
  [/^\/theta\/upload\/?$/, "theta"],
];

function introForPath(pathname: string) {
  return ROUTE_INTROS.find(([pattern]) => pattern.test(pathname))?.[1] || null;
}

function isDismissed(id: PipelineIntroId) {
  try {
    return window.localStorage.getItem(`${LOCAL_PREFIX}${id}`) === "1";
  } catch {
    return false;
  }
}

export default function PipelineIntroPreloader() {
  const { pathname } = useLocation();
  const [activeSrcs, setActiveSrcs] = useState<string[]>([]);
  const timersRef = useRef<number[]>([]);

  const orderedIntros = useMemo(() => {
    const current = introForPath(pathname);
    const ids = Object.keys(PIPELINE_INTROS) as PipelineIntroId[];
    const ordered = current ? [current, ...ids.filter((id) => id !== current)] : ids;
    return ordered.filter((id) => !isDismissed(id));
  }, [pathname]);

  useEffect(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current = [];

    const srcs = orderedIntros
      .map((id) => PIPELINE_INTROS[id].animationCandidates[0])
      .filter(Boolean);

    setActiveSrcs((prev) => {
      const current = srcs[0];
      if (!current) return prev;
      return [current, ...prev.filter((src) => src !== current)];
    });

    srcs.slice(1).forEach((src, index) => {
      const schedule = () => {
        setActiveSrcs((prev) => (prev.includes(src) ? prev : [...prev, src]));
      };

      const timeout = window.setTimeout(() => {
        if ("requestIdleCallback" in window) {
          const idle = window.requestIdleCallback(schedule, { timeout: 2500 });
          timersRef.current.push(window.setTimeout(() => window.cancelIdleCallback(idle), 2600));
          return;
        }
        schedule();
      }, 1800 + index * 1600);
      timersRef.current.push(timeout);
    });

    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, [orderedIntros]);

  // NOTE: this wrapper must NOT be `position: fixed`. A position:fixed iframe
  // nested inside a position:fixed ancestor breaks Chromium's SVG <foreignObject>
  // rasterization, leaving the preloaded intro animation blank when it is later
  // revealed. `absolute` keeps the same zero-footprint, off-screen behavior while
  // letting the foreignObject paint correctly.
  return (
    <div aria-hidden="true" className="pointer-events-none absolute left-0 top-0 h-0 w-0 overflow-hidden">
      {activeSrcs.map((src) => (
        <div
          key={src}
          ref={(node) => registerIntroFrameHost(src, node)}
          style={{ height: 720, width: 1280 }}
        >
          <iframe
            ref={(node) => registerIntroFrame(src, node)}
            src={src}
            title={`Preload ${src}`}
            loading="eager"
            sandbox="allow-scripts allow-same-origin"
            tabIndex={-1}
            onLoad={() => {
              if (pollIntroFrameReady(src)) return;
              let attempts = 0;
              const timer = window.setInterval(() => {
                attempts += 1;
                if (pollIntroFrameReady(src) || attempts > 120) {
                  window.clearInterval(timer);
                }
              }, 100);
            }}
            onError={() => markIntroFrameError(src)}
            style={{
              border: 0,
              display: "block",
              height: 720,
              left: -20000,
              opacity: 1,
              pointerEvents: "none",
              position: "fixed",
              top: 0,
              width: 1280,
              zIndex: 0,
            }}
          />
        </div>
      ))}
    </div>
  );
}
