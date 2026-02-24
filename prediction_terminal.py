import os
import asyncio
import random
import time
from datetime import datetime
from typing import Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, DataTable, Static, Input, 
    RichLog, Label, Sparkline, Button
)
from textual.binding import Binding
from textual import work

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from market_matcher import UnifiedMarket
from unified_store import UnifiedStore
from live_engine import LiveEngine
from agent_manager import AgentManager


CSS_PATH = "prediction_terminal.tcss"


class TerminalHeader(Static):
    def compose(self) -> ComposeResult:
        with Horizontal(id="header-container"):
            yield Label("[P] PredictionTerminal", id="app-title")
            yield Label("|", classes="separator")
            yield Label("● LIVE", id="connection-status", classes="status-connected")
            yield Label("", id="latency")
            yield Label("", id="poly-balance")
            yield Label("", id="clock", classes="clock")


class MarketTablePane(Vertical):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_market_id: Optional[str] = None
        
    def compose(self) -> ComposeResult:
        yield Label("[ Unified Markets ]", classes="pane-title")
        yield DataTable(id="market-table")
        

class GraphPane(Vertical):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_market: Optional[UnifiedMarket] = None
        
    def compose(self) -> ComposeResult:
        yield Label("[ Price History ]", classes="pane-title")
        yield Sparkline(
            id="price-sparkline",
            data=[],
            summary=0,
            min=0,
            max=100
        )
        yield Label("", id="graph-details", classes="graph-details")


class ConsolePane(Vertical):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
    def compose(self) -> ComposeResult:
        yield Label("[ Clawdbot Console ]", classes="pane-title")
        yield RichLog(
            id="console-log",
            highlight=True,
            markup=True,
            auto_scroll=True
        )


class CommandInput(Input):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.placeholder = "Type /help for commands..."
        

