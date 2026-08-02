export function polishFrameDocument(doc: Document) {
  const win = doc.defaultView;
  if (!win) return;

  if (!doc.getElementById("careflow-frame-polish")) {
    const style = doc.createElement("style");
    style.id = "careflow-frame-polish";
    style.textContent = `
      html, body, #dc-root {
        background: #fcfaf3 !important;
        overflow: hidden !important;
      }
      #__bundler_loading,
      #__bundler_thumbnail {
        display: none !important;
      }
      * {
        box-shadow: none !important;
      }
    `;
    doc.head.appendChild(style);
  }

  Array.from(doc.body.querySelectorAll<HTMLElement>("*")).forEach((node) => {
    const style = win.getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    const text = node.textContent || "";

    if (
      style.backgroundColor === "rgb(10, 10, 10)" ||
      style.backgroundColor === "rgba(20, 20, 20, 0.92)"
    ) {
      node.style.background = "#fcfaf3";
    }

    const looksLikePlayerBar =
      rect.bottom > win.innerHeight - 6 &&
      rect.height >= 32 &&
      rect.height <= 80 &&
      text.includes(":");
    if (looksLikePlayerBar) {
      node.style.display = "none";
    }
  });
}

export function isFrameDocumentReady(doc: Document | null | undefined) {
  if (!doc?.body) return false;
  polishFrameDocument(doc);
  return Boolean(doc.getElementById("dc-root"));
}
