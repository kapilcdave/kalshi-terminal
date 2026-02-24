import json
from pathlib import Path
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Input, Footer
from textual.binding import Binding
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
    def on_mount(self):
        self._ticker_data = [
            {"symbol": "SPX", "price": 5234.5, "change": -0.12},
            {"symbol": "BTC", "price": 67890.0, "change": 2.34},
            {"symbol": "DXY", "price": 104.2, "change": -0.05},
            {"symbol": "NDX", "price": 18500.0, "change": 0.45},
            {"symbol": "ETH", "price": 3450.0, "change": 1.87},
        ]
        self.update_ticker()
        self.set_interval(5, self.update_ticker)
        
    def update_ticker(self):
        parts = []
        for item in self._ticker_data:
            symbol = item["symbol"]
            price = item["price"]
            change = item["change"]
            change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
            color = "#a6e3a1" if change >= 0 else "#f38ba8"
            parts.append(f"[bold]{symbol}[/bold] @ {price:,.0f}  [{color}]{change_str}[/{color}]")
        self.update("  " + " │ ".join(parts) + "  ")


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


class CommandInput(Input):
    pass


class PredictionMarketApp(App):
    CSS_PATH = "app.css"
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh_data", "Refresh", show=True),
        Binding("f1", "filter_category('all')", "All", show=True),
        Binding("f2", "filter_category('finance')", "Finance", show=True),
        Binding("f3", "filter_category('politics')", "Politics", show=True),
        Binding("f4", "filter_category('sports')", "Sports", show=True),
        Binding("/", "focus_command", "Cmd", show=True),
        Binding("escape", "clear_focus", "Clear", show=True),
        Binding("enter", "show_details", "Details", show=False),
    ]
    
    def __init__(self):
        super().__init__()
        self.current_category = "all"
        self.all_markets: list[MarketData] = []
        self.filtered_markets: list[MarketData] = []
        
    def compose(self) -> ComposeResult:
        yield HeaderTicker(id="ticker")
        yield MarketDataTable(id="market-table")
        yield Static(" 🦞 [bold cyan]Clawdbot v1.0[/bold cyan] │ Initialized and monitoring markets...", id="clawdbot-status")
        yield CommandInput(placeholder="Type /help for commands...", id="command-input")
        yield Footer()
        
    def on_mount(self) -> None:
        self.load_data()
        self.populate_table()
        self.set_focus(self.query_one("#market-table"))
        
    def load_data(self):
        self.all_markets = []
        
        if MATCHES_FILE.exists():
            try:
                with open(MATCHES_FILE) as f:
                    data = json.load(f)
                    for item in data:
                        event = item.get("event") or item.get("kalshi_title") or "Unknown"
                        kalshi = item.get("kalshi_prob", 0)
                        poly = item.get("poly_prob", 0) or item.get("polymarket_prob", 0)
                        volume = item.get("volume", 0)
                        category = item.get("category", "other")
                        
                        if kalshi and poly:
                            self.all_markets.append(MarketData(event, kalshi, poly, volume, category))
            except Exception as e:
                pass
        
        if not self.all_markets:
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
            ]
        
        self.update_status(f"Loaded {len(self.all_markets)} matched markets")
        
    def get_prob_color(self, prob: float) -> str:
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
        
    def populate_table(self):
        table = self.query_one("#market-table", MarketDataTable)
        table.clear()
        
        self.filtered_markets = [
            m for m in self.all_markets 
            if self.current_category == "all" or m.category == self.current_category
        ]
        
        for market in self.filtered_markets:
            kalshi_color = self.get_prob_color(market.kalshi_prob)
            poly_color = self.get_prob_color(market.poly_prob)
            delta_color = self.get_delta_color(market.delta_pct)
            
            delta_str = f"+{market.delta_pct:.0f}%" if market.delta_pct >= 0 else f"{market.delta_pct:.0f}%"
            
            table.add_row(
                market.event,
                f"[{kalshi_color}]{market.kalshi_prob:.2f}[/{kalshi_color}]",
                f"[{poly_color}]{market.poly_prob:.2f}[/{poly_color}]",
                f"[{delta_color}]{delta_str}[/{delta_color}]",
                market.format_volume()
            )
            
    def update_status(self, message: str):
        self.query_one("#clawdbot-status", Static).update(
            f" 🦞 [bold cyan]Clawdbot v1.0[/bold cyan] │ {datetime.now().strftime('%H:%M:%S')} │ {message}"
        )
        
    def action_filter_category(self, category: str) -> None:
        self.current_category = category
        self.populate_table()
        self.update_status(f"Filtered to {category} ({len(self.filtered_markets)} markets)")
        
    def action_refresh_data(self) -> None:
        self.load_data()
        self.populate_table()
        
    def action_focus_command(self) -> None:
        self.query_one("#command-input", CommandInput).focus()
        
    def action_clear_focus(self) -> None:
        self.set_focus(self.query_one("#market-table"))
        
    def action_show_details(self) -> None:
        table = self.query_one("#market-table", MarketDataTable)
        cursor = table.cursor_row
        if cursor < len(self.filtered_markets):
            market = self.filtered_markets[cursor]
            self.update_status(
                f"Selected: {market.event} | K:{market.kalshi_prob:.0%} P:{market.poly_prob:.0%} Δ:{market.delta_pct:+.0f}%"
            )
            
    def on_market_data_table_row_selected(self, event) -> None:
        self.action_show_details()
        
    def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.input.value.strip().lower()
        if cmd == "/help":
            self.update_status("Commands: /help /refresh /search <term>")
        elif cmd == "/refresh":
            self.action_refresh_data()
            self.update_status("Data refreshed")
        elif cmd.startswith("/search "):
            query = cmd[8:].lower()
            results = [m.event for m in self.all_markets if query in m.event.lower()]
            self.update_status(f"Found: {', '.join(results[:5]) if results else 'No matches'}")
        else:
            self.update_status(f"Unknown: {cmd}")
        event.input.value = ""


if __name__ == "__main__":
    app = PredictionMarketApp()
    app.run()
