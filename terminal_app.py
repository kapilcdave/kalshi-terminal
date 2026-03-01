"""
terminal_app.py — PolyTerminal
Bloomberg-style TUI for Kalshi + Polymarket prediction markets.
Run:  python terminal_app.py
"""
import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, Label, RichLog

from clients import KalshiClient, PolyClient

load_dotenv()
logging.basicConfig(level=logging.WARNING)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "stepfun/step-3.5-flash:free"

# ─── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: #0d0d0d;
    color: #c9d1d9;
}

/* ── Header ── */
#header {
    height: 1;
    dock: top;
    background: #161b22;
    padding: 0 1;
}
#title {
    color: #58a6ff;
    text-style: bold;
}
#k-status, #p-status {
    margin-left: 2;
    color: #3fb950;
}
#k-status.offline, #p-status.offline {
    color: #f85149;
}
#filter-label {
    color: #e3b341;
    text-style: bold;
    margin-left: 2;
}
#clock {
    width: 1fr;
    text-align: right;
    color: #8b949e;
}

/* ── Main panes ── */
#main {
    height: 1fr;
}
#kalshi-col, #poly-col {
    width: 1fr;
    height: 100%;
    border: solid #30363d;
}
.pane-title {
    height: 1;
    text-style: bold;
    background: #161b22;
    color: #58a6ff;
    padding: 0 1;
}
DataTable {
    height: 1fr;
    background: #0d0d0d;
}
DataTable > .datatable--header {
    background: #161b22;
    color: #8b949e;
    text-style: bold;
}
DataTable > .datatable--cursor {
    background: #1f3a5c;
    color: #c9d1d9;
}
DataTable > .datatable--odd-row {
    background: #111417;
}

/* ── Console pane ── */
#console-pane {
    width: 36;
    height: 100%;
    border: solid #30363d;
}
#console-log {
    height: 1fr;
    background: #0d0d0d;
    color: #c9d1d9;
}

