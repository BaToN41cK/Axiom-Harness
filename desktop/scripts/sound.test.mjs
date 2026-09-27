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
  let clock = 1000;
  const param = { setValueAtTime() {}, exponentialRampToValueAtTime() {} };
  class AudioContext {
    state = "running";
    currentTime = 1;
    destination = {};
    constructor() { stats.contexts++; }
    resume() { this.state = "running"; return Promise.resolve(); }
    createOscillator() {
      return { frequency: param, connect() {}, disconnect() { stats.disconnected++; },
        start() { stats.starts++; }, stop(time) { if (time === undefined) stats.stops++; else stats.scheduledStops++; }, onended: null };
    }
    createGain() {
      return { gain: { ...param, exponentialRampToValueAtTime(v) { stats.peaks.push(v); } }, connect() {}, disconnect() {} };
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
  return { api: sandbox.exports, stats, events, tick: () => { clock += 200; }, gesture: (trusted = true) => events.get("pointerdown")?.({ isTrusted: trusted }) };
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