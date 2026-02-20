import os
import asyncio
import re
import json
from datetime import datetime
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer, Grid
from textual.widgets import Footer, DataTable, Static, Label
from textual.reactive import reactive
from textual.binding import Binding
from textual import events

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient

load_dotenv()

THEMES = ["nord", "gruvbox", "tokyo-night", "textual-dark", "solarized-dark", "monokai", "dracula", "catppuccin-mocha"]

class MarketClassifier:
    CATEGORIES = {
        "politics": [r"\btrump\b", r"\bbiden\b", r"\bpresident\b", r"\belection\b", r"\bcongress\b", r"\bsenate\b", r"\bhouse\b", r"\bdemocrat\b", r"\brepublican\b", r"\bgov\b", r"\bsenator\b", r"\brussia\b", r"\bukraine\b", r"\bisrael\b", r"\bchina\b", r"\biran\b"],
        "sports": [r"\bnba\b", r"\bnfl\b", r"\bmlb\b", r"\bnhl\b", r"\bcollege\b", r"\bfootball\b", r"\bbasketball\b", r"\bbaseball\b", r"\bhockey\b", r"\bsoccer\b", r"\bgolf\b", r"\btennis\b", r"\bATP\b", r"\bNCAAB\b", r"\b3pt\b", r"\bgame\b", r"\bwin\b", r"\bplayoff\b"],
        "financial": [r"\bfed\b", r"\binterest\b", r"\brate\b", r"\binflation\b", r"\bgdp\b", r"\bmarket\b", r"\bstock\b", r"\bbitcoin\b", r"\bbtc\b", r"\bcrypto\b", r"\brecession\b", r"\beconomy\b", r"\bdoge\b", r"\bbudget\b", r"\brevenue\b"],
        "entertainment": [r"\boscar\b", r"\bgrammy\b", r"\bemmy\b", r"\bmovie\b", r"\bnetflix\b", r"\bdisney\b", r"\bgta\b", r"\balbum\b", r"\bmusic\b"],
    }
    
    CAT_LABELS = {"politics": "POL", "sports": "SPO", "financial": "FIN", "entertainment": "ENT"}
    
    @classmethod
    def classify(cls, text: str) -> str | None:
        text = text.lower()
        for category, patterns in cls.CATEGORIES.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return category
        return None

    @classmethod
    def label(cls, cat: str) -> str:
        return cls.CAT_LABELS.get(cat, "OTH")

