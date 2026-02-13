
import math
import numpy as np
from typing import List, Dict, Any

class KalshiAnalyzer:
    def __init__(self):
        pass

    def calculate_calibration(self, markets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculates calibration: Actual Outcome Frequency vs. Predicted Probability (Price).
        Expects markets to have 'final_price' (at settlement) and 'actual_outcome' (0 or 1).
        """
        bins = np.linspace(0, 1, 11)  # 10 bins: 0-10%, 10-20%, ..., 90-100%
        bin_counts = np.zeros(10)
        bin_outcomes = np.zeros(10)
        
        for m in markets:
            price = m.get('price', 0)
            outcome = m.get('outcome', 0) # 1 for YES, 0 for NO
            
            bin_idx = min(int(price * 10), 9)
            bin_counts[bin_idx] += 1
            bin_outcomes[bin_idx] += outcome
            
        calibration = []
        for i in range(10):
            if bin_counts[i] > 0:
                expected = (bins[i] + bins[i+1]) / 2
                actual = bin_outcomes[i] / bin_counts[i]
                calibration.append({
                    'bin': f"{int(bins[i]*100)}-{int(bins[i+1]*100)}%",
                    'expected': round(expected, 3),
                    'actual': round(actual, 3),
                    'count': int(bin_counts[i]),
                    'diff': round(actual - expected, 3)
                })
        
        return calibration

    def detect_longshot_bias(self, trades: List[Any]) -> Dict[str, Any]:
        """
        Detects longshot bias: Takers paying more for low probability outcomes.
        """
        # Simplify: If trades at < $0.20 are dominated by YES takers, it's a signal.
        yes_takers = 0
        no_takers = 0
        total_low_prob_volume = 0
        
        for t in trades:
            price = getattr(t, 'yes_price', 0)
            side = getattr(t, 'taker_side', '')
            
            if price < 0.20:
                if side == 'yes':
                    yes_takers += 1
                else:
                    no_takers += 1
                total_low_prob_volume += getattr(t, 'count', 0)
        
        return {
            'low_prob_yes_takers': yes_takers,
            'low_prob_no_takers': no_takers,
            'bias_detected': yes_takers > no_takers * 1.5 if no_takers > 0 else (yes_takers > 5)
        }

    def brier_score(self, predicted: float, actual: int) -> float:
        """Calculates Brier Score: (predicted - actual)^2"""
        return (predicted - actual) ** 2

    def calculate_maker_edge(self, orderbook) -> float:
        """
        Estimates the 'Maker Edge' based on the spread.
        The wider the spread, the more makers profit from providing liquidity.
        """
        if not orderbook:
            return 0
        
        yes_bid = getattr(orderbook, 'yes_bid', 0)
        yes_ask = getattr(orderbook, 'yes_ask', 0)
        
        if yes_ask > 0:
            spread = (yes_ask - yes_bid) / 100 # Prices are typically in cents/points [0, 1]
            return round(spread / 2, 4) # Edge is roughly half the spread
        return 0

    def analyze_liquidity_opportunity(self, orderbook, trades: List[Any]) -> Dict[str, Any]:
        """
        Identifies where makers are likely making the most money.
        High spread + High volume = Profitable for makers.
        """
        if not orderbook:
            return {'score': 0, 'label': 'Low'}
            
        yes_bid = getattr(orderbook, 'yes_bid', 0)
        yes_ask = getattr(orderbook, 'yes_ask', 0)
        spread = (yes_ask - yes_bid)
        
        # Look at trade frequency (last 50 trades)
        avg_trade_size = sum([getattr(t, 'count', 0) for t in trades]) / len(trades) if trades else 0
        
        # Profitability score for makers: Higher spread * higher volume
        score = spread * avg_trade_size / 100
        
        return {
            'score': round(score, 2),
            'label': 'High' if score > 0.5 else 'Medium' if score > 0.1 else 'Low'
        }

    def calculate_signal_confidence(self, bias: Dict[str, Any], liquidity: Dict[str, Any], maker_edge: float) -> Dict[str, Any]:
        """
        Calculates a confidence score (0-100) for a signal.
        """
        score = 0
        reasons = []
        
        # Bias is a strong signal
        if bias['bias_detected']:
            score += 40
            reasons.append("Historical Longshot Bias detected")
            
        # Liquidity (Liquidity = certainity of exit)
        if liquidity['score'] > 0.5:
            score += 30
            reasons.append("High liquidity (low slippage)")
        elif liquidity['score'] > 0.1:
            score += 15
            reasons.append("Moderate liquidity")
            
        # Maker Edge (Spread tightness)
        if maker_edge > 0.005: # > 0.5% edge
            score += 30
            reasons.append("Strong maker yield from spread")
            
        return {
            'score': min(100, score),
            'label': 'VERY HIGH' if score >= 80 else 'HIGH' if score >= 60 else 'MODERATE' if score >= 40 else 'LOW',
            'reasons': reasons
        }

    def get_action_recommendation(self, price: float, confidence: Dict[str, Any]) -> str:
        if confidence['score'] < 40:
            return "WATCH (No clear edge)"
            
        if price < 0.20:
            return "SELL/SHORT YES (High probability of correction)"
        elif price > 0.80:
            return "BUY YES (Underpriced favorite)"
        
        return "MAKER (Provide liquidity to capture spread)"

    def estimate_profitability_zones(self, price: float) -> str:
        """
        Identifies if a price is in a 'Value' or 'Risk' zone based on common biases.
        - Longshot Bias (<0.20): YES is usually overpriced.
        - Pessimism Bias (>0.80): YES is usually underpriced for favorites.
        """
        if price < 0.20:
            return "\033[91mRisk (YES Overpriced)\033[0m" # Red
        elif price > 0.80:
            return "\033[92mValue (YES Underpriced)\033[0m" # Green
        return "Neutral"

    def aggregate_score(self, markets: List[Dict[str, Any]]) -> float:
        scores = [self.brier_score(m['price'], m['outcome']) for m in markets if 'price' in m and 'outcome' in m]
        return sum(scores) / len(scores) if scores else 0
