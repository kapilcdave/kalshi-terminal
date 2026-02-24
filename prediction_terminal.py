import os
import asyncio
import json
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Input, 
    RichLog, Label
)
from textual.binding import Binding

from kalshi_client import KalshiClient
from polymarket_client import PolymarketClient
from unified_store import UnifiedStore
from live_engine import LiveEngine
from agent_manager import AgentManager

CSS_PATH = "prediction_terminal.tcss"

class Ticker(Static):
    """Simple status header."""
    def on_mount(self):
        self.set_interval(1, self.update_ticker)
        self.update_ticker()

    def update_ticker(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.update(f" UNFILTERED WEBSOCKET STREAM | {now} ")


class ClawdbotBar(Static):
    """Personality-driven status bar."""
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(" 🦞 ", id="clawdbot-logo")
            yield Label("[Clawdbot v1.0] Streaming raw websocket packets...", id="bot-message")


class PredictionTerminal(App):
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "clear_logs", "Clear Logs"),
        Binding("p", "pause_logs", "Pause/Resume"),
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
        
        self.paused = False

    def compose(self) -> ComposeResult:
        yield Ticker(id="ticker-container")
        
        with Horizontal(id="logs-container"):
            with Vertical(classes="log-pane"):
                yield Label("Kalshi WebSocket", classes="pane-title kalshi-title")
                yield RichLog(id="kalshi-log", highlight=True, wrap=True, max_lines=1000)
                
            with Vertical(classes="log-pane"):
                yield Label("Polymarket WebSocket", classes="pane-title poly-title")
                yield RichLog(id="poly-log", highlight=True, wrap=True, max_lines=1000)
                
        yield ClawdbotBar(id="clawdbot-bar")
        yield Footer()

    async def on_mount(self) -> None:
        # Hook into the RAW message stream
        self.engine.add_raw_callback(self._on_raw_message)
        
        await self.engine.start()
        await self.agent.start()

    def _on_raw_message(self, platform: str, message: str):
        if self.paused:
            return
            
        try:
            # Parse and pretty print the JSON to make it readable
            data = json.loads(message)
            formatted = json.dumps(data, indent=2)
            
            # Simple syntax highlighting using rich tags based on type
            msg_type = data.get('type', 'unknown')
            color = "cyan"
            if msg_type in ["trade", "price_change"]:
                color = "green"
            elif msg_type in ["orderbook", "orderbook_change"]:
                color = "yellow"
            elif msg_type == "heartbeat":
                color = "bright_black"
                # Optionally filter out heartbeats if they are too noisy:
                # return 
                
            out = f"[{color}]{formatted}[/]"
            
            if platform == "kalshi":
                self.call_from_thread(self.query_one("#kalshi-log").write, out)
            else:
                self.call_from_thread(self.query_one("#poly-log").write, out)
        except Exception:
            # Fallback for non-JSON
            if platform == "kalshi":
                self.call_from_thread(self.query_one("#kalshi-log").write, message)
            else:
                self.call_from_thread(self.query_one("#poly-log").write, message)

    def action_clear_logs(self):
        self.query_one("#kalshi-log").clear()
        self.query_one("#poly-log").clear()
        
    def action_pause_logs(self):
        self.paused = not self.paused
        state = "PAUSED" if self.paused else "STREAMING"
        self.query_one("#bot-message").update(f"[Clawdbot v1.0] {state} raw websocket packets...")

    async def on_unmount(self) -> None:
        await self.engine.stop()
        await self.agent.stop()
        await self.kalshi.close()
        await self.poly.close()

if __name__ == "__main__":
    app = PredictionTerminal()
    app.run()
