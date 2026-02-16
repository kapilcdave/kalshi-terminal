import httpx
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("PolymarketClient")

class PolymarketClient:
    GAMMA_URL = "https://gamma-api.polymarket.com"
    CLOB_URL = "https://clob.polymarket.com"

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_active_markets(self, limit: int = 20):
        """
        Fetch active markets from Gamma API.
        """
        url = f"{self.GAMMA_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit
        }
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            markets = response.json()
            # Return list of market objects
            return markets
        except Exception as e:
            logger.error(f"Error fetching Polymarket markets: {e}")
            return []

    async def get_market_book(self, token_id: str):
        """
        Fetch order book for a specific token (market) from CLOB API.
        """
        url = f"{self.CLOB_URL}/book"
        params = {"token_id": token_id}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching order book for {token_id}: {e}")
            return None

    async def get_price(self, token_id: str):
        """
        Fetch mid price for a specific token from CLOB API.
        """
        url = f"{self.CLOB_URL}/price"
        params = {"token_id": token_id}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching price for {token_id}: {e}")
            return None

    async def close(self):
        await self.client.aclose()

if __name__ == "__main__":
    async def main():
        poly = PolymarketClient()
        markets = await poly.get_active_markets(limit=5)
        for m in markets:
            print(f"Market: {m.get('question')} (ID: {m.get('id')})")
            if m.get('tokens'):
                token = m['tokens'][0]['token_id']
                price = await poly.get_price(token)
                print(f"  Price: {price}")
        await poly.close()

    asyncio.run(main())