class Header(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def on_mount(self):
        self.update(" POLYTERMINAL ")

class MarketCard(Static):
    def __init__(self, title: str, price: float, category: str, platform: str, market_data: dict = None, content: str = "", **kwargs):
        super().__init__(content, **kwargs)
        self.market_title = title
        self.market_price = price
        self.market_category = category
        self.platform = platform
        self.market_data = market_data or {}
        self.is_selected = False

    def get_color(self, price: float) -> str:
        if price >= 0.75:
            return "high"
        elif price <= 0.15:
            return "low"
        elif 0.40 <= price <= 0.60:
            return "mid"
        return "default"

    def render(self) -> str:
        cat_label = MarketClassifier.label(self.market_category)
        color = self.get_color(self.market_price)
        price_str = f"{self.market_price:.2f}"
        title = self.market_title[:28] + "..." if len(self.market_title) > 28 else self.market_title
        sel = "▶" if self.is_selected else " "
        return f"{sel}[{cat_label}] {title:<30} {price_str:>5}"

    def on_click(self) -> None:
        self.is_selected = not self.is_selected
        self.refresh()
        self.app.selected_market = self.market_data
        self.app.show_graph_panel(self.market_data)

class Ticker(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ticks = 0

    def on_mount(self):
        self.update_ticker()
        self.set_interval(5, self.update_ticker)

    def update_ticker(self):
        self._ticks = (self._ticks + 1) % 4
        ticks = ["▓▒░ ", "░▓▒ ", "▒░▓ ", "▓▒░ "]
        now = datetime.now().strftime("%H:%M:%S")
        self.update(f" POLYTERMINAL | {now} {ticks[self._ticks]}")

class PolyTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('financial')", "Finance"),
        Binding("f2", "filter('politics')", "Politics"),
        Binding("f3", "filter('sports')", "Sports"),
        Binding("f4", "filter('entertainment')", "Entertainment"),
        Binding("f5", "filter('all')", "All"),
        Binding("t", "next_theme", "Theme"),
        Binding("g", "toggle_graph", "Graph"),
        Binding("escape", "close_graph", "Close"),
    ]

    current_niche = reactive("all")
    current_theme_idx = reactive(0)
    selected_market = reactive(None)
    show_graph = reactive(False)

    def __init__(self):
        super().__init__()
        self.theme = "nord"
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.k_markets = []
        self.p_markets = []
        self._market_data_map = {}

    def compose(self) -> ComposeResult:
        yield Ticker(id="ticker")
        
        with Horizontal(id="main"):
            with ScrollableContainer(id="kalshi-pane", classes="pane"):
                yield Static("KALSHI", classes="pane-header")
                yield Vertical(id="kalshi-markets")
            with ScrollableContainer(id="poly-pane", classes="pane"):
                yield Static("POLYMARKET", classes="pane-header")
                yield Vertical(id="poly-markets")
            with Vertical(id="graph-pane", classes="pane hidden"):
                yield Static("CHART", classes="pane-header")
                yield Vertical(id="graph-content")
        
        yield Footer()

    CSS = """
    Screen { background: $surface; }
    
    #ticker {
        height: 1;
        dock: top;
        background: $primary;
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    
    #main {
        height: 1fr;
    }
    
    .pane {
        width: 1fr;
        height: 100%;
        border: solid $border;
    }
    
    .pane.hidden {
        display: none;
    }
    
    #kalshi-pane { border-left: none; }
    
    .pane-header {
        height: 1;
        dock: top;
        content-align: center middle;
        text-style: bold;
        background: $panel;
        color: $accent;
    }
    
    .market-card {
        height: 1;
        padding: 0 1;
        layout: horizontal;
    }
    
    .market-card:hover {
        background: $panel;
    }
    
    .market-card.selected {
        background: $primary;
    }
    
    .cat { text-style: bold; }
    .cat-POL { color: $accent; }
    .cat-SPO { color: $success; }
    .cat-FIN { color: $warning; }
    .cat-ENT { color: $error; }
    .cat-OTH { color: $text-muted; }
    
    .price-high { color: #a6e3a1; }
    .price-mid { color: #f9e2af; }
    .price-low { color: #f38ba8; }
    .price-default { color: $text; }
    
    .title { color: $text; }
    
    #graph-pane {
        width: 40%;
    }
    
    .graph-title {
        color: $text;
        text-style: bold;
        padding: 1 2;
    }
    
    .graph-price {
        color: $accent;
        text-style: bold;
        padding: 0 2;
    }
    
    .graph-sparkline {
        color: $success;
        padding: 1 2;
    }
    
    Footer { background: $panel; }
    """

    async def on_mount(self) -> None:
        await self.kalshi.login()
        await self.action_refresh()

    async def action_refresh(self) -> None:
        k_task = asyncio.create_task(self.refresh_kalshi())
        p_task = asyncio.create_task(self.refresh_poly())
        await asyncio.gather(k_task, p_task)

    async def refresh_kalshi(self):
        container = self.query_one("#kalshi-markets", Vertical)
        container.remove_children()
        
        markets = await self.kalshi.get_active_markets(limit=100)
        
        for m in markets:
            title = getattr(m, 'title', m.ticker) or m.ticker
            cat = MarketClassifier.classify(title) or "other"
            
            if self.current_niche != "all" and cat != self.current_niche:
                continue
            
            yes_bid = getattr(m, 'yes_bid', 0) or 0
            yes_ask = getattr(m, 'yes_ask', 0) or 0
            price = (yes_bid + yes_ask) / 2 / 100 if (yes_bid or yes_ask) else 0
            
            cat_label = MarketClassifier.label(cat)
            price_color = "price-high" if price >= 0.75 else "price-low" if price <= 0.15 else "price-mid" if 0.40 <= price <= 0.60 else "price-default"
            title_short = title[:35] + "..." if len(title) > 35 else title
            
            market_data = {
                "title": title,
                "price": price,
                "platform": "kalshi",
                "ticker": getattr(m, 'ticker', ''),
                "category": cat,
                "history": [price] * 10,
            }
            
            card = MarketCard(
                title_short, price, cat, "kalshi", market_data,
                f"[cat-{cat_label}][{cat_label}][/{cat_label}] [title]{title_short:<38}[/title] [{price_color}]{price:>5.2f}[/{price_color}]",
                classes="market-card"
            )
            container.mount(card)

    async def refresh_poly(self):
        container = self.query_one("#poly-markets", Vertical)
        container.remove_children()
        
        markets = await self.poly.get_active_markets(limit=100)
        
        for m in markets:
            question = m.get('question', 'Unknown')
            cat = MarketClassifier.classify(question) or "other"
            
            if self.current_niche != "all" and cat != self.current_niche:
                continue
            
            prices = m.get('outcomePrices', [])
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except:
                    prices = []
            
            price = float(prices[0]) if (isinstance(prices, list) and len(prices) > 0) else 0
            
            cat_label = MarketClassifier.label(cat)
            price_color = "price-high" if price >= 0.75 else "price-low" if price <= 0.15 else "price-mid" if 0.40 <= price <= 0.60 else "price-default"
            title_short = question[:35] + "..." if len(question) > 35 else question
            
            market_data = {
                "title": question,
                "price": price,
                "platform": "polymarket",
                "condition_id": m.get('conditionId', ''),
                "category": cat,
                "history": [price] * 10,
            }
            
            card = MarketCard(
                title_short, price, cat, "polymarket", market_data,
                f"[cat-{cat_label}][{cat_label}][/{cat_label}] [title]{title_short:<38}[/title] [{price_color}]{price:>5.2f}[/{price_color}]",
                classes="market-card"
            )
            container.mount(card)

    async def action_filter(self, niche: str) -> None:
        self.current_niche = niche
        await self.action_refresh()

    def action_toggle_graph(self) -> None:
        self.show_graph = not self.show_graph
        graph_pane = self.query_one("#graph-pane")
        if self.show_graph:
            graph_pane.remove_class("hidden")
        else:
            graph_pane.add_class("hidden")

    def action_close_graph(self) -> None:
        self.show_graph = False
        self.query_one("#graph-pane").add_class("hidden")
        self.selected_market = None

    def show_graph_panel(self, market_data: dict) -> None:
        if not market_data:
            return
        
        self.show_graph = True
        graph_pane = self.query_one("#graph-pane")
        graph_pane.remove_class("hidden")
        
        container = self.query_one("#graph-content", Vertical)
        container.remove_children()
        
        title = market_data.get("title", market_data.get("question", "Unknown"))
        price = market_data.get("price", 0)
        platform = market_data.get("platform", "unknown")
        
        container.mount(Static(f"\n[graph-title]{title}[/graph-title]\n", classes="graph-title"))
        container.mount(Static(f"[graph-price]Current Price: ${price:.2f}[/graph-price]\n", classes="graph-price"))
        
        sparkline_data = market_data.get("history", [price] * 10)
        sparkline = self._generate_sparkline(sparkline_data)
        container.mount(Static(f"[graph-sparkline]{sparkline}[/graph-sparkline]", classes="graph-sparkline"))
        
        container.mount(Static(f"\nPlatform: {platform.upper()}", classes="graph-title"))

    def _generate_sparkline(self, data: list) -> str:
        if not data:
            return "No data"
        
        data = data[-20:] if len(data) > 20 else data
        min_val = min(data)
        max_val = max(data)
        range_val = max_val - min_val if max_val > min_val else 1
        
        chars = "▁▂▃▄▅▆▇█"
        result = ""
        for v in data:
            normalized = (v - min_val) / range_val
            idx = int(normalized * (len(chars) - 1))
            result += chars[idx]
        
        return result

    def action_next_theme(self) -> None:
        self.current_theme_idx = (self.current_theme_idx + 1) % len(THEMES)
        self.theme = THEMES[self.current_theme_idx]

if __name__ == "__main__":
    app = PolyTerminal()
    app.run()