class PredictionTerminal(App):
    CSS = """
    Screen {
        background: $surface;
    }
    
    #header-container {
        height: 1;
        background: $primary;
        dock: top;
        padding: 0 1;
    }
    
    #app-title {
        text-style: bold;
        color: $text;
    }
    
    .separator {
        color: $text-muted;
        margin: 0 1;
    }
    
    #connection-status {
        color: $success;
    }
    
    #connection-status.disconnected {
        color: $error;
    }
    
    .clock {
        width: 1fr;
        text-align: right;
        color: $text-muted;
    }
    
    #latency, #balance {
        color: $text-muted;
        margin-left: 2;
    }
    
    #main-layout {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-rows: 1fr 1fr;
    }
    
    .pane {
        border: solid $border;
        padding: 0;
    }
    
    .pane-title {
        background: $panel;
        color: $text;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    
    #market-table {
        height: 100%;
        background: $surface;
    }
    
    #market-table > .datatable--cursor {
        background: $primary-darken-1;
    }
    
    #market-table .datatable--header {
        background: $panel;
        color: $text;
    }
    
    #price-sparkline {
        height: 100%;
        background: $surface;
    }
    
    .graph-details {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    
    #console-log {
        height: 100%;
        background: $surface;
        color: $text;
    }
    
    #command-bar {
        height: 1;
        dock: bottom;
        background: $panel;
        padding: 0 1;
    }
    
    #command-input {
        width: 100%;
        background: $surface;
        color: $text;
    }
    
    #console-split {
        layout: grid;
        grid-size: 1 2;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('all')", "All"),
        Binding("f2", "filter('finance')", "Finance"),
        Binding("f3", "filter('politics')", "Politics"),
        Binding("f4", "filter('sports')", "Sports"),
        Binding("enter", "select_row", "Select"),
        Binding("/", "focus_input", "Command"),
        Binding("escape", "blur_input", "Clear"),
    ]
    
    def __init__(self):
        super().__init__()
        
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        
        self.store = UnifiedStore()
        
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
        
        self.current_filter = "all"
        
    def compose(self) -> ComposeResult:
        yield TerminalHeader()
        
        with Container(id="main-layout"):
            with Vertical(classes="pane", id="table-area"):
                yield MarketTablePane()
                
            with Vertical(classes="pane", id="graph-area"):
                yield GraphPane()

            with Vertical(classes="pane", id="console-area"):
                yield ConsolePane()
                
        with Horizontal(id="command-bar"):
            yield CommandInput(id="command-input")
            
        yield Footer()
        
    async def on_mount(self) -> None:
        await self._setup_tables()
        await self._setup_subscriptions()
        await self._setup_console()
        
        self.set_interval(1, self._update_clock)
        self.set_interval(60, self._update_balance) # Update balance every minute
        
        await self.engine.start()
        await self.agent.start()
        
        # Focus the table immediately for keyboard control
        self.query_one("#market-table").focus()
        
        await self.action_refresh()
        await self._update_balance()
        
    async def _setup_tables(self):
        table = self.query_one("#market-table", DataTable)
        table.add_columns(
            "Event", "Kalshi", "Poly", "Δ%", "Volume"
        )
        table.cursor_type = "row"
        
        # Use reactive highlight for instant graph updates
        table.on_row_highlighted = self._on_row_highlighted
        
    async def _setup_subscriptions(self):
        self.store.subscribe(self._on_market_update)
        
        self.engine.add_status_callback(self._on_connection_status)
        self.engine.add_price_callback(self._on_price_update)
        
    async def _setup_console(self):
        self.agent.add_output_callback(self._console_output)
        
        console = self.query_one("#console-log", RichLog)
        console.write(
            "[#00ff00 bold]Clawdbot v1.0[#00ff00] - Prediction Market Terminal",
            )
        console.write("[#666666]Initializing connections...[/]")
        
    def _console_output(self, text: str, style: str = "default"):
        console = self.query_one("#console-log", RichLog)
        
        if style == "success":
            console.write(f"[#00ff00]{text}")
        elif style == "warning":
            console.write(f"[#ffaa00]{text}")
        elif style == "error":
            console.write(f"[#ff0000]{text}")
        elif style == "user":
            console.write(f"[#00ffff]{text}")
        elif style == "assistant":
            console.write(f"[#ff00ff]{text}")
        else:
            console.write(text)
            
    async def _on_market_update(self, market: Optional[UnifiedMarket], change_type: str):
        if change_type == "rebuild_complete":
            await self._refresh_table()
            
    async def _on_connection_status(self, status):
        status_label = self.query_one("#connection-status", Label)
        
        if status.platform == "kalshi":
            if status.connected:
                status_label.update("● LIVE")
                status_label.classes = "status-connected"
            else:
                status_label.update("○ OFFLINE")
                status_label.classes = "disconnected"
                
        elif status.platform == "polymarket":
            latency_label = self.query_one("#latency", Label)
            latency_label.update(f"Latency: {status.latency_ms:.0f}ms")
            
    async def _on_price_update(self, platform: str, data: Dict):
        await self._refresh_table()
        
    async def _refresh_table(self):
        table = self.query_one("#market-table", DataTable)
        
        markets = self.store.get_all_markets()
        
        if self.current_filter != "all":
            markets = [m for m in markets 
                      if self.current_filter.lower() in m.normalized_name.lower()]
        
        markets.sort(key=lambda m: m.total_volume, reverse=True)
        
        existing_rows = set(table.rows.keys())
        current_rows = set()
        
        for market in markets[:50]:
            key = market.id
            current_rows.add(key)
            
            delta_str = f"{market.delta_percent:+.1f}%" if market.has_both_prices else "—"
            kalshi_str = f"{market.kalshi_price:.2f}" if market.kalshi_price > 0 else "—"
            poly_str = f"{market.poly_price:.2f}" if market.poly_price > 0 else "—"
            volume_str = f"{market.total_volume:,}"
            
            if key in existing_rows:
                table.update_row(
                    key,
                    (market.event_name[:35], kalshi_str, poly_str, delta_str, volume_str)
                )
            else:
                table.add_row(
                    market.event_name[:35],
                    kalshi_str,
                    poly_str,
                    delta_str,
                    volume_str,
                    key=key
                )
                
        for key in existing_rows - current_rows:
            table.remove_row(key)
            
    def _on_row_highlighted(self, event):
        row_key = event.row_key
        if row_key is not None:
            market = self.store.get_market(str(row_key))
            if market:
                # Trigger graph update and background history fetch
                self._update_graph(market)
                self._fetch_market_history(market)
                
    @work(exclusive=True)
    async def _fetch_market_history(self, market: UnifiedMarket):
        """Background worker to fetch historical data for the selected market."""
        # fetch from Polymarket
        if market.poly_token_id:
            history = await self.poly.get_prices_history(market.poly_token_id)
            if history:
                points = []
                for entry in history:
                    # entry has 'price' and 't' (timestamp in seconds)
                    points.append({
                        'price': float(entry.get('p', 0)),
                        'timestamp': int(entry.get('t', 0))
                    })
                await self.store.add_history_points(market.id, points, 'poly')
        
        # fetch from Kalshi
        if market.kalshi_ticker:
            now = int(time.time())
            start = now - (6 * 3600) # Last 6 hours
            candles = await self.kalshi.get_market_candlesticks(market.kalshi_ticker, start, now, period=60)
            if candles:
                points = []
                for c in candles:
                    points.append({
                        'price': c.close,
                        'timestamp': c.start_period_ts
                    })
                await self.store.add_history_points(market.id, points, 'kalshi')
        
        # Refresh graph if still on the same market
        table = self.query_one("#market-table", DataTable)
        if table.cursor_row is not None:
             highlighted_key = table.get_row_key_at(table.cursor_row)
             if str(highlighted_key) == market.id:
                 self.call_from_thread(self._update_graph, market)
                
    def _update_graph(self, market: UnifiedMarket):
        history = self.store.get_price_history(market.id)
        
        if not history:
            return
            
        kalshi_data = [p.kalshi_price * 100 if p.kalshi_price else 0 for p in history]
        poly_data = [p.poly_price * 100 if p.poly_price else 0 for p in history]
        
        sparkline = self.query_one("#price-sparkline", Sparkline)
        
        combined = []
        for i in range(len(kalshi_data)):
            k = kalshi_data[i] if i < len(kalshi_data) else 0
            p = poly_data[i] if i < len(poly_data) else 0
            combined.append(max(k, p))
            
        if combined:
            sparkline.data = combined
            sparkline.min = 0
            sparkline.max = 100
            
        details = self.query_one("#graph-details", Label)
        details.update(
            f"{market.event_name[:40]} | K: {market.kalshi_price:.2f} | P: {market.poly_price:.2f}"
        )
        
    async def _update_balance(self):
        try:
            balance = await self.poly.get_balance()
            if balance > 0:
                self.query_one("#poly-balance", Label).update(f"Poly Balance: ${balance:,.2f}")
            else:
                self.query_one("#poly-balance", Label).update("")
        except Exception:
            pass

    def _update_clock(self):
        try:
            clock = self.query_one("#clock", Label)
            clock.update(datetime.now().strftime("%H:%M:%S"))
        except:
            pass
            
    async def action_refresh(self) -> None:
        k_markets = await self.kalshi.get_active_markets(limit=50)
        p_markets = await self.poly.get_active_markets(limit=50)
        
        await self.store.rebuild_from_feeds(k_markets, p_markets)
        await self._refresh_table()
        
    async def action_filter(self, category: str) -> None:
        self.current_filter = category
        await self._refresh_table()
        
    async def action_select_row(self) -> None:
        table = self.query_one("#market-table", DataTable)
        row_key = table.cursor_row
        
    def action_focus_input(self):
        self.query_one("#command-input", Input).focus()
        
    def action_blur_input(self):
        self.query_one("#command-input", Input).blur()
        
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        
        if not command:
            return
            
        if command.startswith("/"):
            await self._handle_command(command)
        elif command.startswith("?"):
            await self.agent.process_message(command[1:])
        else:
            await self.agent.process_message(command)
            
        event.input.value = ""
        
    async def _handle_command(self, command: str):
        parts = command.split()
        cmd = parts[0].lower()
        
        console = self.query_one("#console-log", RichLog)
        
        if cmd == "/help":
            console.write("""
