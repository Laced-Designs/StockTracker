from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='ST_', env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./stocktracker.db'
    mode: Literal['demo', 'live'] = 'demo'
    redis_url: str = ''
    alpaca_key: str = ''
    alpaca_secret: str = ''
    symbols: str = 'AAPL,MSFT,NVDA,SPY,AMZN,TSLA'
    tick_seconds: float = Field(5, ge=1)
    fee_bps: int = Field(1, ge=0, le=100)
    slippage_bps: int = Field(2, ge=0, le=100)
