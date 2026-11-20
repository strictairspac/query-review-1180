from datetime import date
from decimal import Decimal
from pydantic import BaseModel,Field
class RateInput(BaseModel):
    currency:str=Field(min_length=3,max_length=3)
    rate_date:date
    rate:Decimal=Field(gt=0,max_digits=18,decimal_places=6)
