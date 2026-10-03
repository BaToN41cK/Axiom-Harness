import { useEffect, useRef, useState } from "react";
import { request } from "../bridge";
import type { PluginRow, UIExtension } from "../types";
import { useLocale } from "../lib/locale";

/**
 * W3.1 — isolated host for a plugin UI panel.
 *
 * The plugin's own document (`ui/index.html`) runs inside a sandboxed iframe
 * (`allow-scripts` only — no `allow-same-origin`, no navigation, no forms), so
 * it has an opaque origin and cannot touch AXIOM's DOM or IPC. The only channel
 * out is `parent.postMessage`, which we validate strictly and forward to the
 * core `plugin_host` gate; a plugin can never call an undeclared capability, and
 * a broken plugin can only fail inside its own frame.
 */
export default function PluginPanelHost({ plugin, extension }: { plugin: PluginRow; extension: UIExtension }) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [reloadKey, setReloadKey] = useState(0);
  const { t } = useLocale();

  useEffect(() => {
    let alive = true;
    setStatus("loading");
    request<{ html: string | null }>("plugin_ui_html", { name: plugin.name })
      .then((res) => {
        if (!alive) return;
        setHtml(res.html);
        setStatus(res.html ? "loading" : "error");
      })
      .catch(() => alive && setStatus("error"));
    return () => {
      alive = false;
    };
  }, [plugin.name, reloadKey]);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const msg = event.data as Record<string, unknown> | null;
      if (!msg || typeof msg !== "object") return;
      // Strictly typed envelope: reject anything not a plugin request, and only
      // accept it from the plugin this panel belongs to.
      if (typeof msg.id !== "string" || typeof msg.method !== "string" || typeof msg.plugin !== "string") return;
      if (msg.plugin !== plugin.name) return;
      const frame = iframeRef.current;
      if (!frame || event.source !== frame.contentWindow) return;
      const params = typeof msg.params === "object" && msg.params !== null ? (msg.params as Record<string, unknown>) : {};
      request<{ ok: boolean; data?: unknown; error?: string | null }>("plugin_host", {
        id: msg.id,
        plugin: msg.plugin,
        method: msg.method,
        params,
      })
        .then((res) => {
          frame.contentWindow?.postMessage({ id: msg.id, ok: res.ok, data: res.data, error: res.error ?? null }, "*");
        })
        .catch((err) => {
          frame.contentWindow?.postMessage({ id: msg.id, ok: false, data: null, error: String(err) }, "*");
        });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [plugin.name]);

  if (status === "error" || html === null) {
    return (
      <div className="plugin-panel-empty">
        <span>{t("ui.plugin.panel_title", { title: String(extension.meta?.title ?? extension.id) })}</span>
        <small>{t("ui.plugin.panel_unavailable")}</small>
      </div>
    );
  }

  return (
    <div className="plugin-panel">
      <div className="plugin-panel-bar">
        <span className="plugin-panel-title">{t("ui.plugin.panel_title", { title: String(extension.meta?.title ?? extension.id) })}</span>
        <button className="btn ghost" onClick={() => setReloadKey((n) => n + 1)} title={t("ui.plugin.reload")}>{t("ui.common.refresh")}</button>
      </div>
      <iframe
        ref={iframeRef}
        className="plugin-panel-frame"
        sandbox="allow-scripts"
        title={String(extension.meta?.title ?? extension.id)}
        srcDoc={html}
        onLoad={() => setStatus("ready")}
      />
    </div>
  );
}
