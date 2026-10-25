from datetime import datetime,timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator

class AccountRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    name:str=Field(min_length=1,max_length=60)
    mode:Literal['live','replay']='replay'
    source:str=Field(default='coinmetrics_reference',max_length=60)
    symbol:str=Field(default='BTC-USD',pattern=r'^[A-Z][A-Z0-9.\-]{0,14}$')
    start:datetime|None=None
    initial_tokens:Decimal=Field(default=Decimal('500'),gt=0,le=100000,decimal_places=8)
    @field_validator('start')
    @classmethod
    def aware(cls,value):
        if value is not None and value.tzinfo is None:raise ValueError('timezone-aware start required')
        return value

class OrderRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    client_order_id:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    symbol:str=Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,14}$')
    source:str=Field(max_length=60)
    side:Literal['buy','sell']
    token_budget:Decimal|None=Field(default=None,gt=0,le=100000,decimal_places=8)
    quantity:Decimal|None=Field(default=None,gt=0,le=1000000000,decimal_places=12)
    @model_validator(mode='after')
    def sized(self):
        if self.side=='buy' and (self.token_budget is None or self.quantity is not None):raise ValueError('buy requires token_budget only, including fees')
        if self.side=='sell' and (self.quantity is None or self.token_budget is not None):raise ValueError('sell requires quantity only')
        return self

class Quote(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    symbol:str
    source:str
    market_time:datetime
    observed_at:datetime
    bid:Decimal=Field(gt=0,le=Decimal('1e12'))
    ask:Decimal=Field(gt=0,le=Decimal('1e12'))
    mode:Literal['live','replay']
    spread_basis:str='provider bid/ask'
    @model_validator(mode='after')
    def valid(self):
        if self.market_time.tzinfo is None or self.observed_at.tzinfo is None:raise ValueError('aware quote times required')
        if self.bid>self.ask:raise ValueError('crossed quote')
        return self
