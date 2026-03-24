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

from clients import KalshiClient, PolyClient, get_public_kalshi_markets
from market_grouping import build_grouped_markets, summarize_groups
from market_matching import find_candidate_matches

load_dotenv()
logging.basicConfig(level=logging.WARNING)

OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY   = os.getenv("OPENROUTER_API_KEY", "")
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

# ─── Keyword filter map ────────────────────────────────────────────────────────

FILTER_KEYWORDS: dict[str, list[str]] = {
    "all":      [],
    "finance":  ["stock", "market", "fed", "rate", "inflation", "gdp", "crypto", "bitcoin", "eth", "recession", "economy"],
    "politics": ["election", "president", "congress", "senate", "vote", "trump", "biden", "democrat", "republican", "governor", "party"],
    "sports":   ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "hockey", "tennis", "golf", "ufc", "mma", "champion"],
}

# ─── App ──────────────────────────────────────────────────────────────────────

class PolyTerminal(App):
    CSS = CSS
    BINDINGS = [
        Binding("q",      "quit",             "Quit"),
        Binding("r",      "refresh",          "Refresh"),
        Binding("f1",     "filter('all')",    "All"),
        Binding("f2",     "filter('finance')", "Finance"),
        Binding("f3",     "filter('politics')", "Politics"),
        Binding("f4",     "filter('sports')",  "Sports"),
        Binding("/",      "focus_cmd",        "Command"),
        Binding("escape", "blur_cmd",         "Dismiss"),
    ]

    def __init__(self):
        super().__init__()

        api_key  = os.getenv("KALSHI_API_KEY", "")
        raw_key_file = os.getenv("KALSHI_PRIVATE_KEY_FILE", "").strip('"').strip("'")
        key_file = os.path.abspath(raw_key_file) if raw_key_file else ""
        pem      = open(key_file).read() if key_file and os.path.exists(key_file) else ""

        self.kalshi: Optional[KalshiClient] = KalshiClient(api_key, pem) if api_key and pem else None
        self.poly = PolyClient()
        self._kalshi_key_path = key_file
        self._kalshi_auth_available = bool(api_key and pem)

        # {ticker: {title, price, volume}}
        self._k_data: dict = {}
        # {market_id: {question, price, volume}}
        self._p_data: dict = {}
        # {token_id: market_id}
        self._p_token_to_mid: dict = {}
        # token_ids subscribed to poly WS
        self._p_tokens: list[str] = []

        self._filter  = "all"
        self._balance = ""

        # dirty flags — set on WS tick, cleared after periodic render
        self._k_dirty = False
        self._p_dirty = False

        # background tasks (WS streams)
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
        # Set up Kalshi table columns with fixed widths
        kt = self.query_one("#k-table", DataTable)
        kt.add_column("Ticker", width=14)
        kt.add_column("Title",  width=None)   # auto-fill remaining space
        kt.add_column("Yes",    width=8)
        kt.add_column("Vol",    width=10)

        # Set up Polymarket table columns with fixed widths
        pt = self.query_one("#p-table", DataTable)
        pt.add_column("Question", width=None)  # auto-fill remaining space
        pt.add_column("Yes",      width=8)
        pt.add_column("Vol",      width=10)

        # Console greeting
        c = self.query_one("#console-log", RichLog)
        c.write("[bold #58a6ff]Clawdbot[/] ready. Type /help for commands.")
        if not self._kalshi_auth_available:
            if self._kalshi_key_path:
                self._log(f"[yellow]Kalshi WS disabled:[/] missing private key file at {self._kalshi_key_path}")
            else:
                self._log("[yellow]Kalshi WS disabled:[/] KALSHI_PRIVATE_KEY_FILE is not configured")

        # Clock: every second
        self.set_interval(1, self._tick_clock)
        # Throttled table renders: ~2 Hz to avoid thrashing on WS ticks
        self.set_interval(0.5, self._flush_tables)

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
        try:
            if self.kalshi:
                markets = await self.kalshi.get_markets(limit=100)
            else:
                markets = await get_public_kalshi_markets(limit=100)
            for m in markets:
                ticker  = m.get("ticker", "")
                title   = m.get("title") or ticker
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
            self._p_token_to_mid.clear()
            for m in markets:
                mid      = str(m.get("id") or m.get("conditionId", ""))
                question = m.get("question") or "—"
                raw      = m.get("outcomePrices", [])
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = []
                price  = float(raw[0]) if isinstance(raw, list) and raw else 0
                volume = float(m.get("volume", 0) or 0)
                self._p_data[mid] = {"question": question, "price": price, "volume": volume}
                for tid in (m.get("clobTokenIds") or []):
                    tid_str = str(tid)
                    self._p_tokens.append(tid_str)
                    self._p_token_to_mid[tid_str] = mid
            self._log(f"Loaded [green]{len(markets)}[/] Polymarket markets")
        except Exception as e:
            self._log(f"[red]Polymarket fetch error:[/] {e}")

    # ── WebSocket streams ─────────────────────────────────────────────────────

    def _spawn_streams(self) -> None:
        if self.kalshi:
            self._tasks.append(
                asyncio.create_task(self.kalshi.stream(self._on_k_ws, self._on_k_status, log_cb=self._log))
            )
        else:
            self._log("[dim]Skipping Kalshi WS: authenticated client unavailable.[/]")
        self._tasks.append(
            asyncio.create_task(self.poly.stream(self._p_tokens, self._on_p_ws, self._on_p_status, log_cb=self._log))
        )

    async def _cancel_streams(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _on_k_ws(self, ticker: str, price: float) -> None:
        if ticker in self._k_data:
            self._k_data[ticker]["price"] = price
        else:
            self._k_data[ticker] = {"title": ticker, "price": price, "volume": 0}
        self._k_dirty = True

    async def _on_p_ws(self, token_id: str, price: float) -> None:
        mid = self._p_token_to_mid.get(token_id)
        if mid and mid in self._p_data:
            self._p_data[mid]["price"] = price
            self._p_dirty = True

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

    # ── Throttled table flush ─────────────────────────────────────────────────

    def _flush_tables(self) -> None:
        """Called at 2 Hz. Only re-renders tables that have pending updates."""
        if self._k_dirty:
            self._k_dirty = False
            self._render_k_table()
        if self._p_dirty:
            self._p_dirty = False
            self._render_p_table()

    # ── Table rendering ───────────────────────────────────────────────────────

    def _matches_filter(self, text: str) -> bool:
        keywords = FILTER_KEYWORDS.get(self._filter, [])
        if not keywords:
            return True  # "all" — show everything
        tl = text.lower()
        return any(kw in tl for kw in keywords)

    def _render_k_table(self) -> None:
        try:
            table = self.query_one("#k-table", DataTable)
            table.clear()
            rows = sorted(self._k_data.items(), key=lambda x: (-x[1]["volume"], x[0]))
            grouped = build_grouped_markets(rows, "title")
            last_group = None
            shown = 0
            group_index = 0
            for market in grouped:
                if not self._matches_filter(market.title):
                    continue
                if market.group != last_group:
                    group_index += 1
                    table.add_row(
                        "",
                        f"[{market.group[:34]}]",
                        "",
                        "",
                        key=f"k-group-{group_index}",
                    )
                    last_group = market.group

                table.add_row(
                    market.market_id[:20],
                    f"  {market.title[:36]}",
                    f"{market.price:.2f}" if market.price else "—",
                    f"{int(market.volume):,}",
                    key=market.market_id,
                )
                shown += 1
                if shown >= 80:
                    break
        except Exception:
            pass

    def _render_p_table(self) -> None:
        try:
            table = self.query_one("#p-table", DataTable)
            table.clear()
            rows = sorted(self._p_data.items(), key=lambda x: (-x[1]["volume"], x[0]))
            grouped = build_grouped_markets(rows, "question")
            last_group = None
            shown = 0
            group_index = 0
            for market in grouped:
                if not self._matches_filter(market.title):
                    continue
                if market.group != last_group:
                    group_index += 1
                    table.add_row(
                        f"[{market.group[:53]}]",
                        "",
                        "",
                        key=f"p-group-{group_index}",
                    )
                    last_group = market.group

                table.add_row(
                    f"  {market.title[:53]}",
                    f"{market.price:.2f}" if market.price else "—",
                    f"{int(market.volume):,}",
                    key=market.market_id,
                )
                shown += 1
                if shown >= 80:
                    break
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
        self._log("[dim]Restarting streams and refreshing data…[/]")
        await self._cancel_streams()
        self._k_data.clear()
        self._p_data.clear()
        self._p_token_to_mid.clear()
        self._p_tokens.clear()
        await self._load_initial()
        self._spawn_streams()

    async def action_filter(self, category: str) -> None:
        self._filter = category
        try:
            self.query_one("#filter-label", Label).update(category.upper())
        except Exception:
            pass
        self._log(f"Filter: [yellow]{category}[/]")
        # Re-render both tables immediately with new filter
        self._render_k_table()
        self._render_p_table()

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
            self._ask_agent(text)  # calls @work method — Textual manages the task

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
            k_groups = summarize_groups(list(self._k_data.items()), "title")
            p_groups = summarize_groups(list(self._p_data.items()), "question")
            shared_groups = sorted(set(k_groups) & set(p_groups))

            if not shared_groups:
                self._log("[yellow]0[/] shared cross-platform event groups.")
                return

            self._log(f"[green]{len(shared_groups)}[/] shared cross-platform event groups:")
            shown_groups = 0
            total_candidate_matches = 0
            for group_key in shared_groups:
                k_bucket = k_groups[group_key]
                p_bucket = p_groups[group_key]
                k_markets = {
                    market.market_id: {
                        "title": market.title,
                        "price": market.price,
                        "volume": market.volume,
                    }
                    for market in k_bucket["markets"]
                }
                p_markets = {
                    market.market_id: {
                        "question": market.title,
                        "price": market.price,
                        "volume": market.volume,
                    }
                    for market in p_bucket["markets"]
                }
                candidates = find_candidate_matches(k_markets, p_markets, min_score=0.45)
                total_candidate_matches += len(candidates)

                self._log(
                    f"[bold]{k_bucket['label']}[/] | "
                    f"K {k_bucket['count']} / P {p_bucket['count']} | "
                    f"candidates [cyan]{len(candidates)}[/]"
                )
                self._log("  Kalshi")
                for market in k_bucket["markets"][:4]:
                    self._log(
                        f"    |- {market.market_id[:24]} | {market.title[:52]} | "
                        f"{market.price:.2f} | vol {int(market.volume):,}"
                    )
                if k_bucket["count"] > 4:
                    self._log(f"    `- … {k_bucket['count'] - 4} more")

                self._log("  Polymarket")
                for market in p_bucket["markets"][:4]:
                    self._log(
                        f"    |- {market.title[:60]} | {market.price:.2f} | vol {int(market.volume):,}"
                    )
                if p_bucket["count"] > 4:
                    self._log(f"    `- … {p_bucket['count'] - 4} more")

                if candidates:
                    self._log("  Candidate Matches")
                    for candidate in candidates[:3]:
                        reasons = ", ".join(candidate.reasons[:3])
                        self._log(
                            f"    |- {candidate.kalshi_ticker[:22]} <-> "
                            f"{candidate.poly_question[:38]} | "
                            f"score {candidate.score:.2f} | "
                            f"spread {candidate.spread:.3f} | {reasons}"
                        )
                    if len(candidates) > 3:
                        self._log(f"    `- … {len(candidates) - 3} more")
                else:
                    self._log("  Candidate Matches")
                    self._log("    `- none above score threshold")

                shown_groups += 1
                if shown_groups >= 8:
                    remaining = len(shared_groups) - shown_groups
                    if remaining > 0:
                        self._log(f"[dim]… {remaining} more shared groups not shown.[/]")
                    break

            self._log(f"[yellow]{total_candidate_matches}[/] candidate submarket matches in shown groups.")
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

    @work(exclusive=False)
    async def _ask_agent(self, question: str) -> None:
        """Send a question to Clawdbot via OpenRouter. Runs as a Textual worker."""
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
                            {"role": "system", "content": system},
                            {"role": "user",   "content": question},
                        ],
                    },
                )
                r.raise_for_status()
                data  = r.json()
                reply = data["choices"][0]["message"]["content"]
            self._log(f"[magenta]Clawdbot:[/] {reply}")
        except httpx.HTTPStatusError as e:
            self._log(f"[red]Clawdbot API error {e.response.status_code}:[/] {e.response.text[:200]}")
        except Exception as e:
            self._log(f"[red]Clawdbot error:[/] {e}")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    async def on_unmount(self) -> None:
        await self._cancel_streams()


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    PolyTerminal().run()
