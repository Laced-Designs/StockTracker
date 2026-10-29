from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime, timezone

class AccountCreate(BaseModel):
    name: str=Field('My trading account',min_length=1,max_length=60)
    initial_tokens: Decimal=Field(10000,ge=100,le=1000000,max_digits=16,decimal_places=2)

class OrderRequest(BaseModel):
    client_id: str=Field(min_length=1,max_length=80,pattern=r'^[\w-]+$')
    symbol: str=Field(pattern=r'^[A-Z]{1,5}$')
    asset: Literal['equity','option']='equity'
    side: Literal['buy','sell','buy_to_open','sell_to_close','sell_to_open','buy_to_close']='buy'
    type: Literal['market','limit','stop']='market'
    quantity: Decimal=Field(gt=0,le=100000,max_digits=16,decimal_places=6)
    price: Decimal|None=Field(None,gt=0,le=1000000,max_digits=16,decimal_places=6)
    right: Literal['call','put']|None=None
    strike: Decimal|None=Field(None,gt=0,le=1000000,max_digits=16,decimal_places=2)
    expiry: datetime|None=None
    @model_validator(mode='after')
    def check(self):
        if self.type!='market' and self.price is None:raise ValueError('Limit and stop orders need a trigger price')
        if self.asset=='equity' and self.side not in ('buy','sell'):raise ValueError('Equities support buy/sell only')
        if self.asset=='option':
            if self.side in ('buy','sell'):raise ValueError('Select an option open/close action')
            if self.quantity!=int(self.quantity):raise ValueError('Options require whole contracts')
            if not self.right or not self.strike or not self.expiry:raise ValueError('Option right, strike and expiry are required')
            if self.expiry.tzinfo is None:raise ValueError('Expiry needs timezone')
            if self.type!='market':raise ValueError('Model options currently support market orders only')
        return self
