"""Splash screen — animated black hole, gradient logo and the *real* startup.

Every step reports what actually happened (Ollama reachable or not, how many
models were found, which model was selected). The progress bar is eased
(lerp) towards the real progress so it glides instead of jumping, and the
screen stays up for a short minimum time so the animation can be seen.
Nothing fakes success: a step is spinning only while its real probe runs.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Static

from axiom.shared import formatting as fmt
from axiom.shared import logo as logo_art
from axiom.shared import theme

#: Minimum splash time so the boot animation is actually visible.
MIN_SPLASH_SECONDS = 2.4
#: Extra pause on a successful start so the user sees "ready" at 100 %.
READY_HOLD_SECONDS = 0.9
#: Kept for compatibility (old vertical float of the logo).
BOUNCE = (0, 0, 1, 1, 0, 0, -1, -1)
#: Animation frame interval (≈15 fps — smooth but cheap in a terminal).
FRAME = 1 / 15
#: Black-hole canvas size in cells and the minimum terminal width to show it.
HOLE_W, HOLE_H = 46, 19
HOLE_MIN_WIDTH = 112
BAR_WIDTH = 38


@dataclass
class StartupStep:
    """One real startup probe."""

    title: str
    run: Callable[[], Awaitable[tuple[bool, str]]]


# --------------------------------------------------------------------- colour


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def _hex(c: tuple[int, int, int]) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


#: Fire ramp of the accretion disk: ember → red → orange → white-hot.
_RAMP = ((28, 4, 6), (110, 14, 20), (214, 52, 38), (255, 128, 64), (255, 214, 160), (255, 246, 228))


def _fire(t: float) -> str:
    t = max(0.0, min(0.999, t)) * (len(_RAMP) - 1)
    i = int(t)
    return _hex(_mix(_RAMP[i], _RAMP[i + 1], t - i))


_GLYPHS = " ·:░░▒▒▓▓██"


# ----------------------------------------------------------------- black hole


class BlackHole(Static):
    """ASCII black hole: rotating turbulent disk, lensed arc, photon ring."""

    def __init__(self) -> None:
        super().__init__("", id="splash-hole", markup=False)
        rnd = random.Random(7)
        self._stars = [(rnd.randrange(HOLE_W), rnd.randrange(HOLE_H), rnd.random() * 6.28) for _ in range(26)]

    def render_frame(self, t: float) -> None:
        self.update(self.frame(t))

    @staticmethod
    def _cell(dx: float, dy: float, t: float) -> tuple[float, str | None]:
        """Intensity 0..1 (and optional fixed colour) of one cell."""
        # Screen space: cells are ~2× taller than wide → dy is pre-scaled.
        rs = math.hypot(dx, dy)
        shadow = 0.27
        # Disk plane (tilted ellipse).
        u, v = dx, dy / 0.30
        r = math.hypot(u, v)
        a = math.atan2(v, u)
        disk = 0.0
        if 0.36 < r < 1.0:
            spin = a - t * (1.6 / max(r, 0.45))
            swirl = 0.62 + 0.24 * math.sin(3 * spin + r * 9) + 0.14 * math.sin(7 * spin - r * 5 + 1.3)
            fall = (1 - (r - 0.36) / 0.64) ** 1.1
            doppler = 1.0 + 0.55 * (-u / max(r, 1e-3))
            disk = max(0.0, swirl * fall * doppler * 1.05)
        front = dy > 0  # lower half of the ellipse passes in front of the hole
        if rs < shadow and not (front and disk > 0):
            return 0.0, None
        # Lensed far side of the disk: an arc hugging the shadow from above.
        halo = 0.0
        if dy < 0.04:
            d = abs(rs - 0.36)
            halo = max(0.0, 1 - d / 0.09) * (0.7 + 0.25 * math.sin(a * 3 - t * 1.4)) * (1 if dy < 0 else 0.4)
        # Photon ring.
        ring = max(0.0, 1 - abs(rs - shadow - 0.018) / 0.03) * 0.95
        return min(1.0, max(disk, halo, ring)), None

    def frame(self, t: float) -> Text:
        text = Text(no_wrap=True, overflow="crop")
        cx, cy = (HOLE_W - 1) / 2, (HOLE_H - 1) / 2
        star_at = {(x, y): p for x, y, p in self._stars}
        for row in range(HOLE_H):
            run_style: str | None = None
            run = ""
            for col in range(HOLE_W):
                dx = (col - cx) / (HOLE_W / 2)
                dy = (row - cy) / (HOLE_H / 2) * 0.82
                level, _ = self._cell(dx, dy, t)
                if level <= 0.03:
                    ch, style = " ", ""
                    phase = star_at.get((col, row))
                    if phase is not None and math.hypot(dx, dy) > 0.5:
                        tw = 0.5 + 0.5 * math.sin(t * 2.2 + phase)
                        ch = "·" if tw < 0.7 else "+"
                        style = _hex(_mix((40, 40, 60), (210, 210, 235), tw))
                else:
                    ch = _GLYPHS[min(len(_GLYPHS) - 1, 1 + int(level * (len(_GLYPHS) - 1)))]
                    style = _fire(level)
                if style != run_style and run:
                    text.append(run, style=run_style or None)
                    run = ""
                run_style = style
                run += ch
            if run:
                text.append(run, style=run_style or None)
            if row < HOLE_H - 1:
                text.append("\n")
        return text


# ---------------------------------------------------------------- actions


class ActionOption(Static):
    """A minimal clickable/selectable action (Retry / Exit)."""

    class Pressed(Message):
        def __init__(self, label: str) -> None:
            self.label = label
            super().__init__()

    def __init__(self, label: str) -> None:
        super().__init__(label, classes="action", markup=False)
        self.label_text = label

    def on_click(self) -> None:
        self.post_message(self.Pressed(self.label_text))


# ----------------------------------------------------------------- screen


class SplashScreen(Screen):
    """Black hole, logo, real step list, eased progress, Retry/Exit on failure."""

    BINDINGS = [("left", "move(-1)", "Previous"), ("right", "move(1)", "Next")]

    def __init__(self, steps: list[StartupStep], *, animations: bool = True) -> None:
        super().__init__(id="splash-screen")
        self._steps = steps
        self._animations = animations
        self._frame = 0
        self._t0 = time.perf_counter()
        self._finished = False
        self._failed_reason: str | None = None
        self._selected = 0
        self._timer = None
        self._actions: list[ActionOption] = []
        self._active_line: Static | None = None
        self._active_title: str | None = None
        # Progress: real target vs. eased display value.
        self._done_steps = 0
        self._step_started = time.perf_counter()
        self._shown = 0.0
        self._skip = asyncio.Event()

    def compose(self) -> ComposeResult:
        with Horizontal(id="splash-body"):
            with Vertical(id="splash-column"):
                yield Static("", id="splash-logo", markup=False)
                yield Static(logo_art.LOGO_RULE, id="splash-rule", markup=False)
                yield Static(logo_art.SUBTITLE, id="splash-subtitle", markup=False)
                yield Vertical(id="splash-steps")
                yield Static("", id="splash-progress", markup=False)
                yield Static("", id="splash-message", markup=False)
                yield Horizontal(id="splash-actions")
            yield BlackHole()

    def on_mount(self) -> None:
        self._layout()
        self._draw_logo()
        self._draw_progress()
        if self._animations:
            self._timer = self.set_interval(FRAME, self._animate_splash)
            self.query_one(BlackHole).render_frame(0.0)
        else:
            self.query_one(BlackHole).render_frame(0.0)
        self.run_worker(self._run_steps, exclusive=True, name="startup")

    def on_resize(self, event: events.Resize) -> None:
        self._layout()
        self._draw_logo()

    def _layout(self) -> None:
        width = self.size.width or 80
        self.query_one(BlackHole).display = width >= HOLE_MIN_WIDTH

    # ---------------------------------------------------------------- animation

    def _elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def _target(self) -> float:
        total = max(1, len(self._steps))
        if self._finished and not self._failed_reason:
            return 1.0
        base = self._done_steps / total
        if self._active_title is None:
            return base
        # Creep inside the running step (asymptotic — never claims completion).
        running = time.perf_counter() - self._step_started
        return base + (1 / total) * 0.85 * (1 - math.exp(-running / 0.9))

    def _animate_splash(self) -> None:
        self._frame += 1
        target = self._target()
        self._shown += (target - self._shown) * 0.16
        if abs(target - self._shown) < 0.002:
            self._shown = target
        self._draw_logo()
        self._spin_active_step()
        self._draw_progress()
        hole = self.query_one(BlackHole)
        if hole.display:
            hole.render_frame(self._elapsed())

    def _spin_active_step(self) -> None:
        """Animate the glyph of the step that is currently running."""
        if self._active_line is None or self._active_title is None:
            return
        line = Text()
        line.append(fmt.spinner_frame(self._frame // 2), style="bold #ff8a5c")
        line.append(f"  {self._active_title}", style="#ececf0")
        dots = "." * (1 + (self._frame // 5) % 3)
        line.append(f" {dots:<3}", style="#6c6c78")
        self._active_line.update(line)

    def _draw_progress(self) -> None:
        shown = self._shown if self._animations else self._target()
        filled = shown * BAR_WIDTH
        full = int(filled)
        text = Text(no_wrap=True)
        sweep = (self._frame * 0.6) % (BAR_WIDTH + 12) - 6
        for i in range(BAR_WIDTH):
            if i < full:
                base = _mix((150, 20, 34), (255, 140, 80), i / max(1, BAR_WIDTH - 1))
                glow = max(0.0, 1 - abs(i - sweep) / 4) if self._animations and not self._failed_reason else 0
                text.append("━", style=_hex(_mix(base, (255, 236, 210), glow * 0.7)))
            elif i == full and shown < 1:
                text.append("╸", style="#ff9a6a" if filled - full > 0.5 else "#a33a2c")
            else:
                text.append("─", style="#26262c")
        pct = int(round(shown * 100))
        color = "#e5534b" if self._failed_reason else "#ffffff"
        text.append(f"  {pct:>3}%", style=f"bold {color}")
        self.query_one("#splash-progress", Static).update(text)

    # -------------------------------------------------------------- step runner

    async def _run_steps(self) -> None:
        started = time.perf_counter()
        self._t0 = started if self._frame == 0 else self._t0
        container = self.query_one("#splash-steps", Vertical)
        ok_overall = True
        for step in self._steps:
            line = Static(f"{fmt.spinner_frame(0)}  {step.title}", classes="splash-step", markup=False)
            self._active_line = line
            self._active_title = step.title
            self._step_started = time.perf_counter()
            await container.mount(line)
            try:
                ok, note = await step.run()
            except Exception as exc:
                ok, note = False, f"{type(exc).__name__}: {exc}"
            self._active_line = None
            self._active_title = None
            glyph = theme.TICK if ok else theme.CROSS
            done = Text()
            done.append(glyph, style="bold #56d364" if ok else "bold #e5534b")
            done.append(f"  {step.title}", style="#b9b9b9" if ok else "#e5534b")
            done.append(f"  {note}", style="#6c6c78" if ok else "#c0504a")
            line.update(done)
            line.set_class(not ok, "failed")
            if not ok:
                ok_overall = False
                self._failed_reason = f"{step.title}: {note}"
                break
            self._done_steps += 1
        if self._animations:
            remaining = MIN_SPLASH_SECONDS - (time.perf_counter() - started)
            if remaining > 0:
                await self._sleep_or_skip(remaining)
        self._finished = True
        if ok_overall:
            message = self.query_one("#splash-message", Static)
            message.update("Ready · starting AXIOM …   (any key to skip)" if self._animations else "Starting AXIOM …")
            message.set_class(True, "ready")
            if self._animations:
                await self._sleep_or_skip(READY_HOLD_SECONDS)
            self._stop_timer()
            # The workspace lives in the app; the splash only asks for it.
            start = getattr(self.app, "start_workspace", None)
            if callable(start):
                start()
        else:
            self._draw_progress()
            self._show_failure()

    async def _sleep_or_skip(self, seconds: float) -> None:
        self._skip.clear()
        try:
            await asyncio.wait_for(self._skip.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _show_failure(self) -> None:
        message = self.query_one("#splash-message", Static)
        message.update(self._failed_reason or "Startup failed.")
        message.set_class(False, "ready")
        message.set_class(True, "failed")
        actions = self.query_one("#splash-actions", Horizontal)
        self._actions = [ActionOption("Retry"), ActionOption("Exit")]
        self._selected = 0
        actions.mount_all(self._actions)
        self._apply_selection()

    def _apply_selection(self) -> None:
        for index, option in enumerate(self._actions):
            option.set_class(index == self._selected, "selected")

    # -------------------------------------------------------------------- events

    def on_key(self, event: events.Key) -> None:
        if not self._actions:
            # Any key skips the decorative minimum display time.
            self._skip.set()
            return
        if event.key == "left":
            event.stop()
            self._move(-1)
        elif event.key == "right":
            event.stop()
            self._move(1)
        elif event.key == "enter":
            event.stop()
            self._activate(self._actions[self._selected].label_text)

    def _move(self, delta: int) -> None:
        self._selected = (self._selected + delta) % len(self._actions)
        self._apply_selection()

    def on_action_option_pressed(self, event: ActionOption.Pressed) -> None:
        event.stop()
        self._activate(event.label)

    def _activate(self, label: str) -> None:
        if label == "Retry":
            self._retry()
        else:
            self.app.exit()

    def _retry(self) -> None:
        for option in self._actions:
            option.remove()
        self._actions = []
        for child in list(self.query_one("#splash-steps", Vertical).children):
            child.remove()
        message = self.query_one("#splash-message", Static)
        message.update("")
        message.set_class(False, "failed")
        self._finished = False
        self._failed_reason = None
        self._done_steps = 0
        self._shown = 0.0
        if self._animations and self._timer is None:
            self._timer = self.set_interval(FRAME, self._animate_splash)
        self.run_worker(self._run_steps, exclusive=True, name="startup-retry")

    def _draw_logo(self) -> None:
        width = self.size.width or 80
        column = width - (HOLE_W + 4 if width >= HOLE_MIN_WIDTH else 0)
        lines = logo_art.logo_lines(column)
        span = max(len(line) for line in lines)
        sweep = (self._frame * 0.9) % (span + 30) - 15 if self._animations else -100
        text = Text(no_wrap=True)
        for row, line in enumerate(lines):
            padded = f"{line:<{span}}"
            for col, ch in enumerate(padded):
                if ch == " ":
                    text.append(" ")
                    continue
                base = _mix((255, 255, 255), (255, 120, 90), col / max(1, span - 1) * 0.55)
                if ch in "╗╝╔╚═║░▄▀":
                    base = _mix(base, (120, 30, 40), 0.55)
                glow = max(0.0, 1 - abs(col - sweep - row * 0.8) / 5)
                text.append(ch, style=f"bold {_hex(_mix(base, (255, 214, 160), glow))}")
            if row < len(lines) - 1:
                text.append("\n")
        self.query_one("#splash-logo", Static).update(text)
