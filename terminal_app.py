import os
import asyncio
import re
from datetime import datetime
from collections import defaultdict
from difflib import SequenceMatcher
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, DataTable, Static, Label
from textual.reactive import reactive
from textual.binding import Binding

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from arb_engine import ArbEngine

load_dotenv()

THEMES = ["nord", "gruvbox", "tokyo-night", "textual-dark", "solarized-dark", "monokai", "dracula", "catppuccin-mocha"]

class MarketClassifier:
    CATEGORIES = {
        "politics": [
            r"\btrump\b", r"\bbiden\b", r"\bpresident\b", r"\belection\b", r"\bcongress\b",
            r"\bsenate\b", r"\bhouse\b", r"\bdemocrat\b", r"\brepublican\b", r"\bgop\b",
            r"\bgovernor\b", r"\bmayor\b", r"\bprime minister\b", r"\bparliament\b",
            r"\bvote\b", r"\brecall\b", r"\breferendum\b", r"\bpolicy\b", r"\bbill\b",
            r"\bfederal\b", r"\bstate\b", r"\bcourt\b", r"\bsupreme\b", r"\bjustice\b",
            r"\bsenator\b", r"\brepresentative\b", r"\bpolitical\b", r"\bwikileaks\b",
            r"\bpalestine\b", r"\bisrael\b", r"\bukraine\b", r"\brussia\b", r"\bchina\b",
            r"\biran\b", r"\bnorth korea\b", r"\btaiwan\b", r"\beu\b", r"\beurope\b"
        ],
        "sports": [
            r"\bnba\b", r"\bnfl\b", r"\bmlb\b", r"\bnhl\b", r"\bcollege\b", r"\bfootball\b",
            r"\bbasketball\b", r"\bbaseball\b", r"\bhockey\b", r"\bsoccer\b", r"\bgolf\b",
            r"\btennis\b", r"\boxford\b", r"\bchampionship\b", r"\bgame\b", r"\bwin\b",
            r"\blose\b", r"\bwinner\b", r"\bplayoff\b", r"\bseason\b", r"\bteam\b",
            r"\bplayer\b", r"\bscore\b", r"\bmvp\b", r"\btournament\b", r"\bfinal\b",
            r"\bsemifinal\b", r"\bquarter\b", r"\bseed\b", r"\brank\b", r"\bATP\b",
            r"\bWTA\b", r"\bNCAAB\b", r"\bNCAABBGAME\b", r"\b3pt\b", r"\bthree.point\b"
        ],
        "financial": [
            r"\bfed\b", r"\binterest\b", r"\brate\b", r"\binflation\b", r"\bgdp\b",
            r"\bmarket\b", r"\bstock\b", r"\bsp500\b", r"\bdow\b", r"\bnasdaq\b",
            r"\bbitcoin\b", r"\bbtc\b", r"\bcrypto\b", r"\bethereum\b", r"\bcryptocurrency\b",
            r"\btreasury\b", r"\byield\b", r"\bbond\b", r"\brecession\b", r"\beconomy\b",
            r"\bunemployment\b", r"\bjobs\b", r"\blabor\b", r"\b wage\b", r"\bsalary\b",
            r"\brevenue\b", r"\btax\b", r"\btariff\b", r"\btrade\b", r"\bimport\b",
            r"\bexport\b", r"\bdoge\b", r"\bbudget\b", r"\bspending\b"
        ],
        "entertainment": [
            r"\boscar\b", r"\bgrammy\b", r"\bemmy\b", r"\bgolden globe\b", r"\baward\b",
            r"\bmovie\b", r"\bfilm\b", r"\bnetflix\b", r"\bdisney\b", r"\bhollywood\b",
            r"\bactor\b", r"\bactress\b", r"\bdirector\b", r"\bbox office\b", r"\bgta\b",
            r"\bvideo game\b", r"\brelease\b", r"\balbum\b", r"\bmusic\b", r"\bsong\b",
            r"\bchart\b", r"\bbillboard\b", r"\btop\b", r"\bsingle\b", r"\bartist\b",
            r"\btour\b", r"\bconcert\b", r"\bfestival\b"
        ],
        "science": [
            r"\bspace\b", r"\bnasa\b", r"\bmars\b", r"\bmoon\b", r"\bstarship\b",
            r"\bsatellite\b", r"\btelescope\b", r"\bclimate\b", r"\bweather\b",
            r"\btemperature\b", r"\bhurricane\b", r"\bstorm\b", r"\bearthquake\b",
            r"\bvolcano\b", r"\bpandemic\b", r"\bvirus\b", r"\bcovid\b", r"\bvaccine\b",
            r"\bAI\b", r"\bartificial intelligence\b", r"\bmachine learning\b",
            r"\bquantum\b", r"\bphysics\b", r"\bchemistr", r"\bbio\b", r"\bgene\b"
        ]
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
    def find_matches(cls, kalshi_markets, poly_markets, threshold: float = 0.5):
        matches = []
        for km in kalshi_markets:
            k_title = getattr(km, 'title', km.ticker) or km.ticker
            best_match = None
            best_score = threshold
            
            for pm in poly_markets:
                p_question = pm.get('question', '')
                score = cls.similarity(k_title, p_question)
                
                if score > best_score:
                    best_score = score
                    best_match = pm
            
            if best_match:
                matches.append({
                    'kalshi': km,
                    'polymarket': best_match,
                    'score': best_score
                })
        
        return matches

class PolyTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "filter('financial')", "Financial"),
        Binding("f2", "filter('politics')", "Politics"),
        Binding("f3", "filter('sports')", "Sports"),
        Binding("f4", "filter('entertainment')", "Entertainment"),
        Binding("f5", "filter('science')", "Science"),
        Binding("f6", "filter('all')", "All"),
        Binding("t", "next_theme", "Theme"),
    ]

    current_niche = reactive("all")
    current_theme_idx = reactive(0)

    def __init__(self):
        super().__init__()
        self.theme = THEMES[0]
        self.kalshi = KalshiClient()
        self.poly = PolymarketClient()
        self.arb = ArbEngine(self.kalshi, self.poly)
        self.k_markets = {}
        self.p_markets = {}
        self.matches = []

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("POLYTERMINAL ", classes="title"),
            Label("|", classes="sep"),
            Label("ALL MARKETS", id="cat"),
            Label("|", classes="sep"),
            Label(" v1.0 ", id="ver"),
            Label("", id="clock"),
            id="header"
        )
        with Horizontal(id="main"):
            with Vertical(id="kalshi-col"):
                yield Label("KALSHI (USD)", classes="pane-title")
                yield DataTable(id="kalshi-table")
            with Vertical(id="poly-col"):
                yield Label("POLYMARKET (USDC)", classes="pane-title")
                yield DataTable(id="poly-table")
        yield Footer()

    CSS = """
    #header {
        height: 1;
        dock: top;
    }
    .title { text-style: bold; }
    .sep { color: gray; }
    #cat { color: orange; text-style: bold; }
    #clock { width: 1fr; text-align: right; }
    
    #main {
        height: 1fr;
    }
    
    #kalshi-col, #poly-col {
        width: 1fr;
        height: 100%;
    }
    
    .pane-title {
        height: 1;
        dock: top;
        text-style: bold;
    }
    
    DataTable {
        height: 100%;
    }
    """

    async def on_mount(self) -> None:
        k_table = self.query_one("#kalshi-table", DataTable)
        k_table.add_columns("Cat", "Group", "Market", "Yes", "No", "Vol")
        
        p_table = self.query_one("#poly-table", DataTable)
        p_table.add_columns("Cat", "Group", "Market", "Yes", "No", "Vol")

        await self.kalshi.login()
        self.set_interval(1, self.update_clock)
        await self.action_refresh()

    def update_clock(self):
        try:
            self.query_one("#clock").update(datetime.now().strftime("%H:%M:%S"))
        except:
            pass

    async def action_refresh(self) -> None:
        await asyncio.gather(
            self.refresh_kalshi(self.current_niche if self.current_niche != "all" else None),
            self.refresh_poly(self.current_niche if self.current_niche != "all" else None)
        )
        self.find_cross_platform_matches()

    def find_cross_platform_matches(self):
        self.matches = FuzzyMatcher.find_matches(
            list(self.k_markets.values()),
            list(self.p_markets.values()),
            threshold=0.4
        )

    def _extract_event_name(self, ticker: str, title: str) -> str:
        if "-" in ticker:
            parts = ticker.split("-")
            if len(parts) >= 2:
                base = parts[0] + "-" + parts[1]
                return base[:15] if len(base) > 15 else base
        if title:
            words = title.split()
            if len(words) >= 2:
                return words[0][:15]
        return ticker[:15]

    async def refresh_kalshi(self, category=None):
        table = self.query_one("#kalshi-table", DataTable)
        table.clear()
        
        markets = await self.kalshi.get_active_markets(limit=200, category=category)
        
        groups = defaultdict(list)
        for m in markets:
            event = self._extract_event_name(m.ticker, getattr(m, 'title', m.ticker))
            groups[event].append(m)
        
        self.k_markets = {m.ticker: m for m in markets}
        
        for event_name, group_markets in sorted(groups.items()):
            for m in group_markets:
                title = getattr(m, 'title', m.ticker) or m.ticker
                cat = MarketClassifier.classify(title) or "other"
                
                if self.current_niche != "all" and cat != self.current_niche:
                    continue
                
                yes_bid = getattr(m, 'yes_bid', 0) or 0
                yes_ask = getattr(m, 'yes_ask', 0) or 0
                no_bid = getattr(m, 'no_bid', 100) or 100
                no_ask = getattr(m, 'no_ask', 100) or 100
                vol = getattr(m, 'volume', 0) or 0
                
                yes_price = (yes_bid + yes_ask) / 2 / 100 if (yes_bid or yes_ask) else 0
                no_price = (no_bid + no_ask) / 2 / 100 if (no_bid or no_ask) else 0
                
                is_matched = any(match['kalshi'].ticker == m.ticker for match in self.matches)
                marker = "🔗" if is_matched else ""
                
                table.add_row(
                    cat[:3].upper(),
                    event_name,
                    (title[:25] + "..." if len(title) > 25 else title) + marker,
                    f"{yes_price:.2f}" if yes_price > 0 else "--",
                    f"{no_price:.2f}" if no_price > 0 else "--",
                    f"{vol:,}",
                    key=m.ticker
                )

    async def refresh_poly(self, category=None):
        table = self.query_one("#poly-table", DataTable)
        table.clear()
        
        poly_tag = None
        if category == "politics": poly_tag = "Politics"
        elif category == "sports": poly_tag = "Sports"
        elif category == "financial": poly_tag = "Business"
        
        markets = await self.poly.get_active_markets(limit=200, tag=poly_tag)
        
        groups = defaultdict(list)
        for m in markets:
            question = m.get('question', 'Unknown')
            event = self._extract_event_name(m.get('id', 'unknown'), question)
            groups[event].append(m)
        
        self.p_markets = {str(m.get('id')): m for m in markets}
        
        for event_name, group_markets in sorted(groups.items()):
            for m in group_markets:
                question = m.get('question', 'Unknown')
                cat = MarketClassifier.classify(question) or "other"
                
                if self.current_niche != "all" and cat != self.current_niche:
                    continue
                
                prices = m.get('outcomePrices', [])
                if isinstance(prices, str):
                    import json
                    try:
                        prices = json.loads(prices)
                    except:
                        prices = []
                yes_price = float(prices[0]) if (isinstance(prices, (list, tuple)) and len(prices) > 0) else 0
                no_price = float(prices[1]) if (isinstance(prices, (list, tuple)) and len(prices) > 1) else 0
                vol = float(m.get('volume', 0) or 0)
                
                is_matched = any(match['polymarket'].get('id') == m.get('id') for match in self.matches)
                marker = "🔗" if is_matched else ""
                
                table.add_row(
                    cat[:3].upper(),
                    event_name,
                    (question[:25] + "..." if len(question) > 25 else question) + marker,
                    f"{yes_price:.2f}",
                    f"{no_price:.2f}",
                    f"{int(vol):,}",
                    key=str(m.get('id'))
                )

    async def action_filter(self, niche: str) -> None:
        self.current_niche = niche
        try:
            self.query_one("#cat").update(niche.upper() if niche != "all" else "ALL MARKETS")
        except:
            pass
        await self.action_refresh()

    def action_next_theme(self) -> None:
        self.current_theme_idx = (self.current_theme_idx + 1) % len(THEMES)
        self.theme = THEMES[self.current_theme_idx]

if __name__ == "__main__":
    app = PolyTerminal()
    app.run()
