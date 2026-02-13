
import asyncio
import os
import argparse
from kalshi_client import KalshiClient
from analyzer import KalshiAnalyzer
from datetime import datetime

async def main():
    parser = argparse.ArgumentParser(description="Kalshi Real-Time SPORTS Monitor")
    parser.add_argument("--limit", type=int, default=5, help="Number of markets to monitor")
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    args = parser.parse_args()

    client = KalshiClient()
    if args.mock:
        client.use_mock = True
    
    analyzer = KalshiAnalyzer()
    price_history = {} # ticker -> last_price
    
    print("\033[H\033[J") # Clear screen
    print(f"--- Kalshi Real-Time Monitor: SPORTS (Interval: {args.interval}s) ---")
    if not client.api_key and not args.mock:
        print("\033[93mWarning: No API Key. Live data may be limited.\033[0m")
    
    try:
        while True:
            markets = await client.get_active_markets(limit=50)
            sports_keywords = ['NBA', 'NFL', 'MLB', 'NHL', 'SOCCER', 'FOOTBALL', 'BASKETBALL', 'HOCKEY', 'SPORTS']
            filtered = [m for m in markets if any(k in getattr(m, 'ticker', '').upper() or k in getattr(m, 'title', '').upper() for k in sports_keywords)]
            
            # Print Dashboard Header
            print("\033[H") # Reset cursor to top
            print(f"--- Kalshi Real-Time Monitor: SPORTS --- Last Update: {datetime.now().strftime('%H:%M:%S')}")
            print("-" * 80)
            
            output_count = 0
            for m in filtered:
                if output_count >= args.limit:
                    break
                    
                ticker = getattr(m, 'ticker', 'N/A')
                title = getattr(m, 'title', 'N/A')[:40] + "..."
                
                ob = await client.get_market_orderbook(ticker)
                if not ob or ob.yes_bid == 0:
                    continue
                
                current_price = ob.yes_bid
                prev_price = price_history.get(ticker, current_price)
                shift = current_price - prev_price
                price_history[ticker] = current_price
                
                shift_str = ""
                if shift > 0:
                    shift_str = f" \033[92m▲ ${shift:.2f}\033[0m"
                elif shift < 0:
                    shift_str = f" \033[91m▼ ${abs(shift):.2f}\033[0m"
                
                trades = await client.get_market_trades(ticker, limit=20)
                bias = analyzer.detect_longshot_bias(trades)
                maker_edge = analyzer.calculate_maker_edge(ob)
                liquidity = analyzer.analyze_liquidity_opportunity(ob, trades)
                
                conf = analyzer.calculate_signal_confidence(bias, liquidity, maker_edge)
                action = analyzer.get_action_recommendation(current_price, conf)
                zone = analyzer.estimate_profitability_zones(current_price)
                
                # Signal Color Formatting
                sig_color = "\033[96m" if conf['score'] >= 60 else "" # Cyan for high confidence
                reset = "\033[0m"
                
                print(f"Market: {title} ({ticker})")
                print(f"  Price: ${current_price:.2f}{shift_str} | Zone: {zone}")
                print(f"  Signal: {sig_color}{conf['label']} ({conf['score']}% Confidence){reset}")
                print(f"  Action: \033[1m{action}\033[0m")
                print(f"  Edge: Maker {maker_edge*100:.2f}% | Liq: {liquidity['label']}")
                print("-" * 40)
                
                output_count += 1
            
            await asyncio.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\033[93mStopping monitor...\033[0m")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
