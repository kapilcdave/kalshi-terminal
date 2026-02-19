import os
import asyncio
import random
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Footer, DataTable, Static, Label, Header
from textual.reactive import reactive
from textual.binding import Binding

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from arb_engine import ArbEngine

load_dotenv()

THEMES = ["nord", "gruvbox", "tokyo-night", "textual-dark", "solarized-light", "monokai"]

class BloombergHeader(Static):
    title = reactive("POLYTERMINAL")
    category = reactive("ALL MARKETS")

    def compose(self) -> ComposeResult:
        with Horizontal(id="bbg-header"):
            yield Label(self.title, id="app-title")
            yield Label(" | ", classes="separator")
            yield Label(self.category, id="app-category")
            yield Label(" | ", classes="separator")
            yield Label("v1.0", id="app-subtitle")
            yield Label("", id="clock")

class PolyTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('financial')", "Financial"),
        Binding("f2", "filter('politics')", "Politics"),
        Binding("f3", "filter('sports')", "Sports"),
        Binding("f4", "filter('all')", "All"),
        Binding("t", "next_theme", "Theme"),
    ]

    current_niche = reactive("all")
    current_theme_idx = reactive(0)

    def __init__(self):
        super().__init__()
        self.theme = THEMES[0]
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.arb = ArbEngine(self.kalshi, self.poly)
        self.k_markets = {}
        self.p_markets = {}
        self.expanded_groups = set()

    def compose(self) -> ComposeResult:
        yield BloombergHeader()
        with Container(id="main-container"):
            with ScrollableContainer(id="kalshi-pane"):
                yield Label("KALSHI (USD)", classes="pane-header")
                yield DataTable(id="kalshi-table")
            with ScrollableContainer(id="poly-pane"):
                yield Label("POLYMARKET (USDC)", classes="pane-header")
                yield DataTable(id="poly-table")
        yield Footer()

    async def on_mount(self) -> None:
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.add_columns("Group", "Market", "Yes", "No", "Vol")
        k_table.cursor_type = "row"

        p_table = self.query_one("#poly-table", DataTable)
        p_table.add_columns("Group", "Market", "Yes", "No", "Vol")
        p_table.cursor_type = "row"

        await self.kalshi.login()
        self.set_interval(1, self.update_clock)
        await self.action_refresh()

    def update_clock(self):
        try:
            self.query_one("#clock").update(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except:
            pass

    async def action_refresh(self) -> None:
        await asyncio.gather(
            self.refresh_kalshi(self.current_niche if self.current_niche != "all" else None),
            self.refresh_poly(self.current_niche if self.current_niche != "all" else None)
        )

    def _extract_event_name(self, ticker: str, title: str) -> str:
        if "-" in ticker:
            parts = ticker.split("-")
            if len(parts) >= 2:
                base = parts[0] + "-" + parts[1]
                if len(base) > 18:
                    base = base[:18]
                return base
        if title:
            words = title.split()
            if len(words) >= 3:
                return " ".join(words[:2])[:18]
        return ticker[:18]

    async def refresh_kalshi(self, category=None):
        table = self.query_one("#kalshi-table", DataTable)
        table.clear()
        
        markets = await self.kalshi.get_active_markets(limit=50, category=category)
        
        groups = defaultdict(list)
        for m in markets:
            event = self._extract_event_name(m.ticker, getattr(m, 'title', m.ticker))
            groups[event].append(m)
        
        self.k_markets = {m.ticker: m for m in markets}
        
        for event_name, group_markets in sorted(groups.items()):
            for m in group_markets:
                title = getattr(m, 'title', m.ticker) or m.ticker
                yes_bid = getattr(m, 'yes_bid', 0) or 0
                yes_ask = getattr(m, 'yes_ask', 0) or 0
                no_bid = getattr(m, 'no_bid', 100) or 100
                no_ask = getattr(m, 'no_ask', 100) or 100
                vol = getattr(m, 'volume', 0) or 0
                
                yes_price = (yes_bid + yes_ask) / 2 / 100 if (yes_bid or yes_ask) else 0
                no_price = (no_bid + no_ask) / 2 / 100 if (no_bid or no_ask) else 0
                
                table.add_row(
                    event_name,
                    title[:40] + "..." if len(title) > 40 else title,
                    f"{yes_price:.2f}" if yes_price > 0 else "--",
                    f"{no_price:.2f}" if no_price > 0 else "--",
                    f"{vol:,}",
                    key=m.ticker
                )

    async def refresh_poly(self, category=None):
        table = self.query_one("#poly-table", DataTable)
        table.clear()
        
        poly_tag = None
        if category == "politics": poly_tag = "Politics"
        elif category == "sports": poly_tag = "Sports"
        elif category == "financial": poly_tag = "Business"
        
        markets = await self.poly.get_active_markets(limit=50, tag=poly_tag)
        
        groups = defaultdict(list)
        for m in markets:
            question = m.get('question', 'Unknown')
            event = self._extract_event_name(m.get('id', 'unknown'), question)
            groups[event].append(m)
        
        self.p_markets = {str(m.get('id')): m for m in markets}
        
        for event_name, group_markets in sorted(groups.items()):
            for m in group_markets:
                question = m.get('question', 'Unknown')
                prices = m.get('outcomePrices', [])
                if isinstance(prices, str):
                    import json
                    try:
                        prices = json.loads(prices)
                    except:
                        prices = []
                yes_price = float(prices[0]) if (isinstance(prices, (list, tuple)) and len(prices) > 0) else 0
                no_price = float(prices[1]) if (isinstance(prices, (list, tuple)) and len(prices) > 1) else 0
                vol = float(m.get('volume', 0) or 0)
                
                table.add_row(
                    event_name,
                    question[:40] + "..." if len(question) > 40 else question,
                    f"{yes_price:.2f}",
                    f"{no_price:.2f}",
                    f"{int(vol):,}",
                    key=str(m.get('id'))
                )

    async def action_filter(self, niche: str) -> None:
        self.current_niche = niche
        try:
            self.query_one("#app-category").update(niche.upper())
        except:
            pass
        await self.action_refresh()

    def action_next_theme(self) -> None:
        self.current_theme_idx = (self.current_theme_idx + 1) % len(THEMES)
        self.theme = THEMES[self.current_theme_idx]
        self.sub_title = f"Theme: {self.theme}"

if __name__ == "__main__":
    app = PolyTerminal()
    app.run()
