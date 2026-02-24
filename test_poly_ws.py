import asyncio
import json
import websockets
import httpx

async def test_poly():
    print("Fetching active tokens...")
    async with httpx.AsyncClient() as client:
        r = await client.get('https://gamma-api.polymarket.com/markets?active=true&limit=10')
        markets = r.json()
        tokens = [m['tokens'][0]['token_id'] for m in markets if m.get('tokens')]
    
    print(f"Subscribing to {len(tokens)} tokens...")
    async with websockets.connect("wss://ws-subscriptions-clob.polymarket.com/ws/market") as ws:
        # Try assets_ids
        sub1 = {"type": "market", "operation": "subscribe", "assets_ids": tokens}
        await ws.send(json.dumps(sub1))
        
        for _ in range(3):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print("Received:", msg[:200])
            except asyncio.TimeoutError:
                print("Timeout waiting for message")
                break

asyncio.run(test_poly())
