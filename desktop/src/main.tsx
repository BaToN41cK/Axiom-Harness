import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// Local-first fonts and the design-token layer come first: everything below
// resolves its colours, spacing and typography from these two files.
import "./styles/fonts.css";
import "./styles/tokens.css";
// Design-system primitives (`ax-*`). Loaded before the legacy sheets so the
// existing domain CSS can still win where it needs to during the migration.
import "./styles/ui.css";
// W2.7: styles are split per domain and imported in the original cascade
// order — base tokens/components first, then the extracted domain partials.
import "./styles.css";
import "./styles/boot.css";
import "./styles/orchestration.css";
import "./styles/virtualization.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
