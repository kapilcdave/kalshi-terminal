import logging
import difflib

logger = logging.getLogger("ArbEngine")

class ArbEngine:
    def __init__(self, kalshi_client, poly_client):
        self.kalshi = kalshi_client
        self.poly = poly_client
        self.mappings = {} # Manual or discovered mappings: Poly Token ID -> Kalshi Ticker

    def find_matches(self, kalshi_markets, poly_markets, threshold=0.6):
        """
        Simple fuzzy matching between Kalshi titles and Polymarket questions.
        Returns a list of potential (Kalshi, Poly) pairs.
        """
        matches = []
        for k in kalshi_markets:
            k_title = k.title.lower()
            for p in poly_markets:
                p_title = p.get('question', '').lower()
                
                # Use difflib for basic similarity
                ratio = difflib.SequenceMatcher(None, k_title, p_title).ratio()
                if ratio > threshold:
                    matches.append({
                        "kalshi": k,
                        "poly": p,
                        "ratio": ratio
                    })
        return matches

    def calculate_spread(self, kalshi_price, poly_price):
        """
        Calculates arbitrage spread between Kalshi and Poly.
        Kalshi price is usually 0.0-1.0 (binary option).
        Poly price is also 0.0-1.0.
        """
        # Example: Kalshi Yes at 0.45, Poly Yes at 0.50
        # Spread = Poly - Kalshi
        spread = poly_price - kalshi_price
        return spread

    async def get_spread_opportunity(self, kalshi_ticker, poly_token_id):
        """
        Fetches live order books and calculates actionable spread.
        """
        k_ob = await self.kalshi.get_market_orderbook(kalshi_ticker)
        p_ob = await self.poly.get_market_book(poly_token_id)

        if not k_ob or not p_ob:
            return None

        # Action: Buy Kalshi Yes, Sell Poly Yes (if K_Ask < P_Bid)
        # Kalshi Ask is price to buy
        # Poly Bid is price to sell (or vice-versa)
        
        # Poly CLOB 'bids' and 'asks' are lists of {price, size}
        p_bids = p_ob.get('bids', [])
        p_asks = p_ob.get('asks', [])

        if not p_bids or not p_asks:
            return None

        p_highest_bid = float(p_bids[0]['price'])
        p_lowest_ask = float(p_asks[0]['price'])
        
        k_lowest_ask = k_ob.yes_ask
        k_highest_bid = k_ob.yes_bid

        # Opportunity 1: Buy Kalshi, Sell Poly
        arb_k_to_p = p_highest_bid - k_lowest_ask
        
        # Opportunity 2: Buy Poly, Sell Kalshi
        arb_p_to_k = k_highest_bid - p_lowest_ask

        return {
            "buy_kalshi_sell_poly": arb_k_to_p,
            "buy_poly_sell_kalshi": arb_p_to_k,
            "details": {
                "kalshi": {"bid": k_highest_bid, "ask": k_lowest_ask},
                "poly": {"bid": p_highest_bid, "ask": p_lowest_ask}
            }
        }