/* ── Command bar ── */
#cmd-bar {
    height: 1;
    dock: bottom;
    background: #161b22;
    padding: 0 1;
}
#cmd-label {
    color: #58a6ff;
    text-style: bold;
    margin-right: 1;
}
#cmd-input {
    width: 1fr;
    background: transparent;
    border: none;
    color: #c9d1d9;
}
"""

# ─── App ──────────────────────────────────────────────────────────────────────

class PolyTerminal(App):
    CSS = CSS
    BINDINGS = [
        Binding("q",      "quit",            "Quit"),
        Binding("r",      "refresh",         "Refresh"),
        Binding("f1",     "filter('all')",   "All"),
        Binding("f2",     "filter('finance')","Finance"),
        Binding("f3",     "filter('politics')","Politics"),
        Binding("f4",     "filter('sports')", "Sports"),
        Binding("/",      "focus_cmd",       "Command"),
        Binding("escape", "blur_cmd",        "Dismiss"),
    ]

    def __init__(self):
        super().__init__()

        api_key = os.getenv("KALSHI_API_KEY", "")
        key_file = os.getenv("KALSHI_PRIVATE_KEY_FILE", "").strip('"').strip("'")
        pem = open(key_file).read() if key_file and os.path.exists(key_file) else ""

        self.kalshi: Optional[KalshiClient] = KalshiClient(api_key, pem) if api_key and pem else None
        self.poly = PolyClient()

        # {ticker: {title, price, volume}}
        self._k_data: dict = {}
        # {market_id: {question, price, volume}}
        self._p_data: dict = {}
        # token_ids subscribed to poly WS
        self._p_tokens: list[str] = []

        self._filter = "all"
        self._balance = ""

        # background tasks
        self._tasks: list[asyncio.Task] = []

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("◈ POLYTERMINAL", id="title"),
            Label("K: ◉ --", id="k-status"),
            Label("P: ◉ --", id="p-status"),
            Label("ALL", id="filter-label"),
            Label("", id="clock"),
            id="header",
        )
        with Horizontal(id="main"):
            with Vertical(id="kalshi-col"):
                yield Label("  KALSHI (USD)", classes="pane-title")
                yield DataTable(id="k-table", cursor_type="row")
            with Vertical(id="poly-col"):
                yield Label("  POLYMARKET (USDC)", classes="pane-title")
                yield DataTable(id="p-table", cursor_type="row")
            with Vertical(id="console-pane"):
                yield Label("  CLAWDBOT", classes="pane-title")
                yield RichLog(id="console-log", highlight=True, markup=True, auto_scroll=True)
        yield Horizontal(
            Label("⟩", id="cmd-label"),
            Input(placeholder="Ask Clawdbot or /help …", id="cmd-input"),
            id="cmd-bar",
        )
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        # Set up table columns
        kt = self.query_one("#k-table", DataTable)
        kt.add_columns("Ticker", "Title", "Yes", "Vol")
        pt = self.query_one("#p-table", DataTable)
        pt.add_columns("Question", "Yes", "Vol")

        # Console greeting
        c = self.query_one("#console-log", RichLog)
        c.write("[bold #58a6ff]Clawdbot[/] ready. Type /help for commands.")

        self.set_interval(1, self._tick_clock)
        self._start_all()

    @work(thread=False)
    async def _start_all(self) -> None:
        await self._load_initial()
        self._spawn_streams()

    # ── Initial REST load ─────────────────────────────────────────────────────

    async def _load_initial(self) -> None:
        self._log("Fetching initial market data…")
        await asyncio.gather(
            self._fetch_kalshi(),
            self._fetch_poly(),
            return_exceptions=True,
        )
        self._render_k_table()
        self._render_p_table()

        if self.kalshi:
            try:
                bal = await self.kalshi.get_balance()
                self._balance = f"${bal:.2f}"
            except Exception:
                pass

    async def _fetch_kalshi(self) -> None:
        if not self.kalshi:
            return
        try:
            markets = await self.kalshi.get_markets(limit=100)
            for m in markets:
                ticker = m.get("ticker", "")
                title  = m.get("title") or ticker
                yes_bid = m.get("yes_bid") or 0
                yes_ask = m.get("yes_ask") or 0
                price   = ((yes_bid + yes_ask) / 2 / 100) if (yes_bid or yes_ask) else 0
                volume  = m.get("volume", 0) or 0
                self._k_data[ticker] = {"title": title, "price": price, "volume": volume}
            self._log(f"Loaded [green]{len(markets)}[/] Kalshi markets")
        except Exception as e:
            self._log(f"[red]Kalshi fetch error:[/] {e}")

    async def _fetch_poly(self) -> None:
        try:
            markets = await self.poly.get_markets(limit=100)
            self._p_tokens = []
            for m in markets:
                mid      = str(m.get("id") or m.get("conditionId", ""))
                question = m.get("question") or "—"
                # price from outcomePrices
                raw = m.get("outcomePrices", [])
                if isinstance(raw, str):
                    try: raw = json.loads(raw)
                    except Exception: raw = []
                price = float(raw[0]) if isinstance(raw, list) and raw else 0
                volume = float(m.get("volume", 0) or 0)
                self._p_data[mid] = {"question": question, "price": price, "volume": volume}
                # collect token_ids for WS subscription
                for tid in (m.get("clobTokenIds") or []):
                    self._p_tokens.append(str(tid))
            self._log(f"Loaded [green]{len(markets)}[/] Polymarket markets")
        except Exception as e:
            self._log(f"[red]Polymarket fetch error:[/] {e}")

    # ── WebSocket streams ─────────────────────────────────────────────────────

    def _spawn_streams(self) -> None:
        if self.kalshi:
            t1 = asyncio.create_task(self.kalshi.stream(self._on_k_ws, self._on_k_status))
            self._tasks.append(t1)
        t2 = asyncio.create_task(
            self.poly.stream(self._p_tokens, self._on_p_ws, self._on_p_status)
        )
        self._tasks.append(t2)

    async def _on_k_ws(self, ticker: str, price: float) -> None:
        if ticker in self._k_data:
            self._k_data[ticker]["price"] = price
        else:
            self._k_data[ticker] = {"title": ticker, "price": price, "volume": 0}
        self.call_from_thread(self._render_k_table) if False else self._render_k_table()

    async def _on_p_ws(self, token_id: str, price: float) -> None:
        # Match token to market
        for mid, info in self._p_data.items():
            if token_id == mid:
                self._p_data[mid]["price"] = price
                self._render_p_table()
                return

    async def _on_k_status(self, status: str) -> None:
        lbl = self.query_one("#k-status", Label)
        if status == "connected":
            lbl.update("K: ● LIVE")
            lbl.remove_class("offline")
        else:
            lbl.update("K: ○ OFF")
            lbl.add_class("offline")

    async def _on_p_status(self, status: str) -> None:
        lbl = self.query_one("#p-status", Label)
        if status == "connected":
            lbl.update("P: ● LIVE")
            lbl.remove_class("offline")
        else:
            lbl.update("P: ○ OFF")
            lbl.add_class("offline")

    # ── Table rendering ───────────────────────────────────────────────────────

    def _render_k_table(self) -> None:
        try:
            table = self.query_one("#k-table", DataTable)
            table.clear()
            rows = sorted(self._k_data.items(), key=lambda x: -x[1]["volume"])
            for ticker, info in rows[:80]:
                price = info["price"]
                vol   = info["volume"]
                table.add_row(
                    ticker[:20],
                    (info["title"] or ticker)[:38],
                    f"{price:.2f}" if price else "—",
                    f"{vol:,}",
                    key=ticker,
                )
        except Exception:
            pass

    def _render_p_table(self) -> None:
        try:
            table = self.query_one("#p-table", DataTable)
            table.clear()
            rows = sorted(self._p_data.items(), key=lambda x: -x[1]["volume"])
            for mid, info in rows[:80]:
                price = info["price"]
                vol   = info["volume"]
                table.add_row(
                    (info["question"] or mid)[:55],
                    f"{price:.2f}" if price else "—",
                    f"{int(vol):,}",
                    key=mid,
                )
        except Exception:
            pass

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self) -> None:
        try:
            suffix = f"  {self._balance}" if self._balance else ""
            self.query_one("#clock", Label).update(
                datetime.now().strftime("%H:%M:%S") + suffix
            )
        except Exception:
            pass

    # ── Console helper ────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        try:
            self.query_one("#console-log", RichLog).write(text)
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────────────────────

    async def action_refresh(self) -> None:
        self._k_data.clear()
        self._p_data.clear()
        await self._load_initial()

    async def action_filter(self, category: str) -> None:
        self._filter = category
        try:
            self.query_one("#filter-label", Label).update(category.upper())
        except Exception:
            pass
        self._log(f"Filter: [yellow]{category}[/]")

    def action_focus_cmd(self) -> None:
        self.query_one("#cmd-input", Input).focus()

    def action_blur_cmd(self) -> None:
        self.query_one("#cmd-input", Input).blur()

    # ── Command input ─────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._log(f"[cyan]>[/] {text}")
        if text.startswith("/"):
            await self._cmd(text)
        else:
            asyncio.create_task(self._ask_agent(text))

    async def _cmd(self, raw: str) -> None:
        cmd = raw.split()[0].lower()
        if cmd == "/help":
            self._log(
                "[bold]Commands:[/]\n"
                "  /help     — this message\n"
                "  /refresh  — reload all data\n"
                "  /spreads  — markets on both platforms\n"
                "  /balance  — Kalshi account balance\n"
                "  /clear    — clear console\n"
                "  /quit     — exit\n"
                "  [anything else] → sent to Clawdbot"
            )
        elif cmd == "/refresh":
            await self.action_refresh()
        elif cmd == "/spreads":
            both = [
                (t, d) for t, d in self._k_data.items()
                if any(t.lower() in q["question"].lower() for q in self._p_data.values())
            ]
            self._log(f"[yellow]{len(both)}[/] potential cross-platform matches.")
        elif cmd == "/balance":
            if self.kalshi:
                try:
                    b = await self.kalshi.get_balance()
                    self._log(f"Balance: [green]${b:.2f}[/]")
                except Exception as e:
                    self._log(f"[red]Balance error:[/] {e}")
            else:
                self._log("[red]Kalshi not configured.[/]")
        elif cmd == "/clear":
            self.query_one("#console-log", RichLog).clear()
        elif cmd == "/quit":
            self.exit()
        else:
            self._log(f"[red]Unknown:[/] {cmd}  (try /help)")

    async def _ask_agent(self, question: str) -> None:
        if not OPENROUTER_KEY:
            self._log("[red]OPENROUTER_API_KEY not set in .env[/]")
            return

        # Summarise market context
        top_k = ", ".join(list(self._k_data.keys())[:10])
        top_p = ", ".join(
            info["question"][:40] for info in list(self._p_data.values())[:5]
        )
        system = (
            "You are Clawdbot, a concise prediction-market analyst. "
            "You have live data from Kalshi and Polymarket. Be brief and actionable.\n"
            f"Current Kalshi tickers (sample): {top_k}\n"
            f"Current Polymarket questions (sample): {top_p}"
        )
        self._log("[dim]Clawdbot thinking…[/]")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_KEY}",
                        "Content-Type":  "application/json",
                        "HTTP-Referer":  "https://github.com/kapilcdave/polyterminal",
                        "X-Title":       "PolyTerminal",
                    },
                    json={
                        "model":      OPENROUTER_MODEL,
                        "max_tokens": 512,
                        "messages": [
                            {"role": "system",  "content": system},
                            {"role": "user",    "content": question},
                        ],
                    },
                )
                r.raise_for_status()
                reply = r.json()["choices"][0]["message"]["content"]
            self._log(f"[magenta]Clawdbot:[/] {reply}")
        except Exception as e:
            self._log(f"[red]Agent error:[/] {e}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def on_unmount(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PolyTerminal().run()
