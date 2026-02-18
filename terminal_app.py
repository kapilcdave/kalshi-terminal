import os
import asyncio
import random
from datetime import datetime
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, DataTable, Static, Label, Input
from textual.reactive import reactive
from textual.binding import Binding

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from arb_engine import ArbEngine
from stream_manager import StreamManager

load_dotenv()

class BloombergHeader(Static):
    """A custom professional header."""
    title = reactive("POLYTERMINAL")
    category = reactive("ALL MARKETS")

    def compose(self) -> ComposeResult:
        with Horizontal(id="bbg-header"):
            yield Label(self.title, id="app-title")
            yield Label(" | ", classes="separator")
            yield Label(self.category, id="app-category")
            yield Label(" | ", classes="separator")
            yield Label("PRO EDITION v1.0", id="app-subtitle")
            yield Label("", id="clock")

    def watch_category(self, category: str) -> None:
        try:
            self.query_one("#app-category").update(category.upper())
        except:
            pass

class MarketPane(Vertical):
    """A pane displaying markets for a specific platform."""
    def __init__(self, title, platform_name, **kwargs):
        super().__init__(**kwargs)
        self.pane_title = title
        self.platform = platform_name

    def compose(self) -> ComposeResult:
        yield Label(self.pane_title, classes="pane-header")
        yield DataTable(id=f"{self.platform}-table")

class PolyTerminal(App):
    CSS = """
    Screen {
        background: #000000;
        color: #00FFFF;
    }

    #bbg-header {
        height: 1;
        background: #000080;
        color: #FFFFFF;
        padding: 0 1;
    }

    #app-title { text-style: bold; color: #00FFFF; }
    .separator { color: #555555; }
    #app-category { color: #FFA500; text-style: bold; }
    #app-subtitle { color: #AAAAAA; }
    #clock { width: 1fr; text-align: right; color: #00FF00; }

    .pane-header {
        background: #111111;
        color: #FFFFFF;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid #00FFFF;
    }

    DataTable {
        height: 1fr;
        background: #000000;
        color: #00FF00;
        border: none;
    }

    DataTable > .datatable--header {
        background: #050505;
        color: #00FFFF;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #003333;
        color: #FFFFFF;
    }

    #main-container {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 1fr;
    }

    Footer {
        background: #000080;
        color: #FFFFFF;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('financial')", "Financial"),
        Binding("f2", "filter('politics')", "Politics"),
        Binding("f3", "filter('sports')", "Sports"),
        Binding("f4", "filter('all')", "All"),
        Binding("t", "toggle_theme", "Toggle Theme"),
    ]

    current_niche = reactive("all")
    themes = ["bloomberg", "hacker", "classic"]
    current_theme_index = reactive(0)

    def __init__(self):
        super().__init__()
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.arb = ArbEngine(self.kalshi, self.poly)
        self.k_markets = {}
        self.p_markets = {}

    def compose(self) -> ComposeResult:
        yield BloombergHeader()
        with Container(id="main-container"):
            yield MarketPane("KALSHI (USD)", "kalshi")
            yield MarketPane("POLYMARKET (USDC)", "poly")
        yield Footer()

    async def on_mount(self) -> None:
        # Setup Tables
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.add_columns("Ticker", "Price", "Vol")
        k_table.cursor_type = "row"

        p_table = self.query_one("#poly-table", DataTable)
        p_table.add_columns("Market", "Price", "Vol")
        p_table.cursor_type = "row"

        await self.kalshi.login()
        
        # Start Clock Update
        self.set_interval(1, self.update_clock)
        
        # Start Stream Manager for live price updates if needed
        # self.stream = StreamManager(self.handle_stream_update)
        # asyncio.create_task(self.stream.start())
        
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
        self.highlight_matches()

    async def refresh_kalshi(self, category=None):
        table = self.query_one("#kalshi-table", DataTable)
        table.clear()
        markets = await self.kalshi.get_active_markets(limit=30, category=category)
        self.k_markets = {m.ticker: m for m in markets}
        for m in markets:
            bid = getattr(m, 'yes_bid', 0)
            vol = getattr(m, 'volume', 0)
            table.add_row(m.ticker, f"{bid:.2f}", str(vol), key=m.ticker)

    async def refresh_poly(self, category=None):
        table = self.query_one("#poly-table", DataTable)
        table.clear()
        
        poly_tag = None
        if category == "politics": poly_tag = "Politics"
        elif category == "sports": poly_tag = "Sports"
        elif category == "financial": poly_tag = "Business"
        
        markets = await self.poly.get_active_markets(limit=30, tag=poly_tag)
        self.p_markets = {str(m.get('id')): m for m in markets}
        for m in markets:
            price = m.get('outcomePrices', ['0'])[0]
            vol = m.get('volume', '0')
            table.add_row(m.get('question', 'Unknown')[:50] + "...", price, str(vol), key=str(m.get('id')))

    def highlight_matches(self):
        """Spot markets that appear on both platforms."""
        matches = self.arb.find_matches(self.k_markets.values(), self.p_markets.values(), threshold=0.7)
        # We can add a simple Visual cue like a '*' or color if Textual row styling allows
        # For now, let's update titles of matching rows to show they are paired
        k_table = self.query_one("#kalshi-table", DataTable)
        p_table = self.query_one("#poly-table", DataTable)
        
        for match in matches:
            k_ticker = match['kalshi'].ticker
            p_id = str(match['poly'].get('id'))
            
            # Highlight by adding a prefix or changing color if possible
            # In Textual, updating a single cell is easiest
            try:
                k_table.update_cell(k_ticker, "Ticker", f"🔗 {k_ticker}")
                current_p_val = p_table.get_cell(p_id, "Market")
                if not current_p_val.startswith("🔗"):
                    p_table.update_cell(p_id, "Market", f"🔗 {current_p_val}")
            except:
                pass

    async def action_filter(self, niche: str) -> None:
        self.current_niche = niche
        self.query_one(BloombergHeader).category = niche
        await self.action_refresh()

    def action_toggle_theme(self) -> None:
        self.current_theme_index = (self.current_theme_index + 1) % len(self.themes)
        theme = self.themes[self.current_theme_index]
        self.apply_theme(theme)

    def apply_theme(self, theme_name: str):
        # Programmatic style adjustment for Textual
        if theme_name == "hacker":
            self.theme = "dracula" # Textual built-in or custom colors
            self.styles.background = "#001100"
            self.styles.color = "#00FF00"
        elif theme_name == "classic":
            self.styles.background = "#f0f0f0"
            self.styles.color = "#000000"
        else: # Bloomberg
            self.styles.background = "#000000"
            self.styles.color = "#00FFFF"

if __name__ == "__main__":
    app = PolyTerminal()
    app.run()