[#00ffff]Available Commands:[/]
  /help     - Show this help
  /refresh  - Refresh market data
  /spreads  - Show markets with spreads > 3%
  /buy      - Simulate buy order
  /balance  - Show account balance
  /clear    - Clear console
  /quit     - Exit terminal
            """)
            
        elif cmd == "/refresh":
            await self.action_refresh()
            console.write("[#00ff00]Market data refreshed[/#00ff00]")
            
        elif cmd == "/spreads":
            markets = self.store.get_markets_with_spread(3.0)
            
            if not markets:
                console.write("[#666666]No significant spreads found[/#666666]")
            else:
                console.write(f"[#ffaa00]Found {len(markets)} spread opportunities:[/]")
                for m in markets[:10]:
                    console.write(
                        f"  {m.event_name[:30]}: {m.delta_percent:+.1f}% "
                        f"(K:{m.kalshi_price:.2f} P:{m.poly_price:.2f})"
                    )
                    
        elif cmd == "/buy":
            console.write("[#ffaa00]Buy order simulation - feature coming soon[/#ffaa00]")
            
        elif cmd == "/balance":
            console.write("[#00ffff]Balance: $10,000.00 (demo mode)[/#00ffff]")
            
        elif cmd == "/clear":
            console.clear()
            
        elif cmd == "/quit":
            self.exit()
            
        else:
            console.write(f"[#ff0000]Unknown command: {cmd}[/#ff0000]")
            
    async def on_unmount(self) -> None:
        await self.engine.stop()
        await self.agent.stop()
        await self.kalshi.close()
        await self.poly.close()


if __name__ == "__main__":
    app = PredictionTerminal()
    app.run()
