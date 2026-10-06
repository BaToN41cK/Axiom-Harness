import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

type Resolver = { resolve: (v: unknown) => void; reject: (e: Error) => void };

const pending = new Map<number, Resolver>();

export type CoreEventHandler = (event: unknown) => void;
const eventHandlers = new Set<CoreEventHandler>();

const stderrHandlers = new Set<(text: string) => void>();
const exitHandlers = new Set<() => void>();

let initialized = false;

async function ensureListener() {
  if (initialized) return;
  initialized = true;
  await listen<unknown>("bridge://line", (event) => {
    const payload = event.payload as {
      type?: string;
      req?: number;
      ok?: boolean;
      data?: unknown;
      error?: string;
      event?: unknown;
    };
    if (payload.type === "event" && payload.event) {
      for (const handler of eventHandlers) handler(payload.event);
      return;
    }
    if (payload.type === "reply" && typeof payload.req === "number") {
      // The Rust shell broadcasts "bridge-exited" (req 0) when the Python core
      // has died. Reject *every* pending request in that case — otherwise they
      // hang forever and the UI silently ignores user actions (model
      // switching looks broken while nothing reports an error).
      const exited =
        payload.ok === false && payload.error && payload.error.includes("bridge-exited");
      if (exited) {
        const exitError = new Error(
          "Ядро остановлено. Перезапустите его в настройках (Ctrl+,) или перезапустите приложение.",
        );
        for (const resolver of pending.values()) resolver.reject(exitError);
        pending.clear();
        for (const handler of exitHandlers) handler();
        return;
      }
      const resolver = pending.get(payload.req);
      if (!resolver) return;
      pending.delete(payload.req);
      if (payload.ok) resolver.resolve(payload.data);
      else resolver.reject(new Error(payload.error || "bridge error"));
    }
  });
  await listen<string>("bridge://stderr", (event) => {
    const text = String(event.payload ?? "");
    for (const handler of stderrHandlers) handler(text);
  });
}

/** Fire-and-await JSONL request to the Python core. */
export async function request<T = unknown>(
  cmd: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  await ensureListener();
  const req = Date.now() * 1000 + Math.floor(Math.random() * 1000);
  return await new Promise<T>((resolve, reject) => {
    pending.set(req, {
      resolve: (value: unknown) => {
        // The first successful reply proves the Python core is really
        // reachable, which is the last startup stage (`bridge-ready`).
        if (!coreReadyReported) {
          coreReadyReported = true;
          void invoke("frontend_ready", { core: true }).catch(() => {});
        }
        resolve(value as T);
      },
      reject,
    });
    void invoke("bridge_request", { payload: { req, cmd, args } }).catch((err) => {
      pending.delete(req);
      reject(err instanceof Error ? err : new Error(String(err)));
    });
  });
}

/** Guards the one-shot bridge readiness acknowledgement. */
let coreReadyReported = false;

/** Restart the Python core subprocess (used after Ollama restarts). */
export async function restartCore(): Promise<void> {
  await invoke("bridge_restart");
}

/** Open a link in the real browser (the webview must never navigate away). */
export async function openExternal(url: string): Promise<void> {
  await invoke("open_url", { url });
}

/** Close AXIOM (used by `/exit`). */
export async function quitApp(): Promise<void> {
  await invoke("quit_app");
}

/**
 * Startup readiness acknowledgement.
 *
 * The Rust side deliberately does not treat a live process, `windows=["main"]`
 * or a valid HWND as readiness — it waits for this signal so a failed launch
 * surfaces an actionable error instead of an invisible instance. `core` is set
 * once a real round-trip to the Python core has succeeded.
 */
export async function reportFrontendReady(core = false): Promise<void> {
  await invoke("frontend_ready", { core });
}

/** Subscribe to async core events (streaming, status, done...). */
export function onCoreEvent(handler: CoreEventHandler): () => void {
  eventHandlers.add(handler);
  return () => {
    eventHandlers.delete(handler);
  };
}

/** Raw stderr of the Python core — surfaced in the debug section of Settings. */
export function onCoreStderr(handler: (text: string) => void): () => void {
  stderrHandlers.add(handler);
  void ensureListener();
  return () => {
    stderrHandlers.delete(handler);
  };
}

/** Fired when the core process is gone; the UI explains it instead of hanging. */
export function onCoreExit(handler: () => void): () => void {
  exitHandlers.add(handler);
  return () => {
    exitHandlers.delete(handler);
  };
}
