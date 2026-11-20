from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Text,ForeignKey,DateTime,JSON,func
from datetime import datetime
from ..config.database import Base
class Batch(Base):
    __tablename__='batches'
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(120),unique=True)
    sample_id:Mapped[int]=mapped_column(ForeignKey('samples.id'))
    candidate_sql:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String(20),default='queued')
    fx_snapshot:Mapped[list]=mapped_column(JSON,default=list,nullable=False)
    fx_missing:Mapped[list]=mapped_column(JSON,default=list,nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
