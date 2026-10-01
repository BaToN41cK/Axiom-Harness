"""``/account`` — sign in / register, balance, AXIOM PRO subscription, top-up.

Every value on this screen comes from the AXIOM payment backend (the same one
the desktop app uses). Payments are completed on the YooMoney page in the
browser; the screen then polls the order until the signed server notification
confirms it — a browser redirect alone never changes the balance.
"""

from __future__ import annotations

import time
import webbrowser
from datetime import datetime, timezone
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from axiom.core.account import (
    PRO_DAYS,
    PRO_PRICE_AXIOM_USD_MINOR,
    PRO_PRICE_RUB_MINOR,
    AccountClient,
    AccountError,
    axiom_usd,
    parse_amount,
    payment_message,
    rub_to_axiom_usd_minor,
    rubles,
)

ACCENT = "#ff8a5c"
MUTED = "#6c6c78"
GOOD = "#56d364"
GOLD = "#e3b341"
BAD = "#f47067"
PRESETS = (100, 250, 500, 1000)
#: Facts guaranteed by payment-backend (no marketing promises).
PRO_FEATURES = (
    "30 days from the moment of payment",
    "Renewing early adds 30 days to the current end date",
    "Pay by card / YooMoney wallet, or with AXIOM credits",
    "Same account in the desktop app and in the terminal",
)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fmt_date(value: str | None) -> str:
    parsed = _parse_time(value)
    return parsed.astimezone().strftime("%d.%m.%Y %H:%M") if parsed else "—"


def _bar(fraction: float, width: int, color: str) -> Text:
    fraction = max(0.0, min(1.0, fraction))
    full = int(fraction * width)
    text = Text()
    text.append("█" * full, style=color)
    text.append("░" * (width - full), style="#2a2a32")
    return text


