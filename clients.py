"""
clients.py — Kalshi + Polymarket data clients.
Provides REST (initial load) and WebSocket (live updates) for both platforms.
"""
import asyncio
import base64
import json
import logging
import time
from typing import Callable, Optional

import httpx
import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

log = logging.getLogger(__name__)

KALSHI_API  = "https://api.elections.kalshi.com"
KALSHI_WS   = "wss://api.elections.kalshi.com/trade-api/ws/v2"
POLY_API    = "https://gamma-api.polymarket.com"
POLY_WS     = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


# ─── Kalshi ───────────────────────────────────────────────────────────────────

class KalshiClient:
    def __init__(self, api_key: str, private_key_pem: str):
        self.api_key = api_key
        # Strip whitespace from each line so indented keys also load correctly
        clean = "\n".join(l.strip() for l in private_key_pem.splitlines() if l.strip())
        self._private_key = serialization.load_pem_private_key(
            clean.encode(), password=None
        )

    def _sign(self, method: str, path: str) -> dict:
        """Return signed auth headers required by Kalshi."""
        ts  = str(int(time.time() * 1000))
        msg = (ts + method + path).encode()
        sig = self._private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY":       self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }

    async def get_markets(self, limit: int = 100) -> list[dict]:
        """Fetch open markets via REST."""
        path = "/trade-api/v2/markets"
        headers = self._sign("GET", path)
        headers["Content-Type"] = "application/json"
        params = {"status": "open", "limit": limit}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(KALSHI_API + path, headers=headers, params=params)
            r.raise_for_status()
            return r.json().get("markets", [])

    async def get_balance(self) -> float:
        """Return account balance in dollars."""
        path = "/trade-api/v2/portfolio/balance"
        headers = self._sign("GET", path)
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(KALSHI_API + path, headers=headers)
            r.raise_for_status()
            return r.json().get("balance", 0) / 100

    async def stream(self, on_msg: Callable, on_status: Callable):
        """
        Open Kalshi WebSocket and call on_msg(ticker, yes_price) on each update.
        Reconnects automatically on disconnect. Calls on_status("connected"/"disconnected").
        """
        path = "/trade-api/ws/v2"
        while True:
            try:
                headers = self._sign("GET", path)
                async with websockets.connect(
                    KALSHI_WS, additional_headers=headers, ping_interval=20
                ) as ws:
                    await on_status("connected")
                    # Subscribe to ticker channel
                    await ws.send(json.dumps({
                        "id": int(time.time()),
                        "cmd": "subscribe",
                        "params": {"channels": ["ticker"]},
                    }))
                    async for raw in ws:
                        try:
                            data = json.loads(raw if isinstance(raw, str) else raw.decode())
                            msg  = data.get("msg", {})
                            msgs = msg if isinstance(msg, list) else [msg]
                            for m in msgs:
                                ticker   = m.get("market_ticker")
                                yes_bid  = m.get("yes_bid")
                                yes_ask  = m.get("yes_ask")
                                if ticker and (yes_bid is not None or yes_ask is not None):
                                    bids = [v for v in [yes_bid, yes_ask] if v is not None]
                                    price = sum(bids) / len(bids) / 100
                                    await on_msg(ticker, price)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning(f"Kalshi WS error: {e}")
                await on_status("disconnected")
                await asyncio.sleep(5)


# ─── Polymarket ───────────────────────────────────────────────────────────────

class PolyClient:
    async def get_markets(self, limit: int = 100) -> list[dict]:
        """Fetch active markets via REST — no auth needed."""
        params = {"active": "true", "closed": "false", "limit": limit}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{POLY_API}/markets", params=params)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else data.get("markets", [])

    async def stream(self, token_ids: list[str], on_msg: Callable, on_status: Callable):
        """
        Open Polymarket WebSocket for the given token IDs.
        Calls on_msg(token_id, price) on each price change.
        Reconnects automatically.
        """
        while True:
            try:
                async with websockets.connect(POLY_WS, ping_interval=20) as ws:
                    await on_status("connected")
                    if token_ids:
                        await ws.send(json.dumps({
                            "type":      "market",
                            "operation": "subscribe",
                            "assets_ids": token_ids[:50],  # server cap
                        }))
                    async for raw in ws:
                        try:
                            data  = json.loads(raw if isinstance(raw, str) else raw.decode())
                            items = data if isinstance(data, list) else [data]
                            for m in items:
                                mtype = m.get("event_type") or m.get("type", "")
                                if mtype in ("price_change", "book"):
                                    asset_id = m.get("asset_id") or m.get("market")
                                    price    = float(m.get("price", 0) or 0)
                                    if asset_id and price > 0:
                                        await on_msg(asset_id, price)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning(f"Poly WS error: {e}")
                await on_status("disconnected")
                await asyncio.sleep(5)
