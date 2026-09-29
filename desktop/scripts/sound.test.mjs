import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = ts.transpileModule(readFileSync(new URL("../src/lib/sound.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021 },
}).outputText;

function fixture(saved = null, blockedStorage = false) {
  const events = new Map();
  const stats = { contexts: 0, starts: 0, stops: 0, scheduledStops: 0, peaks: [], disconnected: 0 };
  // Per-cue capture: waveform, the scheduled pitches and the note count, so a
  // test can assert that two cues are genuinely different sounds.
  const cues = [];
  let clock = 1000;
  const param = { setValueAtTime() {}, exponentialRampToValueAtTime() {} };
  class AudioContext {
    state = "running";
    currentTime = 1;
    destination = {};
    constructor() { stats.contexts++; }
    resume() { this.state = "running"; return Promise.resolve(); }
    createOscillator() {
      const cue = { type: null, freqs: [], glides: 0, attacks: 0, end: null };
      cues.push(cue);
      return {
        set type(value) { cue.type = value; },
        get type() { return cue.type; },
        frequency: {
          setValueAtTime(value) { cue.freqs.push(value); },
          exponentialRampToValueAtTime() { cue.glides++; },
        },
        connect() {}, disconnect() { stats.disconnected++; },
        start() { stats.starts++; },
        stop(time) {
          if (time === undefined) stats.stops++;
          else { stats.scheduledStops++; cue.end = time; }
        },
        onended: null,
      };
    }
    createGain() {
      const cue = cues[cues.length - 1];
      return {
        gain: {
          setValueAtTime() {},
          exponentialRampToValueAtTime(v) {
            stats.peaks.push(v);
            // A ramp up to an audible level marks the attack of one note.
            if (v > 0.0001 && cue) cue.attacks++;
          },
        },
        connect() {}, disconnect() {},
      };
    }
  }
  const sandbox = {
    exports: {}, AudioContext,
    performance: { now: () => clock },
    localStorage: {
      getItem() { if (blockedStorage) throw Error("blocked"); return saved; },
      setItem(_k, v) { if (blockedStorage) throw Error("blocked"); saved = v; },
    },
    window: { addEventListener(k, fn) { events.set(k, fn); }, removeEventListener(k) { events.delete(k); } },
  };
  vm.runInNewContext(source, sandbox);
  return { api: sandbox.exports, stats, events, cues, tick: () => { clock += 200; }, gesture: (trusted = true) => events.get("pointerdown")?.({ isTrusted: trusted }) };
}

/** Enable sound, pass the gesture gate and return a ready fixture. */
function armed() {
  const f = fixture("true");
  f.api.installSoundActivation();
  f.gesture();
  return f;
}

/** Play one cue in isolation (the throttle only allows one per window). */
function playOne(f, kind) {
  f.tick();
  f.api.playUiSound(kind);
  return f.cues[f.cues.length - 1];
}

test("silent by default, including trusted gestures and async notifications", () => {
  const f = fixture();
  f.api.installSoundActivation();
  f.gesture();
  f.api.playUiSound("complete");
  assert.equal(f.api.isSoundEnabled(), false);
  assert.equal(f.stats.contexts, 0);
});
test("persisted opt-in still requires a real gesture; no typing cue; bounded envelope", () => {
  const f = fixture("true");
  const dispose = f.api.installSoundActivation();
  f.api.playUiSound("settings");
  f.gesture(false);
  assert.equal(f.stats.contexts, 0);
  f.gesture();
  assert.equal(f.stats.starts, 0);
  f.api.playUiSound("settings");
  f.api.playUiSound("success");
  assert.equal(f.stats.starts, 1, "overlapping cues are throttled");
  assert.ok(Math.max(...f.stats.peaks) <= 0.018);
  f.tick();
  f.api.playUiSound("complete");
  assert.equal(f.stats.starts, 2);
  assert.equal(f.stats.scheduledStops, 2, "every cue has a scheduled end");
  f.api.setSoundEnabled(false);
  f.tick();
  f.api.playUiSound("error");
  assert.equal(f.stats.starts, 2);
  assert.equal(f.stats.stops, 2, "mute stops active voices as well as future cues");
  dispose();
  assert.equal(f.events.size, 0);
});
test("blocked storage falls back to a working session-only setting", () => {
  const f = fixture(null, true);
  f.api.setSoundEnabled(true);
  f.api.installSoundActivation();
  f.gesture();
  f.api.playUiSound("search");
  assert.equal(f.stats.starts, 1);
});

test("every cue is an audibly distinct sound, not the same blip retuned", () => {
  const f = armed();
  const kinds = [
    "complete", "error", "permission", "stopped",
    "success", "search", "panel", "settings", "model",
  ];
  const signatures = new Set();
  for (const kind of kinds) {
    const cue = playOne(f, kind);
    assert.ok(cue, `${kind} produced no cue`);
    assert.ok(cue.freqs.length >= 1, `${kind} scheduled no pitch`);
    assert.ok(cue.type === "sine" || cue.type === "triangle", `${kind} has an odd waveform`);
    // Waveform + the exact pitch sequence is the identity of a cue.
    signatures.add(`${cue.type}:${cue.freqs.join(",")}`);
  }
  assert.equal(signatures.size, kinds.length, "two cues would sound identical");
});

test("terminal states are told apart: finished rises, error is low, stop glides down", () => {
  const f = armed();

  const done = playOne(f, "complete");
  assert.equal(done.attacks, 2, "the answer chime is a two-note figure");
  assert.ok(done.freqs[1] > done.freqs[0], "finished rises in pitch");

  const failed = playOne(f, "error");
  assert.ok(failed.freqs[1] < failed.freqs[0], "error falls in pitch");
  assert.ok(
    Math.max(...failed.freqs) < Math.min(...done.freqs),
    "error sits below the success chime across its whole range",
  );
  assert.equal(failed.type, "triangle", "error uses the buzzier waveform");

  const stopped = playOne(f, "stopped");
  assert.equal(stopped.attacks, 1, "a user stop is a single note");
  assert.equal(stopped.glides, 1, "a user stop glides instead of stepping");

  const ask = playOne(f, "permission");
  assert.equal(ask.attacks, 3, "a permission prompt is a three-note nudge");
  assert.ok(ask.freqs[1] < ask.freqs[0] && ask.freqs[2] > ask.freqs[1], "the nudge alternates");
});

test("longer cues still end on schedule and stay within the volume ceiling", () => {
  const f = armed();
  for (const kind of ["complete", "error", "permission", "stopped", "panel"]) {
    const cue = playOne(f, kind);
    assert.ok(cue.end !== null, `${kind} has no scheduled end`);
    // currentTime is 1 in the fixture; the cue must end after it and stay short.
    assert.ok(cue.end > 1 && cue.end < 1.6, `${kind} ends at an implausible time`);
  }
  assert.ok(Math.max(...f.stats.peaks) <= 0.018, "a cue exceeded the volume ceiling");
  assert.equal(f.stats.starts, f.stats.scheduledStops, "every started voice is stopped");
});

test("an unknown cue degrades to the quietest click instead of throwing", () => {
  const f = armed();
  const fallback = playOne(f, "definitely-not-a-cue");
  const panel = playOne(f, "panel");
  assert.deepEqual(fallback.freqs, panel.freqs);
});