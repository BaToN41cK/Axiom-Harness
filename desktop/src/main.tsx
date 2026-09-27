import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
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
