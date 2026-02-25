import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

import websockets
import httpx

from unified_store import UnifiedStore

logger = logging.getLogger("LiveEngine")

@dataclass
class ConnectionStatus:
    platform: str
    connected: bool = False
    last_heartbeat: float = 0.0
    messages_received: int = 0
    latency_ms: float = 0.0


class LiveEngine:
    KALSHI_WSS_DEMO = "wss://demo-api.kalshi.co/trade-api/v2/stream"
    KALSHI_WSS_PROD = "wss://api.kalshi.com/trade-api/v2/stream"
    POLY_WSS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    POLY_API = "https://clob.polymarket.com"
    POLY_GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(
        self, 
        store: UnifiedStore,
        kalshi_env: str = "demo",
        kalshi_api_key: Optional[str] = None,
        kalshi_private_key: Optional[str] = None,
        kalshi_client: Any = None
    ):
        self.store = store
        self.kalshi_env = kalshi_env
        self.kalshi_api_key = kalshi_api_key
        self.kalshi_private_key = kalshi_private_key
        self.kalshi_client = kalshi_client
        
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        self.kalshi_status = ConnectionStatus("kalshi")
        self.poly_status = ConnectionStatus("polymarket")
        
        self._status_callbacks: List[Callable] = []
        self._price_callbacks: List[Callable] = []
        
        self._http_client: Optional[httpx.AsyncClient] = None
        
    def add_status_callback(self, callback: Callable):
        self._status_callbacks.append(callback)
        
    def add_price_callback(self, callback: Callable):
        self._price_callbacks.append(callback)
        
    async def _notify_status(self, status: ConnectionStatus):
        for cb in self._status_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(status)
                else:
                    cb(status)
            except Exception:
                pass
                
    async def _notify_price(self, platform: str, data: Dict):
        for cb in self._price_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(platform, data)
                else:
                    cb(platform, data)
            except Exception:
                pass
                
    async def start(self):
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
        
        self._tasks.append(asyncio.create_task(self._kalshi_stream()))
        self._tasks.append(asyncio.create_task(self._poly_stream()))
        self._tasks.append(asyncio.create_task(self._status_heartbeat()))
        
        logger.info("LiveEngine started")
        
    async def stop(self):
        self._running = False
        
        for task in self._tasks:
            task.cancel()
            
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        if self._http_client:
            await self._http_client.aclose()
            
        logger.info("LiveEngine stopped")
        
    async def _status_heartbeat(self):
        while self._running:
            await asyncio.sleep(10)
            
            await self._notify_status(self.kalshi_status)
            await self._notify_status(self.poly_status)
            
    async def _kalshi_stream(self):
        url = self.KALSHI_WSS_PROD if self.kalshi_env == "prod" else self.KALSHI_WSS_DEMO
        
        headers = {}
        if self.kalshi_client and self.kalshi_client.api_key and self.kalshi_client.private_key_content:
            try:
                headers = self.kalshi_client.get_auth_headers("GET", "/trade-api/ws/v2")
            except Exception:
                pass
        
        kwargs = {}
        if headers:
            kwargs["extra_headers"] = headers
            
        while self._running:
            try:
                async with websockets.connect(url, **kwargs) as ws:
                    self.kalshi_status.connected = True
                    self.kalshi_status.last_heartbeat = time.time()
                    await self._notify_status(self.kalshi_status)
                    
                    await ws.send(json.dumps({
                        "id": int(time.time()),
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["ticker", "trade"]
                        }
                    }))
                    
                    async for message in ws:
                        if not self._running:
                            break
                            
                        try:
                            # Handle bytes message
                            if isinstance(message, bytes):
                                message = message.decode('utf-8')
                                
                            data = json.loads(message)
                            self.kalshi_status.messages_received += 1
                            
                            msg_type = data.get("type", "")
                            
                            # Skip subscription confirmations and heartbeats
                            if msg_type in ["subscribed", "heartbeat"]:
                                continue
                            
                            # Handle message in msg field for new format
                            msg_data = data.get("msg", data)
                            
                            if isinstance(msg_data, list):
                                for item in msg_data:
                                    await self._process_kalshi_message(item)
                                    await self._notify_price("kalshi", item)
                            else:
                                await self._process_kalshi_message(msg_data)
                                await self._notify_price("kalshi", msg_data)
                            
                        except Exception as e:
                            continue
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Kalshi stream error: {e}")
                self.kalshi_status.connected = False
                await self._notify_status(self.kalshi_status)
                await asyncio.sleep(5)
                
        self.kalshi_status.connected = False
        await self._notify_status(self.kalshi_status)
        
    async def _process_kalshi_message(self, data: Dict):
        msg_type = data.get("type", "")
        
        if msg_type in ["trade", "ticker"]:
            ticker = data.get("market_ticker")
            if not ticker:
                return
                
            price = 0.0
            volume = 0
            
            try:
                if msg_type == "ticker":
                    yes_bid = data.get("yes_bid")
                    yes_ask = data.get("yes_ask")
                    if yes_bid and yes_ask:
                        price = (float(yes_bid) + float(yes_ask)) / 2 / 100
                    elif yes_bid:
                        price = float(yes_bid) / 100
                    volume = int(data.get("volume", 0) or 0)
                elif msg_type == "trade":
                    price = float(data.get("price", 0)) / 100
                    volume = int(data.get("size", 0) or data.get("volume", 0))
            except (ValueError, TypeError):
                pass
                    
            if ticker and price > 0:
                await self.store.update_from_kalshi(ticker, price, volume)
            
        elif msg_type == "heartbeat":
            self.kalshi_status.last_heartbeat = time.time()
            
    async def _poly_stream(self):
        while self._running:
            try:
                async with websockets.connect(self.POLY_WSS) as ws:
                    self.poly_status.connected = True
                    self.poly_status.last_heartbeat = time.time()
                    await self._notify_status(self.poly_status)
                    
                    sub_msg = {
                        "type": "market",
                        "operation": "subscribe",
                        "assets_ids": []
                    }
                    await ws.send(json.dumps(sub_msg))
                    
                    async for message in ws:
                        if not self._running:
                            break
                            
                        try:
                            data = json.loads(message)
                            self.poly_status.messages_received += 1
                            
                            await self._process_poly_message(data)
                            await self._notify_price("polymarket", data)
                            
                        except json.JSONDecodeError:
                            continue
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polymarket stream error: {e}")
                self.poly_status.connected = False
                await self._notify_status(self.poly_status)
                await asyncio.sleep(5)
                
        self.poly_status.connected = False
        await self._notify_status(self.poly_status)
        
    async def _process_poly_message(self, data: Dict):
        msg_type = data.get("type", "")
        
        if msg_type == "price_change" or msg_type == "orderbook_change":
            asset_id = data.get("asset_id") or data.get("token_id")
            if not asset_id:
                return
                
            price = 0.0
            volume = 0
            
            if msg_type == "price_change":
                price = float(data.get("price", 0))
                volume = int(data.get("size", 0) or data.get("volume", 0))
            elif msg_type == "orderbook_change":
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                if bids and len(bids) > 0:
                    price = float(bids[0].get("price", 0))
                    
            question = await self._get_poly_question(asset_id)
            await self.store.update_from_poly(asset_id, question or f"Market {asset_id}", price, volume)
            
        elif msg_type == "pong":
            self.poly_status.last_heartbeat = time.time()
            
    async def _get_poly_question(self, token_id: str) -> Optional[str]:
        if not self._http_client:
            return None
            
        try:
            response = await self._http_client.get(
                f"{self.POLY_GAMMA_API}/markets",
                params={"token_id": token_id, "active": "true"}
            )
            if response.status_code == 200:
                markets = response.json()
                if markets and len(markets) > 0:
                    return markets[0].get("question")
        except Exception:
            pass
            
        return None
        
    async def fetch_initial_markets(self) -> bool:
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            
        logger.info("Fetching initial markets...")
        
        # 1. Fetch from Kalshi
        try:
            from kalshi_client import KalshiClient
            kc = KalshiClient()
            kalshi_markets = await kc.get_active_markets(limit=50)
            for m in kalshi_markets:
                price = 0
                if kc.use_mock:
                    price = getattr(m, 'last_price', 0)
                else:
                    yes_bid = getattr(m, 'yes_bid', 0) or 0
                    yes_ask = getattr(m, 'yes_ask', 0) or 0
                    if yes_bid > 0 and yes_ask > 0:
                        price = (yes_bid + yes_ask) / 2 / 100
                    elif yes_bid > 0:
                        price = yes_bid / 100
                    elif yes_ask > 0:
                        price = yes_ask / 100
                
                if price > 0:
                    await self.store.update_from_kalshi(m.ticker, price, 0)
            logger.info(f"Fetched {len(kalshi_markets)} markets from Kalshi.")
        except Exception as e:
            logger.error(f"Failed to fetch Kalshi markets: {e}")
        
        # 2. Fetch from Polymarket
        try:
            response = await self._http_client.get(
                f"{self.POLY_GAMMA_API}/markets",
                params={"active": "true", "limit": 50, "closed": "false"}
            )
            if response.status_code == 200:
                poly_markets = response.json()
                for m in poly_markets:
                    outcome_prices_raw = m.get('outcomePrices')
                    price = 0
                    if outcome_prices_raw:
                        try:
                            if isinstance(outcome_prices_raw, str):
                                outcome_prices = json.loads(outcome_prices_raw)
                            else:
                                outcome_prices = outcome_prices_raw
                            if outcome_prices and len(outcome_prices) > 0:
                                price = float(outcome_prices[0])
                        except (ValueError, TypeError, json.JSONDecodeError):
                            price = 0
                    
                    token_id = None
                    clob_token_ids = m.get('clobTokenIds', [])
                    if clob_token_ids and len(clob_token_ids) > 0:
                        token_id = clob_token_ids[0]
                    
                    if price > 0 and token_id:
                        await self.store.update_from_poly(
                            token_id, 
                            m.get('question'), 
                            price, 
                            0
                        )
                logger.info(f"Fetched {len(poly_markets)} markets from Polymarket.")
        except Exception as e:
            logger.error(f"Failed to fetch Polymarket markets: {e}")
            
        return True
        
    def get_status_summary(self) -> Dict[str, Any]:
        return {
            "kalshi": {
                "connected": self.kalshi_status.connected,
                "last_heartbeat": self.kalshi_status.last_heartbeat,
                "messages_received": self.kalshi_status.messages_received,
                "latency_ms": self.kalshi_status.latency_ms
            },
            "polymarket": {
                "connected": self.poly_status.connected,
                "last_heartbeat": self.poly_status.last_heartbeat,
                "messages_received": self.poly_status.messages_received,
                "latency_ms": self.poly_status.latency_ms
            }
        }
