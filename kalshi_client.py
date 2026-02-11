
import os
import asyncio
import logging
import random
from datetime import datetime
try:
    import kalshi_python_async
    from kalshi_python_async import Configuration, ApiClient, MarketApi, ExchangeApi
    HAS_KALSHI_SDK = True
except ImportError:
    HAS_KALSHI_SDK = False

logger = logging.getLogger("KalshiClient")

class MockMarket:
    def __init__(self, ticker, title, price):
        self.ticker = ticker
        self.title = title
        self.yes_bid = price - 0.02
        self.yes_ask = price + 0.02
        self.volume = random.randint(1000, 50000)
        self.open_interest = random.randint(5000, 100000)
        self.last_price = price

class KalshiClient:
    def __init__(self):
        self.email = os.getenv("KALSHI_EMAIL")
        self.password = os.getenv("KALSHI_PASSWORD")
        
        # API Key ID for RSA Auth (from environment)
        self.api_key = os.getenv("KALSHI_API_KEY")
        
        # Path to the private key file (from environment)
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_FILE")
        
        # Read PEM content from file for KalshiAuth
        self.private_key_content = None
        if self.private_key_path:
            try:
                with open(self.private_key_path, "r") as f:
                    self.private_key_content = f.read().strip()
            except FileNotFoundError:
                logger.error(f"Private key file not found: {self.private_key_path}")

        self.env = os.getenv("KALSHI_ENV", "demo")
        self.use_mock = False

        # Credentials check: Need either API Key + Private Key OR Email + Password
        has_rsa_creds = self.api_key and self.private_key_content
        has_login_creds = self.email and self.password
        
        if not (has_rsa_creds or has_login_creds):
            logger.warning("No complete credentials found. Defaulting to MOCK mode.")
            self.use_mock = True

        if not HAS_KALSHI_SDK:
            logger.warning("Kalshi SDK not found. Defaulting to MOCK mode.")
            self.use_mock = True

        if not self.use_mock:
            if self.env == "prod":
                self.host = "https://api.kalshi.com/trade-api/v2"
            else:
                self.host = "https://demo-api.kalshi.co/trade-api/v2"

            self.config = Configuration()
            self.config.host = self.host
            
            self.api_client = ApiClient(self.config)
            
            # Setup RSA Auth if keys are present
            if has_rsa_creds:
                try:
                    from kalshi_python_async import KalshiAuth
                    # SDK set_kalshi_auth is broken (NameError + expects path but KalshiAuth wants PEM)
                    # So we manually instantiate KalshiAuth with the PEM content string
                    
                    # Strip indentation from the hardcoded key
                    # Triple quotes include the indentation which breaks PEM parsing
                    clean_key = "\n".join([line.strip() for line in self.private_key_content.split("\n") if line.strip()])
                    
                    auth = KalshiAuth(
                        key_id=self.api_key,
                        private_key_pem=clean_key
                    )
                    self.api_client.kalshi_auth = auth
                    logger.info("Configured RSA Authentication (Manual Workaround).")
                except Exception as e:
                    logger.error(f"Failed to configure RSA Auth: {e}")
                    self.use_mock = True

            self.market_api = MarketApi(self.api_client)
            self.exchange_api = ExchangeApi(self.api_client)

    async def login(self):
        if self.use_mock:
            logger.info("Mock Login Successful")
            return
        
        # If RSA Auth is set up, no explicit login call is needed
        if self.api_key and self.private_key_path:
             logger.info("RSA Auth configured, skipping explicit login.")
             return

        # If we were to support email/pass login, it would be here.
        if self.email and self.password:
            # Login logic would go here if implemented
            pass
        
    async def get_active_markets(self, limit=20, cursor=None):
        if self.use_mock:
            # Generate fake markets
            markets = []
            categories = ["Politics", "Economics", "Weather", "Tech"]
            for i in range(limit):
                cat = random.choice(categories)
                price = random.uniform(0.10, 0.90)
                m = MockMarket(
                    ticker=f"{cat.upper()}-{i}",
                    title=f"Will {cat} Event {i} happen?",
                    price=price
                )
                markets.append(m)
            return markets

        try:
            response = await self.market_api.get_markets(
                limit=limit,
                cursor=cursor
            )
            return response.markets
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    async def get_market_orderbook(self, ticker: str):
        if self.use_mock:
             price = random.uniform(0.30, 0.70)
             return type('obj', (object,), {
                 'yes_bid': round(price - 0.01, 2),
                 'yes_ask': round(price + 0.01, 2),
                 'no_bid': round((1-price) - 0.01, 2),
                 'no_ask': round((1-price) + 0.01, 2)
             })

        try:
            response = await self.market_api.get_market_orderbook(ticker)
            return response.orderbook
        except Exception as e:
            logger.error(f"Error fetching orderbook for {ticker}: {e}")
            return None
