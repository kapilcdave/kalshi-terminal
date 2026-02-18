import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from rapidfuzz import fuzz, process

STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
    'dare', 'ought', 'used', 'it', 'its', 'this', 'that', 'these', 'those',
    'i', 'you', 'he', 'she', 'we', 'they', 'what', 'which', 'who', 'whom',
    'when', 'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
    'own', 'same', 'so', 'than', 'too', 'very', 'just', 'if', 'then', 'else',
    'will', 'event', 'happen', 'will', 'occur'
}

@dataclass
class UnifiedMarket:
    id: str
    event_name: str
    normalized_name: str
    kalshi_ticker: Optional[str] = None
    kalshi_price: float = 0.0
    kalshi_volume: int = 0
    poly_token_id: Optional[str] = None
    poly_question: Optional[str] = None
    poly_price: float = 0.0
    poly_volume: int = 0
    price_history: List[Dict[str, Any]] = field(default_factory=list)
    last_update: float = 0.0
    
    @property
    def delta_percent(self) -> float:
        if self.kalshi_price > 0 and self.poly_price > 0:
            return ((self.poly_price - self.kalshi_price) / self.kalshi_price) * 100
        return 0.0
    
    @property
    def has_both_prices(self) -> bool:
        return self.kalshi_price > 0 and self.poly_price > 0
    
    @property
    def total_volume(self) -> int:
        return self.kalshi_volume + self.poly_volume


class MarketMatcher:
    MATCH_THRESHOLD = 85
    
    def __init__(self, threshold: int = MATCH_THRESHOLD):
        self.threshold = threshold
        self.stop_words = STOP_WORDS
        
    def normalize_title(self, title: str) -> str:
        if not title:
            return ""
        title = title.lower()
        title = re.sub(r'[^\w\s]', ' ', title)
        words = title.split()
        filtered = [w for w in words if w not in self.stop_words]
        normalized = ' '.join(filtered)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def create_market_id(self, normalized_name: str) -> str:
        clean = re.sub(r'[^a-z0-9]', '', normalized_name)
        return clean[:50]
    
    def match_markets(
        self, 
        kalshi_markets: List[Any], 
        poly_markets: List[Any]
    ) -> Dict[str, UnifiedMarket]:
        unified_markets = {}
        
        kalshi_normalized = {}
        for km in kalshi_markets:
            title = getattr(km, 'title', '') or getattr(km, 'ticker', '')
            norm = self.normalize_title(title)
            uid = self.create_market_id(norm)
            kalshi_normalized[uid] = {
                'market': km,
                'normalized': norm,
                'ticker': getattr(km, 'ticker', ''),
                'price': getattr(km, 'yes_bid', 0) or getattr(km, 'last_price', 0),
                'volume': getattr(km, 'volume', 0)
            }
        
        for pm in poly_markets:
            question = pm.get('question', '')
            norm = self.normalize_title(question)
            uid = self.create_market_id(norm)
            
            token_id = None
            price = 0.0
            volume = 0
            
            if pm.get('tokens') and len(pm['tokens']) > 0:
                token_id = pm['tokens'][0].get('token_id')
            
            outcome_prices = pm.get('outcomePrices', [])
            if outcome_prices and len(outcome_prices) > 0:
                try:
                    price = float(outcome_prices[0])
                except (ValueError, TypeError):
                    price = 0.0
            
            try:
                volume = int(pm.get('volume', 0) or 0)
            except (ValueError, TypeError):
                volume = 0
            
            if uid in unified_markets:
                unified_markets[uid].poly_token_id = token_id
                unified_markets[uid].poly_question = question
                unified_markets[uid].poly_price = price
                unified_markets[uid].poly_volume = volume
            else:
                unified_markets[uid] = UnifiedMarket(
                    id=uid,
                    event_name=question or norm,
                    normalized_name=norm,
                    poly_token_id=token_id,
                    poly_question=question,
                    poly_price=price,
                    poly_volume=volume
                )
        
        for uid, km_data in kalshi_normalized.items():
            if uid in unified_markets:
                unified_markets[uid].kalshi_ticker = km_data['ticker']
                unified_markets[uid].kalshi_price = km_data['price']
                unified_markets[uid].kalshi_volume = km_data['volume']
            else:
                unified_markets[uid] = UnifiedMarket(
                    id=uid,
                    event_name=km_data['normalized'],
                    normalized_name=km_data['normalized'],
                    kalshi_ticker=km_data['ticker'],
                    kalshi_price=km_data['price'],
                    kalshi_volume=km_data['volume']
                )
        
        unmatched_poly = []
        for pm in poly_markets:
            question = pm.get('question', '')
            norm = self.normalize_title(question)
            uid = self.create_market_id(norm)
            
            if uid not in kalshi_normalized:
                unmatched_poly.append((norm, uid, pm))
        
        for norm, uid, pm in unmatched_poly:
            if uid not in unified_markets:
                token_id = None
                price = 0.0
                volume = 0
                
                if pm.get('tokens') and len(pm['tokens']) > 0:
                    token_id = pm['tokens'][0].get('token_id')
                
                outcome_prices = pm.get('outcomePrices', [])
                if outcome_prices and len(outcome_prices) > 0:
                    try:
                        price = float(outcome_prices[0])
                    except (ValueError, TypeError):
                        price = 0.0
                
                try:
                    volume = int(pm.get('volume', 0) or 0)
                except (ValueError, TypeError):
                    volume = 0
                
                unified_markets[uid] = UnifiedMarket(
                    id=uid,
                    event_name=question,
                    normalized_name=norm,
                    poly_token_id=token_id,
                    poly_question=question,
                    poly_price=price,
                    poly_volume=volume
                )
        
        return unified_markets
    
    def fuzzy_match_single(
        self, 
        query: str, 
        market_list: List[Dict[str, str]],
        key: str = "event_name"
    ) -> Optional[Dict[str, str]]:
        if not market_list:
            return None
            
        norm_query = self.normalize_title(query)
        choices = [self.normalize_title(m[key]) for m in market_list]
        
        if not choices:
            return None
            
        result = process.extractOne(
            norm_query, 
            choices,
            scorer=fuzz.token_set_ratio
        )
        
        if result and result[1] >= self.threshold:
            idx = choices.index(result[0])
            return market_list[idx]
        
        return None
