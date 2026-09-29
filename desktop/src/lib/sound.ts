/**
 * Small frontend-only UI sound layer.
 *
 * It deliberately uses Web Audio instead of adding assets or a dependency.
 * The preference is local to the desktop UI and is not sent through the
 * bridge/core. Sounds are disabled until the user explicitly enables them.
 *
 * Every cue is a *recipe*, not just a pitch: waveform, a short melodic figure
 * and an envelope per note. That is what makes "answer ready" audibly
 * different from "error" or "permission required", instead of every cue being
 * the same blip at another frequency.
 *
 * One cue = one oscillator. Multiple notes come from scheduled frequency steps
 * with a re-articulated gain, so the node count stays minimal.
 */

export type UiSound =
  | "search"
  | "complete"
  | "settings"
  | "panel"
  | "model"
  | "success"
  | "error"
  | "permission"
  | "stopped";

/** One note inside a cue. `at` is an offset from the start of the cue. */
interface Note {
  at: number;
  freq: number;
  len: number;
  peak: number;
  /** Optional glide target: turns the note into a sweep. */
  glideTo?: number;
}

interface Recipe {
  wave: OscillatorType;
  notes: Note[];
}

/**
 * Perceived loudness depends on the user's device, so the ceiling stays low
 * and every recipe is clamped against it.
 */
const MAX_PEAK = 0.018;

/**
 * The palette. Pitches are chosen so cues differ as gestures, not just as
 * numbers: rising = finished, falling = stopped, low and buzzy = error,
 * alternating = needs your attention.
 */
const RECIPES: Record<UiSound, Recipe> = {
  /** Answer ready: calm rising two-note chime (D5 → A5). */
  complete: {
    wave: "sine",
    notes: [
      { at: 0, freq: 587.33, len: 0.13, peak: 0.011 },
      { at: 0.115, freq: 880, len: 0.2, peak: 0.013 },
    ],
  },

  /** Error: low, buzzy and falling. Longest cue, never reads as success. */
  error: {
    wave: "triangle",
    notes: [
      { at: 0, freq: 233.08, len: 0.14, peak: 0.018 },
      { at: 0.13, freq: 155.56, len: 0.22, peak: 0.016 },
    ],
  },

  /** Permission required: alternating three-note nudge. */
  permission: {
    wave: "triangle",
    notes: [
      { at: 0, freq: 659.25, len: 0.08, peak: 0.013 },
      { at: 0.1, freq: 493.88, len: 0.08, peak: 0.012 },
      { at: 0.2, freq: 659.25, len: 0.14, peak: 0.014 },
    ],
  },

  /** Stopped by the user: soft downward slide, no alarm. */
  stopped: {
    wave: "sine",
    notes: [{ at: 0, freq: 392, len: 0.19, peak: 0.012, glideTo: 261.63 }],
  },

  /** A background action succeeded: one short bright blip, no melody. */
  success: {
    wave: "sine",
    notes: [{ at: 0, freq: 783.99, len: 0.1, peak: 0.011 }],
  },

  /** Search started: quick upward sweep. */
  search: {
    wave: "sine",
    notes: [{ at: 0, freq: 440, len: 0.13, peak: 0.01, glideTo: 698.46 }],
  },

  /** Panel toggled: the quietest, shortest click in the palette. */
  panel: {
    wave: "sine",
    notes: [{ at: 0, freq: 330, len: 0.055, peak: 0.007 }],
  },

  /** Settings opened: descending pair, distinctly heavier than `panel`. */
  settings: {
    wave: "triangle",
    notes: [
      { at: 0, freq: 466.16, len: 0.075, peak: 0.009 },
      { at: 0.075, freq: 349.23, len: 0.12, peak: 0.01 },
    ],
  },

  /** Model switched: neutral double tick on one pitch. */
  model: {
    wave: "sine",
    notes: [
      { at: 0, freq: 523.25, len: 0.06, peak: 0.01 },
      { at: 0.085, freq: 523.25, len: 0.1, peak: 0.011 },
    ],
  },
};

const STORAGE_KEY = "axiom.soundEnabled";
/** Minimum gap between cues; also the throttle for overlapping actions. */
const THROTTLE_MS = 160;
/** Exponential ramps cannot reach zero, so silence is this epsilon. */
const SILENCE = 0.0001;
const ATTACK = 0.008;
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

/** Play a short, deliberately quiet cue after a user-initiated action. */
export function playUiSound(kind: UiSound): void {
  if (!isSoundEnabled()) return;
  // Async events must not initialize audio or bypass the user gesture gate.
  const ctx = audioContext;
  if (!ctx || ctx.state !== "running" || performance.now() - lastPlayed < THROTTLE_MS) return;
  lastPlayed = performance.now();
  try {
    const recipe = RECIPES[kind] ?? RECIPES.panel;
    const now = ctx.currentTime;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = recipe.wave;

    gain.gain.setValueAtTime(SILENCE, now);
    let end = 0;
    for (const note of recipe.notes) {
      const start = now + note.at;
      const stop = start + note.len;
      const peak = Math.min(note.peak, MAX_PEAK);

      oscillator.frequency.setValueAtTime(note.freq, start);
      if (note.glideTo) oscillator.frequency.exponentialRampToValueAtTime(note.glideTo, stop);

      // The envelope is re-articulated per note, so a multi-note figure reads
      // as separate notes instead of one smeared tone.
      gain.gain.setValueAtTime(SILENCE, start);
      gain.gain.exponentialRampToValueAtTime(peak, start + Math.min(ATTACK, note.len / 2));
      gain.gain.exponentialRampToValueAtTime(SILENCE, stop);
      end = Math.max(end, note.at + note.len);
    }

    oscillator.connect(gain);
    gain.connect(ctx.destination);
    voices.add(oscillator);
    oscillator.onended = () => {
      voices.delete(oscillator);
      oscillator.disconnect();
      gain.disconnect();
    };
    oscillator.start(now);
    // Every cue has a scheduled end: a stuck voice would be a real bug.
    oscillator.stop(now + end + 0.01);
  } catch {
    // Audio is optional and must never interrupt a UI action.
  }
}