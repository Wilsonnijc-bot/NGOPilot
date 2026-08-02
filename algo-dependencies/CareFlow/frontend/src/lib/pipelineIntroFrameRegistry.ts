import { isFrameDocumentReady, polishFrameDocument } from "./pipelineIntroFrame";

export type IntroFrameState = "idle" | "loading" | "ready" | "error";

type Listener = (state: IntroFrameState) => void;

const frames = new Map<string, HTMLIFrameElement>();
const hosts = new Map<string, HTMLElement>();
const states = new Map<string, IntroFrameState>();
const listeners = new Map<string, Set<Listener>>();

function emit(src: string) {
  const state = getIntroFrameState(src);
  listeners.get(src)?.forEach((listener) => listener(state));
}

export function getIntroFrameState(src: string): IntroFrameState {
  return states.get(src) || "idle";
}

export function subscribeIntroFrame(src: string, listener: Listener) {
  const set = listeners.get(src) || new Set<Listener>();
  set.add(listener);
  listeners.set(src, set);
  return () => {
    set.delete(listener);
    if (set.size === 0) listeners.delete(src);
  };
}

export function markIntroFrameState(src: string, state: IntroFrameState) {
  if (states.get(src) === state) return;
  states.set(src, state);
  emit(src);
}

export function registerIntroFrameHost(src: string, host: HTMLElement | null) {
  if (!host) {
    hosts.delete(src);
    return;
  }
  hosts.set(src, host);
}

export function registerIntroFrame(src: string, frame: HTMLIFrameElement | null) {
  if (!frame) {
    frames.delete(src);
    return;
  }

  frames.set(src, frame);
  if (pollIntroFrameReady(src)) return;
  if (states.get(src) !== "ready") {
    markIntroFrameState(src, "loading");
  }
}

export function pollIntroFrameReady(src: string) {
  const frame = frames.get(src);
  if (!frame) return false;

  try {
    const doc = frame.contentDocument;
    if (!doc?.body) return false;
    polishFrameDocument(doc);
    if (!isFrameDocumentReady(doc)) return false;
    markIntroFrameState(src, "ready");
    // Keep the frame rendered (display:block, parked off-screen) after boot.
    // Setting display:none here permanently breaks the SVG <foreignObject>
    // paint in Chromium: once the compositing layer is dropped while hidden it
    // never re-rasterizes when the frame is later shown, leaving it blank.
    return true;
  } catch {
    markIntroFrameState(src, "ready");
    return true;
  }
}

export function markIntroFrameError(src: string) {
  markIntroFrameState(src, "error");
}

export function presentIntroFrame(src: string, target: HTMLElement) {
  const frame = frames.get(src);
  if (!frame) return null;

  const updatePosition = () => {
    const rect = target.getBoundingClientRect();
    Object.assign(frame.style, {
      border: "0",
      display: "block",
      height: `${rect.height}px`,
      left: `${rect.left}px`,
      opacity: "1",
      pointerEvents: "none",
      position: "fixed",
      top: `${rect.top}px`,
      width: `${rect.width}px`,
      zIndex: "70",
    });
  };

  updatePosition();
  window.addEventListener("resize", updatePosition);
  window.addEventListener("scroll", updatePosition, true);

  try {
    const doc = frame.contentDocument;
    if (doc?.body) polishFrameDocument(doc);
  } catch {
    // Cross-origin access is not expected for same-origin demo assets, but the
    // already loaded frame can still be displayed if the browser blocks access.
  }

  return () => {
    window.removeEventListener("resize", updatePosition);
    window.removeEventListener("scroll", updatePosition, true);
    const host = hosts.get(src);
    host?.appendChild(frame);
    // Park the frame off-screen but keep it painted (no display:none / opacity:0)
    // so the foreignObject layer survives and re-presents correctly next time.
    Object.assign(frame.style, {
      border: "0",
      display: "block",
      height: "720px",
      left: "-20000px",
      opacity: "1",
      pointerEvents: "none",
      position: "fixed",
      top: "0",
      width: "1280px",
      zIndex: "0",
    });
  };
}