class AccountScreen(ModalScreen[dict | None]):
    """Account, balance and AXIOM PRO."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("ctrl+r", "reload", "Refresh", show=False),
    ]

    def __init__(self, *, view: str = "auto", amount: str | None = None, client: AccountClient | None = None) -> None:
        super().__init__(id="account-screen")
        self.client = client or AccountClient()
        self.view = view  # auto | register | pro | topup
        self.mode = "loading"  # loading | auth | oauth | account
        self.auth_tab = "register" if view == "register" else "login"
        self.account: dict[str, Any] | None = self.client.store.cached_account()
        self.providers: dict[str, bool] | None = None
        self.payment: dict[str, Any] | None = None
        self.amount = amount or "300"
        self.busy = False
        self.error = ""
        self.info = ""
        self._oauth: dict[str, Any] | None = None
        self._cancel_oauth = False
        self._poll_timer = None
        self._oauth_timer = None

    # ================================================================ layout

    def compose(self) -> ComposeResult:
        frame = Vertical(classes="panel", id="account-frame")
        frame.border_title = "AXIOM ACCOUNT"
        frame.border_subtitle = "Tab move · Enter confirm · Ctrl+R refresh · Esc close"
        with frame:
            with VerticalScroll(id="account-body"):
                if self.mode == "loading":
                    yield Static(Text("\n  Connecting to the account server…\n  (it may take up to a minute to wake up)", style=MUTED), classes="acc-note")
                elif self.mode == "auth":
                    yield from self._compose_auth()
                elif self.mode == "oauth":
                    yield from self._compose_oauth()
                else:
                    yield from self._compose_account()
            yield Static(self._status_text(), id="account-status")

    def _status_text(self) -> Text:
        if self.error:
            return Text(f" ✕ {self.error}", style=BAD)
        if self.busy:
            return Text(" ◌ Working…", style=ACCENT)
        if self.info:
            return Text(f" ✓ {self.info}", style=GOOD)
        return Text("")

    # -------------------------------------------------------------- signed out

    def _compose_auth(self) -> ComposeResult:
        hero = Text()
        hero.append("\n  ◆ AXIOM", style=f"bold {ACCENT}")
        hero.append("   one account for the desktop app and the terminal\n", style=MUTED)
        yield Static(hero, classes="acc-hero")
        with Horizontal(classes="acc-tabs"):
            yield Button("Sign in", id="tab-login", classes="acc-tab" + (" -active" if self.auth_tab == "login" else ""))
            yield Button("Create account", id="tab-register", classes="acc-tab" + (" -active" if self.auth_tab == "register" else ""))
        yield Static(Text("  Username", style=MUTED), classes="acc-label")
        yield Input(placeholder="3–32 characters: letters, digits, _ . -", id="acc-user")
        yield Static(Text("  Password", style=MUTED), classes="acc-label")
        yield Input(placeholder="At least 8 characters", password=True, id="acc-pass")
        if self.auth_tab == "register":
            yield Static(Text("  Repeat password", style=MUTED), classes="acc-label")
            yield Input(placeholder="Same password again", password=True, id="acc-pass2")
            yield Static("", id="acc-strength")
        yield Button("Create account" if self.auth_tab == "register" else "Sign in", id="acc-submit", variant="primary", classes="acc-wide")
        yield Static(Text("\n  ─────────────  or continue with  ─────────────", style=MUTED), classes="acc-divider")
        with Horizontal(classes="acc-oauth"):
            for provider, label in (("github", "  GitHub"), ("google", "G  Google")):
                state = None if self.providers is None else self.providers.get(provider)
                suffix = " · checking" if state is None else ("" if state else " · not configured")
                yield Button(label + suffix, id=f"oauth-{provider}", classes="acc-oauth-btn", disabled=state is False)
        yield Static(Text("\n  Sign-in opens your browser; this screen finishes automatically after you confirm.", style=MUTED), classes="acc-note")

    def _compose_oauth(self) -> ComposeResult:
        assert self._oauth is not None
        name = "GitHub" if self._oauth["provider"] == "github" else "Google"
        yield Static(Text(f"\n  Signing in with {name}\n", style="bold #ececf0"), classes="acc-hero")
        yield Static(self._oauth_steps(), id="acc-oauth-steps")
        url = self._oauth.get("url") or ""
        yield Static(Text.assemble(("\n  Link  ", MUTED), (url, "#79c0ff underline")), classes="acc-note")
        with Horizontal(classes="acc-row"):
            yield Button("Open browser again", id="oauth-reopen")
            yield Button("Cancel", id="oauth-cancel", variant="error")

    def _oauth_steps(self) -> Text:
        stage = (self._oauth or {}).get("stage", "starting")
        order = ["starting", "browser", "waiting", "redeeming"]
        labels = {
            "starting": "Creating a secure sign-in link",
            "browser": "Opening the browser",
            "waiting": "Waiting for confirmation in the browser",
            "redeeming": "Creating the session",
        }
        current = order.index(stage) if stage in order else 0
        spinner = "◐◓◑◒"[int(time.time() * 6) % 4]
        text = Text()
        for index, key in enumerate(order):
            if index < current:
                text.append("  ✓ ", style=GOOD)
                text.append(labels[key] + "\n", style="#9a9aa6")
            elif index == current:
                text.append(f"  {spinner} ", style=ACCENT)
                text.append(labels[key] + "\n", style="bold #ececf0")
            else:
                text.append("  ○ ", style="#3a3a44")
                text.append(labels[key] + "\n", style=MUTED)
        started = (self._oauth or {}).get("started", time.time())
        left = max(0, 600 - int(time.time() - started))
        text.append(f"\n  Link valid for {left // 60}:{left % 60:02d}", style=MUTED)
        return text

    # --------------------------------------------------------------- signed in

    def _compose_account(self) -> ComposeResult:
        account = self.account or {}
        yield Static(self._card(account), id="acc-card")
        # ---- PRO
        yield Static(self._pro_block(account), id="acc-pro")
        with Horizontal(classes="acc-row"):
            yield Button(
                ("Extend" if account.get("pro_active") else "Subscribe") + f" · {rubles(PRO_PRICE_RUB_MINOR)}",
                id="pro-card", variant="primary",
                disabled=self.busy or self._pending() or not account.get("payments_available", True),
            )
            yield Button(
                f"Pay {axiom_usd(PRO_PRICE_AXIOM_USD_MINOR)} from balance", id="pro-balance",
                disabled=self.busy or self._pending() or int(account.get("balance_minor") or 0) < PRO_PRICE_AXIOM_USD_MINOR,
            )
        # ---- top-up
        yield Static(Text.assemble(("\n  TOP UP BALANCE", f"bold {MUTED}")), classes="acc-section")
        with Horizontal(classes="acc-row acc-presets"):
            for value in PRESETS:
                selected = parse_amount(self.amount) == value * 100
                yield Button(f"{value} ₽", id=f"preset-{value}", classes="acc-preset" + (" -active" if selected else ""))
        with Horizontal(classes="acc-row"):
            yield Input(self.amount, placeholder="Amount, ₽ (100 – 100 000)", id="acc-amount", restrict=r"[0-9.,]*")
            yield Button("Top up", id="topup", variant="primary", disabled=self.busy or self._pending())
        yield Static(self._topup_hint(), id="acc-topup-hint")
        if account.get("payments_message"):
            yield Static(Text(f"  {account['payments_message']}", style=GOLD), classes="acc-note")
        # ---- payment in progress / result
        if self.payment:
            yield Static(self._payment_block(), id="acc-payment")
            if self._pending():
                with Horizontal(classes="acc-row"):
                    yield Button("Open payment page", id="pay-open", variant="primary")
                    yield Button("Check now", id="pay-check")
        with Horizontal(classes="acc-row acc-footer"):
            yield Button("Refresh", id="acc-refresh")
            yield Button("Sign out", id="acc-logout", variant="error")

    def _card(self, account: dict[str, Any]) -> Text:
        name = str(account.get("username") or "—")
        initials = (name[:2] or "AX").upper()
        pro = bool(account.get("pro_active"))
        text = Text()
        text.append("\n  ")
        text.append(f" {initials} ", style=f"bold #0b0b0f on {GOLD if pro else ACCENT}")
        text.append(f"  {name}", style="bold #ececf0")
        text.append("   ★ PRO" if pro else "   FREE", style=f"bold {GOLD}" if pro else f"bold {MUTED}")
        text.append("\n\n  BALANCE\n", style=f"bold {MUTED}")
        text.append(f"  {axiom_usd(account.get('balance_minor'))}", style="bold #ffffff")
        text.append("  AXIOM USD credits", style=MUTED)
        text.append("   100 ₽ = $1.00\n", style="#4a4a54")
        return text

    def _pro_block(self, account: dict[str, Any]) -> Text:
        text = Text()
        text.append("\n  AXIOM PRO", style=f"bold {GOLD}")
        text.append(f"   {rubles(PRO_PRICE_RUB_MINOR)} / {PRO_DAYS} days  or  {axiom_usd(PRO_PRICE_AXIOM_USD_MINOR)} of credits\n", style=MUTED)
        expires = _parse_time(account.get("pro_expires_at"))
        if account.get("pro_active") and expires:
            left = (expires - datetime.now(timezone.utc)).total_seconds() / 86400
            text.append("  ")
            text.append_text(_bar(left / PRO_DAYS, 30, GOLD))
            text.append(f"  {max(0, int(left))} days left · until {_fmt_date(account.get('pro_expires_at'))}\n", style="#ececf0")
        else:
            text.append("  Not active — subscription switches on automatically after payment.\n", style="#9a9aa6")
        for feature in PRO_FEATURES:
            text.append("  ✓ ", style=GOOD)
            text.append(feature + "\n", style="#c8c8d0")
        return text

    def _topup_hint(self) -> Text:
        minor = parse_amount(self.amount)
        if minor is None:
            return Text("  Enter 100 – 100 000 ₽ (up to 2 decimals).", style=BAD)
        return Text.assemble(
            ("  You pay ", MUTED), (rubles(minor), "bold #ececf0"),
            ("  →  you get ", MUTED), (axiom_usd(rub_to_axiom_usd_minor(minor)), f"bold {GOOD}"),
            (" AXIOM USD credits", MUTED),
        )

    def _payment_block(self) -> Text:
        payment = self.payment or {}
        status = payment.get("status")
        color = {"paid": GOOD, "failed": BAD, "expired": BAD}.get(status or "", ACCENT)
        glyph = {"paid": "✓", "failed": "✕", "expired": "✕"}.get(status or "", "◐◓◑◒"[int(time.time() * 4) % 4])
        what = "AXIOM PRO" if payment.get("type") == "pro" else "Top-up"
        text = Text("\n")
        text.append(f"  {glyph} ", style=f"bold {color}")
        text.append(payment_message(payment), style=f"bold {color}")
        text.append(f"   {what} · {rubles(payment.get('amount_minor'))}\n", style=MUTED)
        steps = ["Order created", "Paid on YooMoney", "Confirmed by server"]
        reached = 3 if status == "paid" else 1
        for index, step in enumerate(steps):
            mark, style = ("●", GOOD) if index < reached else ("○", "#3a3a44")
            text.append(f"  {mark} {step}", style=style if index < reached else MUTED)
            text.append("  ─ " if index < 2 else "\n", style="#3a3a44")
        if status == "pending":
            if payment.get("payment_url"):
                text.append("  ", style="")
                text.append(str(payment["payment_url"]), style="#79c0ff underline")
                text.append("\n")
            if payment.get("expires_at"):
                text.append(f"  Order valid until {_fmt_date(payment.get('expires_at'))}\n", style=MUTED)
            text.append("  The balance changes only after YooMoney's signed notification reaches the server.\n", style="#4a4a54")
        elif status == "paid" and payment.get("type") != "pro":
            credited = payment.get("credited_axiom_usd_minor")
            text.append(f"  Credited {axiom_usd(credited)} AXIOM USD credits\n", style=GOOD)
        return text

    def _pending(self) -> bool:
        return bool(self.payment and self.payment.get("status") == "pending")

    # ============================================================ lifecycle

    async def on_mount(self) -> None:
        if self.client.store.token:
            await self._load_account(initial=True)
        else:
            await self._show_auth()

    async def _show_auth(self) -> None:
        self.mode = "auth"
        self.account = None
        await self.recompose()
        self._focus("#acc-user")
        self.run_worker(self._load_providers(), group="providers", exclusive=True)

    async def _load_providers(self) -> None:
        for delay in (0, 3, 8, 15):
            if delay:
                import asyncio

                await asyncio.sleep(delay)
            try:
                self.providers = await self.client.providers()
                break
            except AccountError:
                continue
        else:
            self.providers = {"github": True, "google": True}  # unknown → let the server decide
        if self.mode == "auth":
            await self._recompose_keep()

    async def _load_account(self, *, initial: bool = False) -> None:
        self.busy, self.error = True, ""
        if not initial:
            self._set_status()
        try:
            self.account = await self.client.me()
            if self.payment is None:
                latest = self.account.get("latest_payment")
                # Resume an unfinished payment; old results are not re-shown.
                if isinstance(latest, dict) and latest.get("status") == "pending":
                    self.payment = latest
            self.mode = "account"
        except AccountError as exc:
            if not self.client.store.token:
                self.busy = False
                await self._show_auth()
                self.error = str(exc)
                self._set_status()
                return
            self.error = str(exc)
            self.mode = "account" if self.account else "auth"
        self.busy = False
        await self.recompose()
        self._after_account()

    def _after_account(self) -> None:
        if self.mode != "account":
            return
        if self._pending():
            self._start_polling()
        if self.view == "topup":
            self._focus("#acc-amount")
        elif self.view == "pro":
            self._focus("#pro-card")
        self.view = "auto"

    def _focus(self, selector: str) -> None:
        try:
            self.query_one(selector).focus()
        except Exception:
            pass

    def _set_status(self) -> None:
        try:
            self.query_one("#account-status", Static).update(self._status_text())
        except Exception:
            pass

    async def _recompose_keep(self) -> None:
        """Recompose but keep what the user already typed."""
        values = {}
        for widget in self.query(Input):
            if widget.id:
                values[widget.id] = widget.value
        focused = self.focused.id if self.focused is not None else None
        await self.recompose()
        for key, value in values.items():
            try:
                self.query_one(f"#{key}", Input).value = value
            except Exception:
                pass
        if focused:
            self._focus(f"#{focused}")

    def action_close(self) -> None:
        self._cancel_oauth = True
        self.dismiss(self.client.store.cached_account())

    async def action_reload(self) -> None:
        if self.mode == "account":
            await self._load_account()

    # ============================================================== auth flow

    @on(Button.Pressed, "#tab-login")
    async def _tab_login(self) -> None:
        if self.auth_tab != "login":
            self.auth_tab, self.error = "login", ""
            await self._recompose_keep()

    @on(Button.Pressed, "#tab-register")
    async def _tab_register(self) -> None:
        if self.auth_tab != "register":
            self.auth_tab, self.error = "register", ""
            await self._recompose_keep()

    @on(Input.Changed, "#acc-pass")
    def _strength(self, event: Input.Changed) -> None:
        try:
            widget = self.query_one("#acc-strength", Static)
        except Exception:
            return
        pw = event.value
        score = sum([len(pw) >= 8, len(pw) >= 12, any(c.isdigit() for c in pw),
                     any(c.isupper() for c in pw) and any(c.islower() for c in pw),
                     any(not c.isalnum() for c in pw)])
        labels = ["too short", "weak", "fair", "good", "strong", "excellent"]
        colors = [BAD, BAD, GOLD, GOLD, GOOD, GOOD]
        text = Text("  ")
        text.append_text(_bar(score / 5, 20, colors[score]))
        text.append(f"  {labels[score]}", style=colors[score])
        widget.update(text if pw else "")

    @on(Input.Submitted, "#acc-user")
    def _user_enter(self) -> None:
        self._focus("#acc-pass")

    @on(Input.Submitted, "#acc-pass")
    @on(Input.Submitted, "#acc-pass2")
    @on(Button.Pressed, "#acc-submit")
    async def _submit(self) -> None:
        if self.busy:
            return
        username = self.query_one("#acc-user", Input).value.strip()
        password = self.query_one("#acc-pass", Input).value
        if self.auth_tab == "register":
            try:
                repeat = self.query_one("#acc-pass2", Input).value
            except Exception:
                repeat = password
            if self.focused is not None and self.focused.id == "acc-pass" and not repeat:
                self._focus("#acc-pass2")
                return
            if password != repeat:
                self.error = "Passwords do not match."
                self._set_status()
                return
        if len(username) < 3 or len(password) < 8:
            self.error = "Username: at least 3 characters; password: at least 8."
            self._set_status()
            return
        self.busy, self.error = True, ""
        self._set_status()
        try:
            if self.auth_tab == "register":
                self.account = await self.client.register(username, password)
                self.info = f"Account {username} created."
            else:
                self.account = await self.client.login(username, password)
                self.info = f"Signed in as {username}."
        except AccountError as exc:
            self.busy, self.error = False, str(exc)
            self._set_status()
            return
        self.busy = False
        self.mode = "account"
        await self.recompose()
        self._after_account()

    @on(Button.Pressed, "#oauth-github")
    async def _github(self) -> None:
        self.run_worker(self._oauth_flow("github"), group="oauth", exclusive=True)

    @on(Button.Pressed, "#oauth-google")
    async def _google(self) -> None:
        self.run_worker(self._oauth_flow("google"), group="oauth", exclusive=True)

    async def _oauth_flow(self, provider: str) -> None:
        self._cancel_oauth = False
        self.error = ""
        self._oauth = {"provider": provider, "stage": "starting", "started": time.time(), "url": ""}
        self.mode = "oauth"
        await self.recompose()
        self._oauth_timer = self.set_interval(0.25, self._tick_oauth)
        try:
            start = await self.client.oauth_start(provider)
            url = start["authorization_url"]
            self._oauth.update(url=url, stage="browser")
            await self.recompose()
            if url.startswith("https://"):
                webbrowser.open(url)
            self._oauth["stage"] = "waiting"
            self.account = await self.client.oauth_wait(start["poll_token"], cancelled=lambda: self._cancel_oauth)
            self._oauth["stage"] = "redeeming"
            self.info = f"Signed in as {self.account.get('username')}."
            self.mode = "account"
        except AccountError as exc:
            self.error = str(exc)
            self.mode = "auth"
        finally:
            if self._oauth_timer is not None:
                self._oauth_timer.stop()
                self._oauth_timer = None
        await self.recompose()
        self._after_account()

    def _tick_oauth(self) -> None:
        try:
            self.query_one("#acc-oauth-steps", Static).update(self._oauth_steps())
        except Exception:
            pass

    @on(Button.Pressed, "#oauth-reopen")
    def _reopen(self) -> None:
        url = (self._oauth or {}).get("url") or ""
        if url.startswith("https://"):
            webbrowser.open(url)

    @on(Button.Pressed, "#oauth-cancel")
    def _cancel(self) -> None:
        self._cancel_oauth = True

    # =========================================================== account flow

    @on(Button.Pressed, "#acc-refresh")
    async def _refresh(self) -> None:
        await self._load_account()

    @on(Button.Pressed, "#acc-logout")
    async def _logout(self) -> None:
        try:
            await self.client.logout()
        except AccountError:
            pass
        self.payment = None
        self.info = "Signed out."
        await self._show_auth()
        self._set_status()

    @on(Button.Pressed, "#pro-card")
    async def _pro_card(self) -> None:
        await self._create_payment(self.client.buy_pro())

    @on(Button.Pressed, "#pro-balance")
    async def _pro_balance(self) -> None:
        self.busy, self.error = True, ""
        self._set_status()
        try:
            self.account = await self.client.buy_pro_from_balance()
            self.info = f"AXIOM PRO active until {_fmt_date(self.account.get('pro_expires_at'))}."
        except AccountError as exc:
            self.error = str(exc)
        self.busy = False
        await self.recompose()

    @on(Button.Pressed, ".acc-preset")
    async def _preset(self, event: Button.Pressed) -> None:
        self.amount = str(event.button.id or "preset-300").split("-", 1)[1]
        await self.recompose()
        self._focus("#topup")

    @on(Input.Changed, "#acc-amount")
    def _amount_changed(self, event: Input.Changed) -> None:
        self.amount = event.value
        try:
            self.query_one("#acc-topup-hint", Static).update(self._topup_hint())
        except Exception:
            pass

    @on(Input.Submitted, "#acc-amount")
    @on(Button.Pressed, "#topup")
    async def _topup(self) -> None:
        minor = parse_amount(self.amount)
        if minor is None:
            self.error = "Enter an amount from 100 to 100 000 ₽."
            self._set_status()
            return
        await self._create_payment(self.client.topup(minor))

    async def _create_payment(self, request) -> None:
        if self.busy or self._pending():
            request.close()
            return
        self.busy, self.error, self.info = True, "", ""
        self._set_status()
        try:
            self.payment = await request
            url = self.payment.get("payment_url") or ""
            if url.startswith("https://"):
                webbrowser.open(url)
            self.info = "Payment page opened in the browser."
        except AccountError as exc:
            self.error = str(exc)
        self.busy = False
        await self.recompose()
        if self._pending():
            self._start_polling()

    @on(Button.Pressed, "#pay-open")
    def _pay_open(self) -> None:
        url = (self.payment or {}).get("payment_url") or ""
        if url.startswith("https://"):
            webbrowser.open(url)

    @on(Button.Pressed, "#pay-check")
    async def _pay_check(self) -> None:
        await self._poll_payment()

    def _start_polling(self) -> None:
        if self._poll_timer is None:
            self._poll_timer = self.set_interval(4.0, self._poll_payment)
            self.set_interval(0.25, self._tick_payment)

    def _tick_payment(self) -> None:
        if self._pending():
            try:
                self.query_one("#acc-payment", Static).update(self._payment_block())
            except Exception:
                pass

    async def _poll_payment(self) -> None:
        if not self.payment or not self._pending():
            return
        try:
            payment, account = await self.client.payment(str(self.payment["id"]))
        except AccountError as exc:
            self.error = str(exc)
            self._set_status()
            return
        changed = payment.get("status") != self.payment.get("status")
        self.payment, self.account = payment, account
        if changed:
            if payment.get("status") == "paid":
                self.info = payment_message(payment)
            if self._poll_timer is not None:
                self._poll_timer.stop()
                self._poll_timer = None
            await self.recompose()
