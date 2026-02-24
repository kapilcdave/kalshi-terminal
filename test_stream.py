import asyncio
import os
from unified_store import UnifiedStore
from live_engine import LiveEngine
from kalshi_client import KalshiClient

async def main():
    store = UnifiedStore()
    kalshi = KalshiClient()
    engine = LiveEngine(
        store=store,
        kalshi_env=os.getenv("KALSHI_ENV", "demo"),
        kalshi_api_key=os.getenv("KALSHI_API_KEY"),
        kalshi_private_key=kalshi.private_key_content if not kalshi.use_mock else None
    )

    def on_raw(platform, msg):
        print(f"[{platform}] {msg[:100]}")

    engine.add_raw_callback(on_raw)
    print("Starting engine...")
    await engine.start()
    print("Waiting 10 seconds...")
    await asyncio.sleep(10)
    print("Stopping engine...")
    await engine.stop()

if __name__ == "__main__":
    asyncio.run(main())
