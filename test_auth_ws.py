import asyncio
import websockets
import json
import logging
from kalshi_client import KalshiClient

logging.basicConfig(level=logging.DEBUG)

async def test_kalshi():
    client = KalshiClient()
    headers = client.get_auth_headers("GET", "/trade-api/v2/ws")
    print(f"Kalshi Headers: {headers}")
    if not headers:
        print("No Kalshi headers generated. Aborting.")
        return

    try:
        async with websockets.connect("wss://trading-api.kalshi.com/trade-api/v2/ws", additional_headers=headers) as ws:
            print("Connected Kalshi!")
            # Subscribe to ticker
            msg = {"id": 1, "cmd": "subscribe", "params": {"channels": ["ticker"], "markets": ["*"]}}
            await ws.send(json.dumps(msg))
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Kalshi recv: {resp}")
    except Exception as e:
        print(f"Kalshi err: {e}")

async def test_poly():
    try:
        async with websockets.connect("wss://ws-subscriptions-clob.polymarket.com/ws/market") as ws:
            print("Connected Polymarket!")
            sub_msg = {"type": "market", "operation": "subscribe", "markets": ["*"]}
            await ws.send(json.dumps(sub_msg))
            for _ in range(2):
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"Poly recv: {msg}")
    except Exception as e:
        print(f"Poly err: {e}")

if __name__ == "__main__":
    asyncio.run(test_kalshi())
    asyncio.run(test_poly())
