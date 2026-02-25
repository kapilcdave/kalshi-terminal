import asyncio
import websockets
import json

kalshi_wss = "wss://trading-api.kalshi.com/trade-api/v2/ws"

async def test_kalshi():
    try:
        async with websockets.connect(kalshi_wss) as ws:
            msg = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker"],
                    "markets": ["*"]
                }
            }
            await ws.send(json.dumps(msg))
            resp = await asyncio.wait_for(ws.recv(), timeout=5)
            print(f"Kalshi recv: {str(resp)[:100]}")
    except Exception as e:
        print(f"Kalshi err: {e}")

async def test_poly():
    try:
        async with websockets.connect("wss://ws-subscriptions-clob.polymarket.com/ws/market") as ws:
            # Let's try assets instead of assets_ids or just token_id 
            # Or market with tokens?
            sub_msg = {
                "assets_ids": ["16678291189211314787145083999015737376658799626183230671758641503291735614088"],
                "type": "market",
                "operation": "subscribe"
            }
            await ws.send(json.dumps(sub_msg))
            for i in range(2):
                resp = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"Poly recv: {str(resp)[:100]}")
    except Exception as e:
        print(f"Poly err: {e}")

async def main():
    await test_kalshi()
    await test_poly()

asyncio.run(main())
