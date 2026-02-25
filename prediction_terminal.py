import os
import asyncio
import random
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





class TerminalHeader(Horizontal):
    def compose(self) -> ComposeResult:
        yield Label("[P] PredictionTerminal", id="app-title")
        yield Label("|", classes="separator")
        yield Label("● LIVE", id="connection-status", classes="status-connected")
        yield Label("", id="latency")
        yield Label("", id="balance")
        yield Label("", id="clock", classes="clock")


class KalshiTablePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("[ KALSHI (USD) ]", classes="pane-title")
        yield DataTable(id="kalshi-table")

class PolyTablePane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("[ POLYMARKET (USDC) ]", classes="pane-title")
        yield DataTable(id="poly-table")
        

class GraphPane(Vertical):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_market: Optional[UnifiedMarket] = None
        
    def compose(self) -> ComposeResult:
        yield Label("[ Price History ]", classes="pane-title")
        yield Sparkline(
            id="price-sparkline",
            data=[]
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
        background: #0a0a0a;
        color: #e0e0e0;
    }
    
    #header-container {
        height: 1;
        background: #161b22;
        dock: top;
        padding: 0 1;
        border-bottom: solid #00ffff;
    }
    
    #app-title {
        text-style: bold;
        color: #00ffff;
    }
    
    .clock {
        width: 1fr;
        text-align: right;
        color: #00ff00;
    }
    
    .separator {
        color: $text-muted;
        margin: 0 1;
    }
    
    #connection-status {
        color: #00ff00;
        text-style: bold;
    }
    
    #connection-status.disconnected {
        color: #ff3333;
    }
    
    .clock {
        width: 1fr;
        text-align: right;
        color: #00ff00;
    }
    
    #main-layout {
        height: 1fr;
    }
    
    .pane {
        width: 1fr;
        height: 100%;
        border: solid #333333;
        background: #0a0a0a;
    }
    
    #side-column {
        width: 1fr;
        height: 100%;
    }
    
    #side-column .pane {
        width: 100%;
        height: 1fr;
    }
    
    #price-sparkline {
        height: 1fr;
        color: #00ff00;
        background: #0a0a0a;
    }
    
    #console-log {
        height: 1fr;
        background: #0a0a0a;
        color: #e0e0e0;
    }
    
    #command-bar {
        height: 1;
        dock: bottom;
        background: #161b22;
        padding: 0 1;
        border-top: solid #333333;
    }
    
    #command-logo {
        color: #00ffff;
        text-style: bold;
        margin-right: 1;
    }
    
    #command-input {
        width: 1fr;
        background: transparent;
        color: #e0e0e0;
        border: none;
    }
    
    .separator {
        color: #666666;
        margin: 0 1;
    }
    
    #latency, #balance {
        color: #888888;
        margin-left: 2;
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
            kalshi_private_key=self.kalshi.private_key_content if not self.kalshi.use_mock else None,
            kalshi_client=self.kalshi
        )
        
        self.agent = AgentManager(
            store=self.store,
            api_key=os.getenv("OPENROUTER_API_KEY")
        )
        
        self.current_filter = "all"
        
    def compose(self) -> ComposeResult:
        yield TerminalHeader(id="header-container")
        
        with Horizontal(id="main-layout"):
            with Vertical(classes="pane"):
                yield KalshiTablePane()
                
            with Vertical(classes="pane"):
                yield PolyTablePane()
                
            with Vertical(id="side-column"):
                with Vertical(classes="pane"):
                    yield GraphPane()
                with Vertical(classes="pane"):
                    yield ConsolePane()
                
        with Horizontal(id="command-bar"):
            yield Label("🦀 Clawdbot:", id="command-logo")
            yield CommandInput(id="command-input")
            
        yield Footer()
        
    async def on_mount(self) -> None:
        await self._setup_tables()
        await self._setup_subscriptions()
        await self._setup_console()
        
        self.set_interval(1, self._update_clock)
        
        # Start engine and agent in background to avoid blocking initial render
        self._start_services()
        
    @work
    async def _start_services(self):
        await self.engine.fetch_initial_markets()
        await self.engine.start()
        await self.agent.start()
        await self.action_refresh()
        
    async def _setup_tables(self):
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.add_columns("Ticker", "Price", "Vol")
        k_table.cursor_type = "row"
        k_table.on_row_selected = self._on_row_selected
        
        p_table = self.query_one("#poly-table", DataTable)
        p_table.add_columns("Question", "Price", "Vol")
        p_table.cursor_type = "row"
        p_table.on_row_selected = self._on_row_selected
        
    async def _setup_subscriptions(self):
        self.store.subscribe(self._on_market_update)
        
        self.engine.add_status_callback(self._on_connection_status)
        self.engine.add_price_callback(self._on_price_update)
        
    async def _setup_console(self):
        self.agent.add_output_callback(self._console_output)
        
        console = self.query_one("#console-log", RichLog)
        console.write(
            "🦀 [#00ff00 bold]Clawdbot v2.0[#00ff00] - OpenRouter Powered",
            )
        console.write("[#666666]Ready for analysis. Press / to command.[/]")
        
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
            
    async def _refresh_table(self):
        # Refresh Kalshi Table
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.clear()
        k_markets = await self.kalshi.get_active_markets(limit=30)
        for m in k_markets:
            price = 0
            yes_bid = getattr(m, 'yes_bid', 0) or 0
            yes_ask = getattr(m, 'yes_ask', 0) or 0
            if yes_bid > 0 and yes_ask > 0: price = (yes_bid + yes_ask) / 2 / 100
            k_table.add_row(m.ticker[:20], f"{price:.2f}", f"{getattr(m, 'volume', 0):,}", key=m.ticker)

        # Refresh Poly Table
        p_table = self.query_one("#poly-table", DataTable)
        p_table.clear()
        p_markets = await self.poly.get_active_markets(limit=30)
        for m in p_markets:
            prices = m.get('outcomePrices', [])
            price = float(prices[0]) if (isinstance(prices, list) and len(prices) > 0) else 0
            p_table.add_row(m.get('question', '')[:30], f"{price:.2f}", f"{int(float(m.get('volume', 0) or 0)):,}", key=str(m.get('id')))
            
    async def _on_market_update(self, market: Optional[UnifiedMarket], change_type: str):
        # We'll refresh both for now on major changes
        if change_type == "rebuild_complete":
            await self._refresh_table()
            
    async def _on_connection_status(self, status):
        status_label = self.query_one("#connection-status", Label)
        
        if status.platform == "kalshi":
            if status.connected:
                status_label.update("● LIVE")
            else:
                status_label.update("○ OFFLINE")
                
        elif status.platform == "polymarket":
            latency_label = self.query_one("#latency", Label)
            latency_label.update(f"Lat: {status.latency_ms:.0f}ms")
            
    async def _on_price_update(self, platform: str, data: Dict):
        await self._refresh_table()
        
    async def _refresh_table(self):
        try:
            markets = self.store.get_all_markets()
            
            # Refresh Kalshi Table
            k_table = self.query_one("#kalshi-table", DataTable)
            k_table.clear()
            k_list = [m for m in markets if m.kalshi_ticker]
            k_list.sort(key=lambda m: m.kalshi_volume, reverse=True)
            for m in k_list[:30]:
                k_table.add_row(
                    m.kalshi_ticker, 
                    f"{m.kalshi_price:.2f}" if m.kalshi_price else "—", 
                    f"{m.kalshi_volume:,}", 
                    key=m.id
                )

            # Refresh Poly Table
            p_table = self.query_one("#poly-table", DataTable)
            p_table.clear()
            p_list = [m for m in markets if m.poly_token_id]
            p_list.sort(key=lambda m: m.poly_volume, reverse=True)
            for m in p_list[:30]:
                p_table.add_row(
                    m.event_name[:25], 
                    f"{m.poly_price:.2f}" if m.poly_price else "—", 
                    f"{int(m.poly_volume):,}", 
                    key=m.id
                )
        except Exception:
            pass
            
    def _on_row_selected(self, event):
        table = event.data_table
        row_key = event.row_key.value
        
        market = self.store.get_market(str(row_key))
        if market:
            self._update_graph(market)
            self._console_output(f"Selected: {market.event_name}", "user")
            
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
