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


    KALSHI_WSS_DEMO = "wss://demo-api.kalshi.co/trade-api/v2/ws"
    KALSHI_WSS_PROD = "wss://api.kalshi.com/trade-api/v2/ws"
    POLY_WSS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    POLY_API = "https://clob.polymarket.com"
    POLY_GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(
        self, 
        store: UnifiedStore,
        kalshi_env: str = "demo",
        kalshi_api_key: Optional[str] = None,
        kalshi_private_key: Optional[str] = None
    ):
        self.store = store
        self.kalshi_env = kalshi_env
        self.kalshi_api_key = kalshi_api_key
        self.kalshi_private_key = kalshi_private_key
        
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        self.kalshi_status = ConnectionStatus("kalshi")
        self.poly_status = ConnectionStatus("polymarket")
        
        self._status_callbacks: List[Callable] = []
        self._price_callbacks: List[Callable] = []
        self._raw_callbacks: List[Callable] = []
        
        self._http_client: Optional[httpx.AsyncClient] = None
        
    def add_status_callback(self, callback: Callable):
        self._status_callbacks.append(callback)
        
        self._price_callbacks.append(callback)
        
    def add_raw_callback(self, callback: Callable):
        self._raw_callbacks.append(callback)
        
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
                
    async def _notify_raw(self, platform: str, message: str):
        for cb in self._raw_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(platform, message)
                else:
                    cb(platform, message)
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
        if self.kalshi_api_key and self.kalshi_private_key:
            import base64
            auth_value = base64.b64encode(
                f"{self.kalshi_api_key}:{self.kalshi_private_key[:20]}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {auth_value}"
        
        kwargs = {}
        if headers:
            kwargs["additional_headers"] = headers
            
        while self._running:
            try:
                async with websockets.connect(url, **kwargs) as ws:
                    self.kalshi_status.connected = True
                    self.kalshi_status.last_heartbeat = time.time()
                    await self._notify_status(self.kalshi_status)
                    
                    await ws.send(json.dumps({
                        "type": "subscribe",
                        "channel": "markets",
                        "markets": ["*"]
                    }))
                    
                    async for message in ws:
                        if not self._running:
                            break
                            
                        try:
                            # Forward raw message
                            await self._notify_raw("kalshi", message)
                            
                            data = json.loads(message)
                            self.kalshi_status.messages_received += 1
                            
                            if isinstance(data, list):
                                for item in data:
                                    await self._process_kalshi_message(item)
                                    await self._notify_price("kalshi", item)
                            else:
                                await self._process_kalshi_message(data)
                                await self._notify_price("kalshi", data)
                            
                        except Exception as e:
                            # Catch all to prevent disconnect on bad message format
                            pass
                            
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
        
        if msg_type == "trade" or msg_type == "orderbook":
            ticker = data.get("ticker") or data.get("market_ticker")
            if not ticker:
                return
                
            price = 0.0
            volume = 0
            
            if msg_type == "trade":
                price = data.get("price", 0) / 100 if isinstance(data.get("price"), (int, float)) else 0
                volume = data.get("size", 0) or data.get("volume", 0)
            elif msg_type == "orderbook":
                orderbook = data.get("orderbook", {})
                yes_orders = orderbook.get("yes", [])
                if yes_orders and len(yes_orders) > 0:
                    price = yes_orders[0][0] / 100 if isinstance(yes_orders[0][0], (int, float)) else 0
                    
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
                    # Fetch some active Polymarket tokens to subscribe to
                    token_ids = []
                    if self._http_client:
                        try:
                            response = await self._http_client.get(
                                f"{self.POLY_GAMMA_API}/markets",
                                params={"active": "true", "limit": 100}
                            )
                            if response.status_code == 200:
                                markets = response.json()
                                for m in markets:
                                    if m.get("tokens"):
                                        token_ids.append(m["tokens"][0].get("token_id"))
                        except Exception as e:
                            logger.error(f"Failed to fetch Poly markets: {e}")
                            
                    if not token_ids:
                        # Fallback static token for testing if fetch fails (e.g. some active token id)
                        token_ids = ["59441160358925232801458852870404391219089069695648877112104523996766487955513"] # Trump 2024 token id approx
                            
                    sub_msg = {
                        "type": "market",
                        "operation": "subscribe",
                        "asset_ids": token_ids[:100]  # Subscribe to up to 100 active tokens
                    }
                    logger.debug(f"Subscribing to Poly with {len(token_ids[:100])} tokens.")
                    await ws.send(json.dumps(sub_msg))
                    
                    async for message in ws:
                        if not self._running:
                            break
                            
                        try:
                            # Forward raw message
                            await self._notify_raw("polymarket", message)
                            
                            data = json.loads(message)
                            self.poly_status.messages_received += 1
                            
                            if isinstance(data, list):
                                for item in data:
                                    await self._process_poly_message(item)
                                    await self._notify_price("polymarket", item)
                            else:
                                await self._process_poly_message(data)
                                await self._notify_price("polymarket", data)
                            
                        except Exception as e:
                            pass
                            
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
