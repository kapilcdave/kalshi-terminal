import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import DataTable, Static, Input, Footer, Header
from textual.binding import Binding
from textual import events
from textual.message import Message

MATCHES_FILE = Path.home() / ".openclaw" / "workspace" / "matches.json"


class MarketData:
    def __init__(self, event: str, kalshi_prob: float, poly_prob: float, 
                 volume: int, category: str = "other"):
        self.event = event
        self.kalshi_prob = kalshi_prob
        self.poly_prob = poly_prob
        self.volume = volume
        self.category = category
        
    @property
    def delta_pct(self) -> float:
        if self.kalshi_prob == 0:
            return 0.0
        return ((self.poly_prob - self.kalshi_prob) / self.kalshi_prob) * 100
    
    def format_volume(self) -> str:
        if self.volume >= 1_000_000:
            return f"{self.volume / 1_000_000:.1f}M"
        elif self.volume >= 1_000:
            return f"{self.volume / 1_000:.1f}K"
        return str(self.volume)


class HeaderTicker(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ticker_data = [
            {"symbol": "SPX", "price": 5234.5, "change": -0.12},
            {"symbol": "BTC", "price": 67890.0, "change": 2.34},
            {"symbol": "DXY", "price": 104.2, "change": -0.05},
            {"symbol": "NDX", "price": 18500.0, "change": 0.45},
            {"symbol": "ETH", "price": 3450.0, "change": 1.87},
        ]
        self._ticks = 0
        
    def on_mount(self):
        self.update_ticker()
        self.set_interval(3, self.update_ticker)
        
    def update_ticker(self):
        self._ticks = (self._ticks + 1) % len(self._ticker_data)
        parts = []
        for item in self._ticker_data:
            symbol = item["symbol"]
            price = item["price"]
            change = item["change"]
            change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
            color = "#a6e3a1" if change >= 0 else "#f38ba8"
            parts.append(f"[bold]{symbol}[/bold] @ {price:,.0f}  [{color}]{change_str}[/{color}]")
        
        self.update("  " + "  │  ".join(parts) + "  ")


class MarketDataTable(DataTable):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_columns(
            ("Event", "event"),
            ("Kalshi", "kalshi"),
            ("Poly", "poly"),
            ("Δ%", "delta"),
            ("Volume", "volume")
        )
        self.cursor_type = "row"
        
    def get_probability_color(self, prob: float) -> str:
        if prob >= 0.75:
            return "#a6e3a1"
        elif prob <= 0.15:
            return "#f38ba8"
        elif 0.40 <= prob <= 0.60:
            return "#f9e2af"
        return "#cdd6f4"
    
    def get_delta_color(self, delta: float) -> str:
        if delta > 0:
            return "#a6e3a1"
        elif delta < 0:
            return "#f38ba8"
        return "#cdd6f4"


class CommandBar(Static):
    class CommandSubmitted(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command
            
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._input = Input(
            placeholder="Type /help for commands...",
            classes="command-input"
        )
        
    def compose(self) -> ComposeResult:
        yield self._input
        
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.value:
            self.post_message(self.CommandSubmitted(event.input.value))
            self._input.value = ""
    
    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self._input.value = ""
            self._input.focus(False)


class ClawdbotStatus(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._message = "Initialized and monitoring markets..."
        
    def on_mount(self):
        self.update_status()
        
    def update_status(self, message: Optional[str] = None):
        if message:
            self._message = message
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.update(f" 🦞 [bold cyan]Clawdbot v1.0[/bold cyan] │ {timestamp} │ {self._message}")


class PredictionMarketApp(App):
    CSS_PATH = "app.css"
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh_data", "Refresh", show=True),
        Binding("f1", "filter_category('all')", "All", show=True),
        Binding("f2", "filter_category('finance')", "Finance", show=True),
        Binding("f3", "filter_category('politics')", "Politics", show=True),
        Binding("f4", "filter_category('sports')", "Sports", show=True),
        Binding("/", "focus_command", "Command", show=True),
        Binding("escape", "clear_focus", "Clear", show=True),
        Binding("enter", "show_details", "Details", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self.current_category = "all"
        self.all_markets: list[MarketData] = []
        self.filtered_markets: list[MarketData] = []
        self._selected_row = 0
        
    def compose(self) -> ComposeResult:
        yield HeaderTicker(id="ticker")
        
        with Container(id="main"):
            yield MarketDataTable(id="market-table")
            
        yield ClawdbotStatus(id="clawdbot-status")
        
        with Horizontal(id="command-bar"):
            yield CommandBar(id="command-input")
            
        yield Footer()
        
    def on_mount(self) -> None:
        self.load_sample_data()
        self.populate_table()
        self.query_one("#clawdbot-status", ClawdbotStatus).update_status(
            f"Loaded {len(self.all_markets)} matched markets"
        )
        
    def load_sample_data(self):
        if MATCHES_FILE.exists():
            try:
                with open(MATCHES_FILE) as f:
                    data = json.load(f)
                    for item in data:
                        market = MarketData(
                            event=item.get("event", "Unknown"),
                            kalshi_prob=item.get("kalshi_prob", 0),
                            poly_prob=item.get("poly_prob", 0),
                            volume=item.get("volume", 0),
                            category=item.get("category", "other")
                        )
                        self.all_markets.append(market)
                    return
            except Exception:
                pass
        
        self.all_markets = [
            MarketData("Harden 3+ 3PTs", 0.75, 0.72, 1200, "sports"),
            MarketData("Trump deported", 0.03, 0.04, 8500, "politics"),
            MarketData("GTA VI $100M+", 0.01, 0.02, 450, "entertainment"),
            MarketData("Fed rate cut Q1", 0.65, 0.68, 5200, "finance"),
            MarketData("BTC $100K by EOY", 0.42, 0.45, 15000, "finance"),
            MarketData("Election winner Dem", 0.48, 0.51, 25000, "politics"),
            MarketData("Super Bowl winner", 0.55, 0.52, 8000, "sports"),
            MarketData("NVDA $200+", 0.82, 0.78, 3200, "finance"),
            MarketData("China Taiwan invasion", 0.08, 0.11, 1800, "politics"),
            MarketData("Oscar Best Picture", 0.35, 0.38, 900, "entertainment"),
            MarketData("Oil $100/barrel", 0.28, 0.25, 2100, "finance"),
            MarketData("NBA champion", 0.22, 0.19, 4500, "sports"),
            MarketData("UK recession 2026", 0.18, 0.21, 650, "finance"),
            MarketData("Elon Mars 2026", 0.05, 0.07, 3200, "entertainment"),
            MarketData("Harris VP pick", 0.62, 0.58, 4100, "politics"),
        ]
        
    def populate_table(self):
        table = self.query_one("#market-table", MarketDataTable)
        table.clear()
        
        self.filtered_markets = [
            m for m in self.all_markets 
            if self.current_category == "all" or m.category == self.current_category
        ]
        
        for market in self.filtered_markets:
            kalshi_color = table.get_probability_color(market.kalshi_prob)
            poly_color = table.get_probability_color(market.poly_prob)
            delta_color = table.get_delta_color(market.delta_pct)
            
            delta_str = f"+{market.delta_pct:.0f}%" if market.delta_pct >= 0 else f"{market.delta_pct:.0f}%"
            
            table.add_row(
                market.event,
                f"[{kalshi_color}]{market.kalshi_prob:.2f}[/{kalshi_color}]",
                f"[{poly_color}]{market.poly_prob:.2f}[/{poly_color}]",
                f"[{delta_color}]{delta_str}[/{delta_color}]",
                market.format_volume()
            )
            
    def action_filter_category(self, category: str) -> None:
        self.current_category = category
        self.populate_table()
        status = self.query_one("#clawdbot-status", ClawdbotStatus)
        status.update_status(f"Filtered to {category} ({len(self.filtered_markets)} markets)")
        
    def action_refresh_data(self) -> None:
        self.load_sample_data()
        self.populate_table()
        status = self.query_one("#clawdbot-status", ClawdbotStatus)
        status.update_status(f"Refreshed {len(self.all_markets)} markets")
        
    def action_focus_command(self) -> None:
        self.query_one("#command-input", CommandBar).query_one(Input).focus()
        
    def action_clear_focus(self) -> None:
        self.query_one("#command-input", CommandBar).query_one(Input).blur()
        
    def action_show_details(self) -> None:
        table = self.query_one("#market-table", MarketDataTable)
        cursor = table.cursor_row
        if cursor < len(self.filtered_markets):
            market = self.filtered_markets[cursor]
            status = self.query_one("#clawdbot-status", ClawdbotStatus)
            status.update_status(
                f"Selected: {market.event} | K:{market.kalshi_prob:.0%} P:{market.poly_prob:.0%} Δ:{market.delta_pct:+.0f}%"
            )
            
    def on_market_data_table_row_selected(self, event) -> None:
        self.action_show_details()


if __name__ == "__main__":
    app = PredictionMarketApp()
    app.run()
