import os
import asyncio
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, DataTable, Static, Input, 
    RichLog, Label
)
from textual.reactive import reactive
from textual.binding import Binding
from textual import work

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from market_matcher import UnifiedMarket
from unified_store import UnifiedStore
from live_engine import LiveEngine
from agent_manager import AgentManager

CSS_PATH = "prediction_terminal.tcss"

class MarketClassifier:
    CATEGORIES = {
        "politics": [r"\btrump\b", r"\bbiden\b", r"\bpresident\b", r"\belection\b", r"\bcongress\b", r"\bsenate\b", r"\bhouse\b", r"\bdemocrat\b", r"\brepublican\b", r"\bgov\b", r"\bsenator\b", r"\brussia\b", r"\bukraine\b", r"\bisrael\b", r"\bchina\b", r"\biran\b"],
        "sports": [r"\bnba\b", r"\bnfl\b", r"\bmlb\b", r"\bnhl\b", r"\bcollege\b", r"\bfootball\b", r"\bbasketball\b", r"\bbaseball\b", r"\bhockey\b", r"\bsoccer\b", r"\bgolf\b", r"\btennis\b", r"\bATP\b", r"\bNCAAB\b", r"\b3pt\b", r"\bgame\b", r"\bwin\b", r"\bplayoff\b"],
        "financial": [r"\bfed\b", r"\binterest\b", r"\brate\b", r"\binflation\b", r"\bgdp\b", r"\bmarket\b", r"\bstock\b", r"\bbitcoin\b", r"\bbtc\b", r"\bcrypto\b", r"\brecession\b", r"\beconomy\b", r"\bdoge\b", r"\bbudget\b", r"\brevenue\b"],
        "entertainment": [r"\boscar\b", r"\bgrammy\b", r"\bemmy\b", r"\bmovie\b", r"\bnetflix\b", r"\bdisney\b", r"\bgta\b", r"\balbum\b", r"\bmusic\b"],
    }
    
    @classmethod
    def classify(cls, text: str) -> str:
        text = text.lower()
        for category, patterns in cls.CATEGORIES.items():
            for pattern in patterns:
                import re
                if re.search(pattern, text, re.IGNORECASE):
                    return category
        return "other"

class Ticker(Static):
    """Bloomberg-style header ticker."""
    def on_mount(self):
        self.set_interval(5, self.update_ticker)
        self.update_ticker()

    def update_ticker(self):
        # Sample indexes / data
        spx = 5234.12
        spx_delta = -0.12
        btc = 67890.50
        btc_delta = 2.34
        dxy = 104.20
        
        spx_style = "red" if spx_delta < 0 else "green"
        btc_style = "red" if btc_delta < 0 else "green"
        
        content = (
            f" SPX @ {spx:.2f}  [{spx_style}]{spx_delta:+.2f}[/]  |  "
            f"BTC @ {btc:,.2f}  [{btc_style}]{btc_delta:+.2f}%[/]  |  "
            f"DXY @ {dxy:.2f} "
        )
        self.update(content)

class ClawdbotBar(Static):
    """Personality-driven status bar."""
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(" 🦞 ", id="clawdbot-logo")
            yield Label("[Clawdbot v1.0] Initialized and monitoring markets...", id="bot-message")

class PredictionTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('all')", "All"),
        Binding("f2", "filter('financial')", "Finance"),
        Binding("f3", "filter('politics')", "Politics"),
        Binding("f4", "filter('sports')", "Sports"),
        Binding("/", "focus_input", "Command"),
        Binding("escape", "blur_input", "Clear"),
    ]

    current_filter = reactive("all")

    def __init__(self):
        super().__init__()
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.store = UnifiedStore()
        
        # Initialize engine with available keys
        self.engine = LiveEngine(
            store=self.store,
            kalshi_env=os.getenv("KALSHI_ENV", "demo"),
            kalshi_api_key=os.getenv("KALSHI_API_KEY"),
            kalshi_private_key=self.kalshi.private_key_content if not self.kalshi.use_mock else None
        )
        
        self.agent = AgentManager(
            store=self.store,
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    def compose(self) -> ComposeResult:
        yield Ticker(id="ticker-container")
        with Container(id="main-layout"):
            yield DataTable(id="market-table")
        yield ClawdbotBar(id="clawdbot-bar")
        yield Footer()
        
        with Horizontal(id="command-bar", classes="hidden"):
            yield Input(id="command-input", placeholder="Type /help or a command...")

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Event", "Kalshi", "Poly", "Δ%", "Volume")
        table.cursor_type = "row"
        table.focus()

        # Subscriptions
        self.store.subscribe(self._on_store_update)
        table.on_row_selected = self._on_row_selected
        
        await self.engine.start()
        await self.agent.start()
        
        # Initial data fetch
        await self.action_refresh()

    def _on_store_update(self, market, change_type):
        """Handle updates from the unified store."""
        if change_type == "rebuild_complete" or "update" in change_type:
            self.call_from_thread(self._refresh_table)

    def _refresh_table(self):
        table = self.query_one(DataTable)
        markets = self.store.get_all_markets()

        if self.current_filter != "all":
            markets = [m for m in markets if MarketClassifier.classify(m.event_name) == self.current_filter]

        markets.sort(key=lambda m: m.total_volume, reverse=True)

        # High-density update
        for market in markets[:100]:
            key = market.id
            
            # Formatted values
            k_price = f"{market.kalshi_price:.2f}" if market.kalshi_price > 0 else "—"
            p_price = f"{market.poly_price:.2f}" if market.poly_price > 0 else "—"
            delta = f"{market.delta_percent:+.1f}%" if market.has_both_prices else "—"
            vol = f"{market.total_volume:,}"
            
            # Color coding helpers
            def get_prob_style(p):
                if p >= 0.75: return "prob-high"
                if p <= 0.15: return "prob-low"
                if 0.40 <= p <= 0.60: return "prob-mid"
                return ""

            k_style = get_prob_style(market.kalshi_price)
            p_style = get_prob_style(market.poly_price)
            d_style = "delta-pos" if market.delta_percent > 0 else "delta-neg" if market.delta_percent < 0 else ""

            row_data = (
                market.event_name[:50],
                f"[{k_style}]{k_price}[/]" if k_style else k_price,
                f"[{p_style}]{p_price}[/]" if p_style else p_price,
                f"[{d_style}]{delta}[/]" if d_style else delta,
                vol
            )

            try:
                if key in table.rows:
                    table.update_row(key, row_data)
                else:
                    table.add_row(*row_data, key=key)
            except Exception:
                # Handle cases where row might have been removed or key mismatch
                pass

    async def action_refresh(self) -> None:
        """Fetch fresh data from clients."""
        self.query_one("#bot-message", Label).update("Refreshing market data...")
        k_markets = await self.kalshi.get_active_markets(limit=50)
        p_markets = await self.poly.get_active_markets(limit=50)
        await self.store.rebuild_from_feeds(k_markets, p_markets)
        self.query_one("#bot-message", Label).update("Data updated. Monitoring spreads.")

    async def action_filter(self, category: str) -> None:
        self.current_filter = category
        self._refresh_table()

    def action_focus_input(self):
        bar = self.query_one("#command-bar")
        bar.remove_class("hidden")
        self.query_one("#command-input").focus()

    def action_blur_input(self):
        bar = self.query_one("#command-bar")
        bar.add_class("hidden")
        self.query_one(DataTable).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        if cmd:
            await self._handle_command(cmd)
        event.input.value = ""
        self.action_blur_input()

    async def _handle_command(self, cmd: str):
        if cmd == "/refresh":
            await self.action_refresh()
        elif cmd == "/match":
            await self._load_local_matches()
        elif cmd == "/help":
            self.query_one("#bot-message", Label).update("Available: /refresh, /match, /search, /quit")
        elif cmd == "/quit":
            self.exit()
            
    async def _load_local_matches(self):
        """Load matches from the OpenClaw workspace file."""
        import json
        from pathlib import Path
        matches_file = Path.home() / ".openclaw" / "workspace" / "matches.json"
        
        if not matches_file.exists():
            self.query_one("#bot-message", Label).update(f"Error: {matches_file} not found.")
            return
            
        try:
            with open(matches_file) as f:
                matches = json.load(f)
            
            # Logic to inject these into the store would go here
            # For now, just notify success
            self.query_one("#bot-message", Label).update(f"Loaded {len(matches)} matches from local workspace.")
        except Exception as e:
            self.query_one("#bot-message", Label).update(f"Failed to load matches: {e}")
        
    async def _on_row_selected(self, event):
        row_key = event.row_key
        market = self.store.get_market(str(row_key))
        if market:
            details = f"[{market.event_name}] K:{market.kalshi_price:.2f} P:{market.poly_price:.2f} Δ:{market.delta_percent:+.1f}% Vol:{market.total_volume:,}"
            self.query_one("#bot-message", Label).update(details)

    async def on_unmount(self) -> None:
        await self.engine.stop()
        await self.agent.stop()
        await self.kalshi.close()
        await self.poly.close()

if __name__ == "__main__":
    app = PredictionTerminal()
    app.run()
