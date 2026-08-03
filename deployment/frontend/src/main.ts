import "../../../harness bone/ui/desktop/src/styles/main.css";
import "./auth.css";
import { requireAuthentication } from "./auth";
import { installBrowserShim } from "./browser-shim";

async function start(): Promise<void> {
  const root = document.getElementById("root");
  if (!root) throw new Error("NGOPilot root element is missing");

  installBrowserShim();
  await requireAuthentication(root);
  await import("@ngopilot/renderer");
}

void start();
