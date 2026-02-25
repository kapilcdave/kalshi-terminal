import os
import json
import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger("AgentManager")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

class AgentState(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTIVE = "active"

@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict

@dataclass
class Message:
    role: str
    content: str
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None

@dataclass
class AgentContext:
    state: AgentState = AgentState.IDLE
    last_analysis: str = ""
    spread_alerts: List[Dict] = field(default_factory=list)
    conversation_history: List[Message] = field(default_factory=list)

class AgentManager:
    def __init__(
        self,
        store,
        api_key: Optional[str] = None,
        model: str = "stepfun/step-3.5-flash:free",
        max_tokens: int = 1024
    ):
        self.store = store
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model
        self.max_tokens = max_tokens
        
        self.context = AgentContext()
        self._running = False
        self._analysis_task: Optional[asyncio.Task] = None
        
        self._output_callbacks: List[Callable] = []
        
        self._tools = self._build_tools()
        
    def _build_tools(self) -> List[ToolDefinition]:
        return [
            ToolDefinition(
                name="get_market_data",
                description="""Get current market data for prediction markets. 
Returns unified market information including prices from both Kalshi and Polymarket, 
volume, and price spread. Use this to analyze arbitrage opportunities.""",
                input_schema={
                    "type": "object",
                    "properties": {
                        "market_id": {
                            "type": "string", 
                            "description": "Optional specific market ID to query"
                        },
                        "min_spread": {
                            "type": "number",
                            "description": "Minimum spread percentage to filter (default 0)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of markets to return (default 10)"
                        }
                    }
                }
            ),
            ToolDefinition(
                name="get_price_history",
                description="""Get historical price data for a specific market. 
Returns time series data showing price movements over time.""",
                input_schema={
                    "type": "object",
                    "properties": {
                        "market_id": {
                            "type": "string",
                            "description": "The market ID to get history for"
                        }
                    },
                    "required": ["market_id"]
                }
            ),
            ToolDefinition(
                name="analyze_spread",
                description="""Analyze a specific spread opportunity between markets.
Returns detailed analysis of the arbitrage potential.""",
                input_schema={
                    "type": "object",
                    "properties": {
                        "market_id": {
                            "type": "string",
                            "description": "The market ID to analyze"
                        }
                    },
                    "required": ["market_id"]
                }
            )
        ]
        
    def add_output_callback(self, callback: Callable):
        self._output_callbacks.append(callback)
        
    async def _notify_output(self, text: str, style: str = "default"):
        for cb in self._output_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(text, style)
                else:
                    cb(text, style)
            except Exception:
                pass
                
    async def start(self):
        self._running = True
        self._analysis_task = asyncio.create_task(self._spread_monitor())
        
        await self._notify_output(
            "[Clawdbot v1.0] Initialized and monitoring markets...",
            "success"
        )
        
    async def stop(self):
        self._running = False
        
        if self._analysis_task:
            self._analysis_task.cancel()
            try:
                await self._analysis_task
            except asyncio.CancelledError:
                pass
                
    async def _spread_monitor(self):
        last_alerted: Dict[str, float] = {}
        alert_cooldown = 60
        
        while self._running:
            await asyncio.sleep(5)
            
            try:
                spread_markets = self.store.get_markets_with_spread(min_spread=3.0)
                
                for market in spread_markets:
                    current_time = time.time()
                    last_alert = last_alerted.get(market.id, 0)
                    
                    if (current_time - last_alert) < alert_cooldown:
                        continue
                        
                    last_alerted[market.id] = current_time
                    
                    direction = "lagging" if market.delta_percent > 0 else "leading"
                    
                    message = (
                        f"[SPREAD ALERT] {market.event_name[:40]}...\n"
                        f"  Delta: {market.delta_percent:+.2f}% | "
                        f"Poly {direction} by {abs(market.delta_percent):.1f}%\n"
                        f"  Kalshi: {market.kalshi_price:.2f} | Poly: {market.poly_price:.2f}"
                    )
                    
                    await self._notify_output(message, "warning")
                    
                    context = self.context
                    if len(context.spread_alerts) > 10:
                        context.spread_alerts = context.spread_alerts[-10:]
                    context.spread_alerts.append({
                        "market_id": market.id,
                        "delta": market.delta_percent,
                        "timestamp": current_time
                    })
                    
            except Exception as e:
                logger.error(f"Spread monitor error: {e}")
                
    async def process_message(self, user_message: str) -> str:
        if not self.api_key:
            return "Error: Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env"
            
        self.context.state = AgentState.THINKING
        
        await self._notify_output(f"[You]: {user_message}", "user")
        
        messages = [
            Message(
                role="user",
                content=user_message
            )
        ]
        
        try:
            response = await self._call_llm(messages)
            
            self.context.state = AgentState.ACTIVE
            self.context.last_analysis = response
            
            await self._notify_output(f"[Clawdbot]: {response}", "assistant")
            
            return response
            
        except Exception as e:
            self.context.state = AgentState.IDLE
            error_msg = f"Error: {str(e)}"
            await self._notify_output(error_msg, "error")
            return error_msg
            
    async def _call_llm(self, messages: List[Message]) -> str:
        system_prompt = """You are Clawdbot, an AI assistant for a prediction market terminal that 
monitors prices from both Kalshi and Polymarket. You help users analyze market data, 
spot arbitrage opportunities, and understand price movements.

You have access to market data tools. When users ask about spreads or price differences,
use the get_market_data tool to fetch current prices and analyze opportunities.

Be concise, analytical, and focused on actionable insights."""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/kapilcdave/kalshi",
            "X-Title": "Kalshi Terminal",
            "Content-Type": "application/json"
        }
        
        # OpenRouter uses OpenAI format
        openai_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            msg = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            openai_messages.append(msg)

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": openai_messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema
                    }
                }
                for t in self._tools
            ]
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload
            )
            
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code} - {response.text}")
                
            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return "No response from LLM"
                
            choice = choices[0]
            message = choice.get("message", {})
            
            if "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    tool_result = await self._handle_tool_call(tool_call.get("function", {}))
                    messages.append(Message(
                        role="assistant",
                        content="", # OpenAI expects tool calls in assistant message
                        tool_calls=[tool_call]
                    ))
                    messages.append(Message(
                        role="tool",
                        content=tool_result,
                        tool_call_id=tool_call.get("id")
                    ))
                
                return await self._call_llm(messages)
                
            return message.get("content", "No content")
            
    async def _handle_tool_call(self, tool_block: Dict) -> str:
        tool_name = tool_block.get("name", "")
        tool_input = tool_block.get("input", {})
        
        if tool_name == "get_market_data":
            return await self._tool_get_market_data(tool_input)
        elif tool_name == "get_price_history":
            return await self._tool_get_price_history(tool_input)
        elif tool_name == "analyze_spread":
            return await self._tool_analyze_spread(tool_input)
        else:
            return f"Unknown tool: {tool_name}"
            
    async def _tool_get_market_data(self, params: Dict) -> str:
        min_spread = params.get("min_spread", 0)
        limit = params.get("limit", 10)
        
        if params.get("market_id"):
            market = self.store.get_market(params["market_id"])
            if market:
                return json.dumps({
                    "event_name": market.event_name,
                    "kalshi_price": market.kalshi_price,
                    "poly_price": market.poly_price,
                    "delta_percent": market.delta_percent,
                    "volume": market.total_volume
                }, indent=2)
            return "Market not found"
            
        markets = self.store.get_all_markets()
        filtered = [m for m in markets if abs(m.delta_percent) >= min_spread]
        filtered.sort(key=lambda m: abs(m.delta_percent), reverse=True)
        
        result = []
        for m in filtered[:limit]:
            result.append({
                "event_name": m.event_name[:50],
                "kalshi_price": m.kalshi_price,
                "poly_price": m.poly_price,
                "delta_percent": round(m.delta_percent, 2),
                "volume": m.total_volume
            })
            
        return json.dumps(result, indent=2)
        
    async def _tool_get_price_history(self, params: Dict) -> str:
        market_id = params.get("market_id")
        if not market_id:
            return "market_id required"
            
        history = self.store.get_price_history(market_id)
        
        result = []
        for point in history[-20:]:
            result.append({
                "timestamp": point.timestamp,
                "kalshi_price": point.kalshi_price,
                "poly_price": point.poly_price
            })
            
        return json.dumps(result, indent=2)
        
    async def _tool_analyze_spread(self, params: Dict) -> str:
        market_id = params.get("market_id")
        if not market_id:
            return "market_id required"
            
        market = self.store.get_market(market_id)
        if not market:
            return "Market not found"
            
        if not market.has_both_prices:
            return f"Insufficient data: only have price from {'Kalshi' if market.kalshi_price > 0 else 'Polymarket'}"
            
        spread = market.delta_percent
        direction = "Kalshi underpriced" if spread < 0 else "Polymarket underpriced"
        
        return f"""Spread Analysis: {market.event_name}
- Spread: {spread:+.2f}%
- Direction: {direction}
- Kalshi: ${market.kalshi_price:.2f}
- Polymarket: ${market.poly_price:.2f}
- Combined Volume: {market.total_volume:,}"""
