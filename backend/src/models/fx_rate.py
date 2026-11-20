from datetime import date,datetime
from decimal import Decimal
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Date,Numeric,DateTime,UniqueConstraint,func
from ..config.database import Base
class FxRate(Base):
    __tablename__='fx_rates'
    __table_args__=(UniqueConstraint('currency','rate_date',name='uq_fx_currency_date'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    currency:Mapped[str]=mapped_column(String(3),nullable=False)
    rate_date:Mapped[date]=mapped_column(Date,nullable=False)
    rate:Mapped[Decimal]=mapped_column(Numeric(18,6),nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    updated_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now(),onupdate=func.now())
