from datetime import datetime, timezone
from typing import Literal
import math
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError("timezone-aware timestamp required")
        return value.astimezone(timezone.utc)

class MarketTick(Record):
    price: float = Field(gt=0)
    size: float = Field(ge=0)
    source: str
    trade_id: str
    side: Literal["buy", "sell", "unknown"] = "unknown"

class OHLCV(Record):
    interval: Literal["1m", "15m", "1h", "1d"] = "1m"
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    source: str
    @model_validator(mode="after")
    def valid_range(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("inconsistent OHLC range")
        return self

class PatternFeatureVector(Record):
    interval: str
    window: int = Field(ge=5)
    version: str = "v1"
    values: list[float]
    @field_validator("values")
    @classmethod
    def finite(cls, v):
        if not v or not all(math.isfinite(x) for x in v):
            raise ValueError("finite nonempty vector required")
        return v

class HorizonPrediction(BaseModel):
    horizon: str
    probability_up: float | None = Field(default=None, ge=0, le=1)
    expected_return: float | None = None
    samples: int = 0
    effective_samples: float = 0
    interval_95: tuple[float, float] | None = None

class PredictionSignal(Record):
    mode: Literal["synthetic", "historical", "live"]
    method: str = "cosine+DTW empirical analogs"
    pattern_similarity: float = Field(ge=0, le=1)
    predictions: list[HorizonPrediction]
    alert: bool
    historical_accuracy: float | None = None
    matches: list[dict] = []
    note: str = "Empirical analog frequencies; uncalibrated and dependent samples."
