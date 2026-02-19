import os
import asyncio
import re
import json
from datetime import datetime
from collections import defaultdict, deque
from difflib import SequenceMatcher
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, DataTable, Static, Label
from textual.reactive import reactive
from textual.binding import Binding

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
    
    @classmethod
    def classify(cls, text: str) -> str | None:
        text = text.lower()
        for category, patterns in cls.CATEGORIES.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return category
        return None

class FuzzyMatcher:
    @staticmethod
    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()
    
    @classmethod
    def find_best_match(cls, k_title: str, poly_questions: dict, threshold=0.3):
        best_match = None
        best_score = threshold
        best_id = None
        
        for q_id, q_text in poly_questions.items():
            score = cls.similarity(k_title, q_text)
            if score > best_score:
                best_score = score
                best_match = q_text
                best_id = q_id
        
        return best_id, best_match, best_score

class PriceHistory:
    def __init__(self, maxlen=50):
        self.maxlen = maxlen
        self.data = {}
    
    def add(self, key, price):
        if key not in self.data:
            self.data[key] = deque(maxlen=self.maxlen)
        if price:
            self.data[key].append(price)
    
    def get(self, key):
        return list(self.data.get(key, []))

class PolyTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('financial')", "Fin"),
        Binding("f2", "filter('politics')", "Pol"),
        Binding("f3", "filter('sports')", "Spo"),
        Binding("f4", "filter('all')", "All"),
        Binding("t", "next_theme", "Theme"),
        Binding("l", "toggle_live", "Live"),
    ]

    current_niche = reactive("all")
    current_theme_idx = reactive(0)
    live_enabled = reactive(True)
    selected_row = reactive(None)

    def __init__(self):
        super().__init__()
        self.theme = THEMES[0]
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.k_markets = {}
        self.p_markets = {}
        self.matched_markets = []
        self.live_prices = {}
        self.kalshi_connected = False
        self.poly_connected = False
        self._ws_tasks = []
        self.price_history = PriceHistory()
        self._price_update_interval = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("TERMINAL", classes="title"),
            Label("|", classes="sep"),
            Label("ALL", id="cat"),
            Label("|", classes="sep"),
            Label("●", id="k-status", classes="status-off"),
            Label("●", id="p-status", classes="status-off"),
            Label("", id="clock", classes="clock"),
            id="header"
        )
        with Vertical(id="content"):
            with Vertical(id="main-pane"):
                yield DataTable(id="markets-table")
            with Horizontal(id="detail"):
                with Vertical(id="detail-left", classes="detail-pane"):
                    yield Label("KALS", classes="detail-label")
                    yield Label("", id="detail-k-title", classes="detail-title")
                    yield Label("", id="detail-k-price", classes="detail-price")
                with Vertical(id="detail-center", classes="detail-pane"):
                    yield Label("SPREAD", classes="detail-label")
                    yield Label("", id="detail-spread", classes="detail-spread")
                with Vertical(id="detail-right", classes="detail-pane"):
                    yield Label("POLY", classes="detail-label")
                    yield Label("", id="detail-p-title", classes="detail-title")
                    yield Label("", id="detail-p-price", classes="detail-price")
        yield Footer()

    CSS = """
    #header { height: 1; dock: top; }
    .title { text-style: bold; }
    .sep { color: gray; }
    #cat { color: orange; text-style: bold; }
    .clock { width: 1fr; text-align: right; }
    .status-off { color: red; }
    .status-on { color: green; }
    #content { height: 1fr; }
    #main-pane { height: 1fr; }
    #detail { height: 8; dock: bottom; background: $surface; }
    .detail-pane { width: 1fr; height: 100%; }
    .detail-label { width: 100%; text-align: center; text-style: bold; color: $accent; }
    .detail-title { width: 100%; text-align: center; }
    .detail-price { width: 100%; text-align: center; text-style: bold; }
    .detail-spread { width: 100%; height: 5; text-align: center; text-style: bold; }
    """

    async def on_mount(self) -> None:
        table = self.query_one("#markets-table", DataTable)
        table.add_columns("Match", "Kalshi Price", "Kalshi Market", "Poly Price", "Poly Market", "Spread")
        table.cursor_type = "row"

        await self.kalshi.login()
        self.set_interval(1, self.update_clock)
        
        await self.action_refresh()
        
        if self.live_enabled:
            await self.start_live()

    async def start_live(self):
        self._ws_tasks = [
            asyncio.create_task(self._kalshi_ws()),
            asyncio.create_task(self._poly_ws())
        ]
        self._price_update_interval = self.set_interval(2, self.update_prices)

    async def stop_live(self):
        for task in self._ws_tasks:
            task.cancel()
        self._ws_tasks = []
        if self._price_update_interval:
            self._price_update_interval.stop()
        self.kalshi_connected = False
        self.poly_connected = False

    async def update_prices(self):
        table = self.query_one("#markets-table", DataTable)
        
        for i, match in enumerate(self.matched_markets):
            k_ticker = match.get('k_ticker')
            p_id = match.get('p_id')
            
            k_price = self.live_prices.get(f"k_{k_ticker}", 0)
            p_price = self.live_prices.get(f"p_{p_id}", 0)
            
            if k_price or p_price:
                k_display = f"{k_price:.2f}" if k_price else "--"
                p_display = f"{p_price:.2f}" if p_price else "--"
                spread = abs(k_price - p_price) * 100 if k_price and p_price else 0
                
                try:
                    table.update_row_at(i, (match.get('match_indicator', '○'), k_display, match.get('k_title', '')[:30], p_display, match.get('p_title', '')[:30], f"{spread:.1f}%"))
                except:
                    pass

    async def _kalshi_ws(self):
        import websockets
        url = "wss://demo-api.kalshi.co/trade-api/v2/stream"
        
        while self.live_enabled:
            try:
                async with websockets.connect(url) as ws:
                    self.kalshi_connected = True
                    self._update_status()
                    
                    await ws.send(json.dumps({"type": "subscribe", "channel": "markets", "markets": ["*"]}))
                    
                    async for msg in ws:
                        if not self.live_enabled:
                            break
                        try:
                            data = json.loads(msg)
                            ticker = data.get("ticker")
                            if ticker:
                                price = 0
                                if data.get("type") == "trade":
                                    price = data.get("price", 0) / 100
                                elif data.get("type") == "orderbook":
                                    ob = data.get("orderbook", {})
                                    yes = ob.get("yes", [])
                                    if yes:
                                        price = yes[0][0] / 100
                                if price > 0:
                                    self.live_prices[f"k_{ticker}"] = price
                                    self.price_history.add(f"k_{ticker}", price)
                        except:
                            pass
            except:
                self.kalshi_connected = False
                self._update_status()
                await asyncio.sleep(5)

    async def _poly_ws(self):
        import websockets
        url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        
        while self.live_enabled:
            try:
                async with websockets.connect(url) as ws:
                    self.poly_connected = True
                    self._update_status()
                    
                    await ws.send(json.dumps({"type": "market", "operation": "subscribe", "assets_ids": []}))
                    
                    async for msg in ws:
                        if not self.live_enabled:
                            break
                        try:
                            data = json.loads(msg)
                            asset_id = data.get("asset_id") or data.get("token_id")
                            if asset_id:
                                price = 0
                                if data.get("type") == "price_change":
                                    price = float(data.get("price", 0))
                                elif data.get("type") == "orderbook_change":
                                    bids = data.get("bids", [])
                                    if bids:
                                        price = float(bids[0].get("price", 0))
                                if price > 0:
                                    self.live_prices[f"p_{asset_id}"] = price
                                    self.price_history.add(f"p_{asset_id}", price)
                        except:
                            pass
            except:
                self.poly_connected = False
                self._update_status()
                await asyncio.sleep(5)

    def _update_status(self):
        try:
            ks = self.query_one("#k-status", Label)
            ps = self.query_one("#p-status", Label)
            ks.update("●" if self.kalshi_connected else "○")
            ps.update("●" if self.poly_connected else "○")
            ks.set_class(self.kalshi_connected, "status-on")
            ks.set_class(not self.kalshi_connected, "status-off")
            ps.set_class(self.poly_connected, "status-on")
            ps.set_class(not self.poly_connected, "status-off")
        except:
            pass

    def update_clock(self):
        try:
            self.query_one("#clock").update(datetime.now().strftime("%H:%M"))
        except:
            pass

    async def action_refresh(self) -> None:
        await self.refresh_markets()

    async def refresh_markets(self):
        table = self.query_one("#markets-table", DataTable)
        table.clear()
        
        k_markets = await self.kalshi.get_active_markets(limit=100)
        p_markets = await self.poly.get_active_markets(limit=100)
        
        self.k_markets = {m.ticker: m for m in k_markets}
        
        p_questions = {}
        for m in p_markets:
            q = m.get('question', '')
            p_questions[str(m.get('id'))] = q
        
        self.p_markets = {str(m.get('id')): m for m in p_markets}
        
        matched = []
        unmatched_k = []
        
        for km in k_markets:
            k_title = getattr(km, 'title', km.ticker) or km.ticker
            k_cat = MarketClassifier.classify(k_title)
            
            if self.current_niche != "all" and k_cat != self.current_niche:
                continue
            
            p_id, p_title, score = FuzzyMatcher.find_best_match(k_title, p_questions, threshold=0.35)
            
            if p_id:
                pm = self.p_markets.get(p_id)
                if pm:
                    matched.append({
                        'k_ticker': km.ticker,
                        'k_title': k_title,
                        'k_cat': k_cat,
                        'p_id': p_id,
                        'p_title': p_title,
                        'score': score
                    })
            else:
                unmatched_k.append({
                    'k_ticker': km.ticker,
                    'k_title': k_title,
                    'k_cat': k_cat
                })
        
        self.matched_markets = matched[:30] + [{'k_ticker': m['k_ticker'], 'k_title': m['k_title'], 'k_cat': m['k_cat'], 'p_id': None, 'p_title': None, 'match_indicator': '○'} for m in unmatched_k[:30]]
        
        for match in self.matched_markets:
            k_ticker = match.get('k_ticker')
            k_title = match.get('k_title', '')
            k_cat = match.get('k_cat', '?')
            p_id = match.get('p_id')
            p_title = match.get('p_title', '')
            
            km = self.k_markets.get(k_ticker)
            k_price = 0
            if km:
                yes_bid = getattr(km, 'yes_bid', 0) or 0
                yes_ask = getattr(km, 'yes_ask', 0) or 0
                k_price = (yes_bid + yes_ask) / 2 / 100
            
            live_k = self.live_prices.get(f"k_{k_ticker}")
            if live_k:
                k_price = live_k
            
            p_price = 0
            if p_id:
                pm = self.p_markets.get(p_id)
                if pm:
                    prices = pm.get('outcomePrices', [])
                    if isinstance(prices, list) and len(prices) > 0:
                        p_price = float(prices[0])
                
                live_p = self.live_prices.get(f"p_{p_id}")
                if live_p:
                    p_price = live_p
            
            k_display = f"{k_price:.2f}" if k_price > 0 else "--"
            p_display = f"{p_price:.2f}" if p_price > 0 else "--"
            
            indicator = "◉" if p_id else "○"
            spread = abs(k_price - p_price) * 100 if k_price and p_price else 0
            spread_str = f"{spread:.1f}%" if spread > 0 else "--"
            
            table.add_row(
                indicator,
                k_display,
                f"[{k_cat[:1].upper() if k_cat else '?'}] {k_title[:35]}...",
                p_display,
                p_title[:35] + "..." if p_title and len(p_title) > 35 else p_title or "--",
                spread_str,
                key=k_ticker
            )

    async def on_data_table_row_selected(self, event):
        row_key = event.row_key
        
        for match in self.matched_markets:
            if match.get('k_ticker') == row_key:
                self.selected_row = match
                self.update_detail_view()
                break

    def update_detail_view(self):
        if not self.selected_row:
            return
        
        k_title = self.query_one("#detail-k-title", Label)
        k_price = self.query_one("#detail-k-price", Label)
        p_title = self.query_one("#detail-p-title", Label)
        p_price = self.query_one("#detail-p-price", Label)
        spread_label = self.query_one("#detail-spread", Label)
        
        k_ticker = self.selected_row.get('k_ticker')
        k_title_text = self.selected_row.get('k_title', 'N/A')
        p_title_text = self.selected_row.get('p_title', 'Select a matched market')
        
        k_price_val = self.live_prices.get(f"k_{k_ticker}", 0)
        if not k_price_val:
            km = self.k_markets.get(k_ticker)
            if km:
                yes_bid = getattr(km, 'yes_bid', 0) or 0
                yes_ask = getattr(km, 'yes_ask', 0) or 0
                k_price_val = (yes_bid + yes_ask) / 2 / 100
        
        p_id = self.selected_row.get('p_id')
        p_price_val = 0
        if p_id:
            p_price_val = self.live_prices.get(f"p_{p_id}", 0)
            if not p_price_val:
                pm = self.p_markets.get(p_id)
                if pm:
                    prices = pm.get('outcomePrices', [])
                    if isinstance(prices, list) and len(prices) > 0:
                        p_price_val = float(prices[0])
        
        k_title.update(k_title_text[:50])
        k_price.update(f"${k_price_val:.2f}" if k_price_val else "--")
        
        p_title.update(p_title_text[:50] if p_title_text else "--")
        p_price.update(f"${p_price_val:.2f}" if p_price_val else "--")
        
        if k_price_val and p_price_val:
            spread = abs(k_price_val - p_price_val) * 100
            color = "green" if spread < 5 else "yellow" if spread < 15 else "red"
            spread_label.update(f"{spread:.1f}%\nspread")
        else:
            spread_label.update("--\nselect match")

    async def action_filter(self, niche: str) -> None:
        self.current_niche = niche
        try:
            self.query_one("#cat").update(niche.upper() if niche != "all" else "ALL")
        except:
            pass
        await self.action_refresh()

    def action_next_theme(self) -> None:
        self.current_theme_idx = (self.current_theme_idx + 1) % len(THEMES)
        self.theme = THEMES[self.current_theme_idx]

    async def action_toggle_live(self) -> None:
        self.live_enabled = not self.live_enabled
        if self.live_enabled:
            await self.start_live()
        else:
            await self.stop_live()
        self._update_status()

    async def on_shutdown(self):
        await self.stop_live()

if __name__ == "__main__":
    app = PolyTerminal()
    app.run()
