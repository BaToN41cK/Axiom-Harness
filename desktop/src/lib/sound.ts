/**
 * Small frontend-only UI sound layer.
 *
 * It deliberately uses Web Audio instead of adding assets or a dependency.
 * The preference is local to the desktop UI and is not sent through the
 * bridge/core. Sounds are disabled until the user explicitly enables them.
 */

export type UiSound = "search" | "complete" | "settings" | "panel" | "model" | "success" | "error";

const STORAGE_KEY = "axiom.soundEnabled";
let audioContext: AudioContext | null = null;
let enabled = readPreference();
let lastPlayed = -Infinity;
const voices = new Set<OscillatorNode>();

function readPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function isSoundEnabled(): boolean { return enabled; }

export function setSoundEnabled(value: boolean): void {
  enabled = value;
  try {
    localStorage.setItem(STORAGE_KEY, String(value));
  } catch {
    // Storage can be unavailable; the current session still remains usable.
  }
  if (!value) {
    for (const voice of voices) {
      try { voice.stop(); } catch { /* already ended */ }
    }
    voices.clear();
    lastPlayed = -Infinity;
  }
}

function context(): AudioContext | null {
  if (typeof window === "undefined" || typeof AudioContext === "undefined") return null;
  if (!audioContext) audioContext = new AudioContext();
  return audioContext;
}

/** Prepare/resume audio only after a real user gesture, never on boot/events. */
export function installSoundActivation(): () => void {
  const activate = (event: Event) => {
    if (!event.isTrusted || !enabled) return;
    try {
      const ctx = context();
      if (ctx?.state === "suspended") void ctx.resume().catch(() => {});
    } catch { /* Audio can be unavailable in restricted webviews. */ }
  };
  window.addEventListener("pointerdown", activate, true);
  window.addEventListener("keydown", activate, true);
  return () => {
    window.removeEventListener("pointerdown", activate, true);
    window.removeEventListener("keydown", activate, true);
  };
}

/** Play a short, deliberately quiet tonal cue after a user-initiated action. */
export function playUiSound(kind: UiSound): void {
  if (!isSoundEnabled()) return;
  // Async events must not initialize audio or bypass the user gesture gate.
  const ctx = audioContext;
  if (!ctx || ctx.state !== "running" || performance.now() - lastPlayed < 160) return;
  lastPlayed = performance.now();
  try {
    const now = ctx.currentTime;
    const frequencies: Record<UiSound, number> = {
      search: 440, complete: 660, settings: 330, panel: 380,
      model: 520, success: 590, error: 180,
    };
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = kind === "error" ? "triangle" : "sine";
    oscillator.frequency.setValueAtTime(frequencies[kind], now);
    oscillator.frequency.exponentialRampToValueAtTime(frequencies[kind] * (kind === "error" ? 0.82 : 1.08), now + 0.075);
    // Quiet peak gain; perceived loudness still depends on the user's device.
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(kind === "error" ? 0.018 : 0.012, now + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.095);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    voices.add(oscillator);
    oscillator.onended = () => {
      voices.delete(oscillator);
      oscillator.disconnect();
      gain.disconnect();
    };
    oscillator.start(now);
    oscillator.stop(now + 0.105);
  } catch {
    // Audio is optional and must never interrupt a UI action.
  }
}