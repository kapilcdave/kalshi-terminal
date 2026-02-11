
from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.widgets import Header, Footer, DataTable, Static, Label, Digits, Sparkline, TabbedContent, TabPane
from textual.reactive import reactive
from textual.binding import Binding
import random
import asyncio
from kalshi_client import KalshiClient

class MarketDetail(Static):
    """Displays details for the selected market."""
    current_market = reactive(None)
    price_history = reactive([0.5] * 60) # Default flat line

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-inner"):
            yield Label("SELECT A MARKET", id="market-title")
            
            with Horizontal(id="price-container"):
                with Vertical(classes="price-box bid-box"):
                    yield Label("BID", classes="price-label")
                    yield Digits("00", id="yes-bid", classes="price-digit")
                
                with Vertical(classes="spark-container"):
                    yield Label("PRICE HISTORY (1H)", classes="chart-label")
                    yield Sparkline(self.price_history, summary_function=max)
                
                with Vertical(classes="price-box ask-box"):
                    yield Label("ASK", classes="price-label")
                    yield Digits("00", id="yes-ask", classes="price-digit")
            
            yield Label("VOLUME: --   OI: --", id="market-stats")

    def watch_current_market(self, market):
        if market:
            self.query_one("#market-title").update(f"{market.title}")
            self.update_price(market)
            # Simulate history based on current price
            # In real app, fetch candles
            base = getattr(market, 'yes_bid', 0.5) or 0.5
            self.price_history = [max(0.01, min(0.99, base + random.uniform(-0.05, 0.05))) for _ in range(60)]
            self.query_one(Sparkline).data = self.price_history
            
            vol = getattr(market, 'volume', 0)
            oi = getattr(market, 'open_interest', 0)
            self.query_one("#market-stats").update(f"VOLUME: {vol:,}   OI: {oi:,}")

    def update_price(self, market):
         if hasattr(market, 'yes_bid'):
            bid = int(market.yes_bid * 100)
            ask = int(market.yes_ask * 100)
            self.query_one("#yes-bid").update(f"{bid}")
            self.query_one("#yes-ask").update(f"{ask}")

class KalshiTerminal(App):
    CSS = """
    Screen {
        layout: vertical;
        background: #121212;
    }
    
    Header {
        background: #0d47a1;
        color: white;
        text-style: bold;
    }
    
    DataTable {
        height: 1fr;
        border: solid #333333;
        background: #1e1e1e;
    }
    
    DataTable > .datatable--header {
        text-style: bold;
        background: #263238;
        color: #cfd8dc;
    }
    
    DataTable > .datatable--cursor {
        background: #0d47a1;
        color: white;
    }
    
    #market-detail-container {
        height: 20;
        border-top: heavy #00e676;
        background: #1e1e1e;
        padding: 1;
    }
    
    #market-title {
        text-align: center;
        text-style: bold;
        color: #00e676;
        margin-bottom: 1;
        width: 100%;
        background: #263238;
        padding: 1;
    }
    
    #price-container {
        align: center middle;
        height: 10;
        margin-bottom: 1;
    }
    
    .price-box {
        width: 20;
        height: 100%;
        align: center middle;
        border: heavy #444444;
        margin: 0 1;
        background: #212121;
    }
    
    
    .bid-box { border: heavy #00e676; }
    .ask-box { border: heavy #ff1744; }

    
    .price-label { color: #888888; margin-bottom: 1; }
    .price-digit { color: white; }
    
    .spark-container {
        width: 40;
        height: 100%;
        margin: 0 2;
        align: center middle;
    }
    
    Sparkline {
        width: 100%;
        height: 5;
        color: #00e676;
    }
    
    .chart-label {
        color: #555555;
        margin-bottom: 1;
    }
    
    #market-stats {
        text-align: center;
        color: #90a4ae;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh Markets")
    ]

    def __init__(self):
        super().__init__()
        self.client = KalshiClient()
        self.markets = {} 

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="⚡")
        yield DataTable(id="market-table")
        yield Container(MarketDetail(id="market-detail"), id="market-detail-container")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("Ticker", "Title", "Vol", "Bid", "Ask")
        
        # Initial load
        await self.client.login()
        await self.action_refresh()

    async def action_refresh(self) -> None:
        table = self.query_one(DataTable)
        
        # Save cursor position if any
        cursor_row = table.cursor_row
        
        table.clear()
        
        # Fetch markets
        market_list = await self.client.get_active_markets(limit=50) # Increased limit
        self.markets = {m.ticker: m for m in market_list}
        
        rows = []
        for m in market_list:
            vol = getattr(m, 'volume', 0) or 0
            bid = getattr(m, 'yes_bid', 0.0) or 0.0
            ask = getattr(m, 'yes_ask', 0.0) or 0.0
            
            rows.append((
                m.ticker,
                m.title,
                str(vol),
                f"{bid:.2f}",
                f"{ask:.2f}"
            ))
            
        table.add_rows(rows)
        
        # Restore cursor if possible
        if cursor_row is not None and cursor_row < len(rows):
             table.move_cursor(row=cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._select_market(event.row_key)
        
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._select_market(event.row_key)

    def _select_market(self, row_key):
        table = self.query_one(DataTable)
        row = table.get_row(row_key)
        ticker = row[0]
        
        if ticker in self.markets:
            self.query_one("#market-detail").current_market = self.markets[ticker]

if __name__ == "__main__":
    app = KalshiTerminal()
    app.run()
