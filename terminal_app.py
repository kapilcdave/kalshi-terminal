

import os
import asyncio
import random
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.widgets import Header, Footer, DataTable, Static, Label, Digits, Sparkline, TabbedContent, TabPane, Input
from textual.reactive import reactive
from textual.binding import Binding

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from arb_engine import ArbEngine
from stream_manager import StreamManager
from agent_hub import AgentHub

load_dotenv()

class BloombergHeader(Static):
    """A custom professional header."""
    def compose(self) -> ComposeResult:
        with Horizontal(id="bbg-header"):
            yield Label("POLYTERMINAL", id="app-title")
            yield Label(" | ", classes="separator")
            yield Label("PRO EDITION v1.0", id="app-subtitle")
            yield Label("", id="clock")

class MarketPane(Vertical):
    """A pane displaying markets for a specific platform."""
    def __init__(self, title, platform_name, **kwargs):
        super().__init__(**kwargs)
        self.pane_title = title
        self.platform = platform_name

    def compose(self) -> ComposeResult:
        yield Label(self.pane_title, classes="pane-header")
        yield DataTable(id=f"{self.platform}-table")

class KalshiPolymarketTerminal(App):
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
    #app-subtitle { color: #AAAAAA; }

    .pane-header {
        background: #222222;
        color: #FFA500;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid #444444;
    }

    DataTable {
        height: 1fr;
        background: #000000;
        color: #00FF00;
        border: none;
    }

    DataTable > .datatable--header {
        background: #111111;
        color: #00FFFF;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #333333;
        color: #FFFFFF;
    }

    #main-container {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 1fr;
    }

    #arb-pane {
        height: 8;
        background: #001100;
        border-top: double #00FF00;
        padding: 0 1;
    }

    .arb-header { color: #00FF00; text-style: bold; }
    .arb-item { color: #FFFFFF; }
    .profitable { color: #00FF00; text-style: bold; }

    #agent-pane {
        height: 10;
        border-top: heavy #8800FF;
        background: #0a001a;
        padding: 0 1;
    }

    .agent-header { color: #8800FF; text-style: bold; }
    #agent-input {
        background: #111111;
        color: #FFFFFF;
        border: none;
    }

    Footer {
        background: #000080;
        color: #FFFFFF;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh All"),
        Binding("a", "toggle_arb", "Arb Monitor"),
    ]

    def __init__(self):
        super().__init__()
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.arb = ArbEngine(self.kalshi, self.poly)
        self.k_markets = {}
        self.p_markets = {}
        self.current_match = None

    def compose(self) -> ComposeResult:
        yield BloombergHeader()
        with Container(id="main-container"):
            yield MarketPane("KALSHI MARKETS (USD)", "kalshi")
            yield MarketPane("POLYMARKET (USDC)", "poly")
        with Vertical(id="arb-pane"):
            yield Label("ACTIVE ARBITRAGE SCANNER", classes="arb-header")
            yield Static("Scanning for opportunities...", id="arb-status")
        with Vertical(id="agent-pane"):
            yield Label("AGENT COMMAND CENTER (BETA)", classes="agent-header")
            yield Static("Ready for commands. Type 'analyze' or 'execute'...", id="agent-output")
            yield Input(placeholder="Ask the Terminal Agent...", id="agent-input")
        yield Footer()

    async def on_mount(self) -> None:
        # Initial Auth & Hubs
        self.agent_hub = AgentHub(self)
        
        # Setup Tables
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.add_columns("Ticker", "Price", "Vol")
        k_table.cursor_type = "row"

        p_table = self.query_one("#poly-table", DataTable)
        p_table.add_columns("Market", "Price", "Vol")
        p_table.cursor_type = "row"

        await self.kalshi.login()
        
        # Start Stream Manager
        self.stream = StreamManager(self.handle_stream_update)
        asyncio.create_task(self.stream.start())
        
        await self.action_refresh()

    async def handle_stream_update(self, platform, data):
        """Handle real-time updates from WebSocket."""
        if platform == "poly":
            # Polymarket WS format (Market channel):
            # {"event": "price_update", "asset_id": "...", "price": "..."}
            if data.get("event") == "price_update":
                token_id = data.get("asset_id")
                new_price = data.get("price")
                # Update our local record
                for m_id, m in self.p_markets.items():
                    if m.get('tokens') and m['tokens'][0]['token_id'] == token_id:
                        m['outcomePrices'] = [new_price]
                        # Refresh table row
                        self.refresh_table_row("poly", m_id)
                        break
        
        self.update_arb_status()

    def refresh_table_row(self, platform, item_id):
        """Update a specific row in the DataTable without clearing everything."""
        table = self.query_one(f"#{platform}-table", DataTable)
        if platform == "poly":
            m = self.p_markets.get(item_id)
            # This is tricky because Textual's DataTable uses keys or coordinates.
            # For simplicity in this TUI, we might just re-render or find by coordinate.
            # Transitioning to coordinate-based update would be better for performance.
            pass

    async def action_refresh(self) -> None:
        await asyncio.gather(
            self.refresh_kalshi(),
            self.refresh_poly()
        )
        self.update_arb_status()

    async def refresh_kalshi(self):
        table = self.query_one("#kalshi-table", DataTable)
        table.clear()
        markets = await self.kalshi.get_active_markets(limit=20)
        self.k_markets = {m.ticker: m for m in markets}
        for m in markets:
            bid = getattr(m, 'yes_bid', 0)
            vol = getattr(m, 'volume', 0)
            table.add_row(m.ticker, f"{bid:.2f}", str(vol))

    async def refresh_poly(self):
        table = self.query_one("#poly-table", DataTable)
        table.clear()
        markets = await self.poly.get_active_markets(limit=20)
        self.p_markets = {str(m.get('id')): m for m in markets}
        
        token_ids = []
        for m in markets:
            price = m.get('outcomePrices', ['0'])[0]
            vol = m.get('volume', '0')
            table.add_row(m.get('question', 'Unknown')[:40] + "...", price, str(vol))
            if m.get('tokens'):
                token_ids.append(m['tokens'][0]['token_id'])

        # Update WebSocket subscription
        if hasattr(self, 'stream'):
            await self.stream.subscribe_poly(token_ids)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle agent command input."""
        if event.input.id == "agent-input":
            command = event.value
            event.input.value = "" # Clear input
            self.query_one("#agent-output").update(f"[cyan]Agent:[/] Processing '{command}'...")
            
            # Call the agent hub
            response = await self.agent_hub.process_query(command)
            self.query_one("#agent-output").update(f"[cyan]Agent:[/] {response}")

    def update_arb_status(self):
        # Placeholder for real-time arb logic
        # In a real run, we'd use ArbEngine.find_matches
        matches = self.arb.find_matches(self.k_markets.values(), self.p_markets.values())
        if matches:
            self.current_match = matches[0]
            best = self.current_match
            self.query_one("#arb-status").update(
                f"POTENTIAL MATCH: [white]{best['kalshi'].ticker}[/white] <--> [white]{best['poly'].get('question')[:30]}[/white] (Sim: {best['ratio']:.2f})"
            )
        else:
            self.current_match = None
            self.query_one("#arb-status").update("No clear matches found. Broadening search...")

if __name__ == "__main__":
    app = KalshiPolymarketTerminal()
    app.run()
