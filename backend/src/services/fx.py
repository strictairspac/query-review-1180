"""Foreign-currency settlement: lock rates per batch, hold batches with missing prices."""
import re
from datetime import date
from decimal import Decimal,InvalidOperation
from sqlalchemy import select,text
from fastapi import HTTPException
from ..models.batch import Batch
from ..models.fx_rate import FxRate
from .queue import queue
LOCK_KEY=4101
SCALE=Decimal('0.000001')
CURRENCY_RE=re.compile(r'^[A-Z]{3}$')
def advisory(db):db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':LOCK_KEY})
def scale(value):return format(Decimal(value).quantize(SCALE),'f')
def needed_pairs(db):
    """Every non-CNY (currency, transport_date) present in the upstream bills."""
    return [(c,d) for c,d in db.execute(text("SELECT DISTINCT currency, transport_date FROM invoices WHERE currency<>'CNY' ORDER BY 1,2"))]
def rate_map(db):return {(r.currency,r.rate_date):r.rate for r in db.scalars(select(FxRate))}
def _entry(cur,day,rate):return {'currency':cur,'date':day.isoformat(),'rate':scale(rate)}
def build_snapshot(db):
    """Freeze the rates that exist at acceptance; report every pair still missing a price."""
    rates=rate_map(db);snapshot=[];missing=[]
    for cur,day in needed_pairs(db):
        rate=rates.get((cur,day))
        if rate is None:missing.append({'currency':cur,'date':day.isoformat()})
        else:snapshot.append(_entry(cur,day,rate))
    return snapshot,missing
def uncovered_pairs(db,snapshot):
    """Pairs used by the bills that the locked snapshot does not price."""
    locked={(str(x.get('currency')),str(x.get('date'))) for x in (snapshot or [])}
    return [{'currency':cur,'date':day.isoformat()} for cur,day in needed_pairs(db) if (cur,day.isoformat()) not in locked]
def backfill_held(db):
    """Fill gaps in held batches from the first value stored; never rewrite locked rates."""
    rates=rate_map(db);resumed=[]
    for batch in db.scalars(select(Batch).where(Batch.status=='held')):
        snapshot=list(batch.fx_snapshot or []);missing=list(batch.fx_missing or []);remaining=[]
        for item in missing:
            try:key=(str(item['currency']),date.fromisoformat(str(item['date'])))
            except Exception:remaining.append(item);continue
            rate=rates.get(key)
            if rate is None:remaining.append(item)
            else:snapshot.append(_entry(*key,rate))
        if len(remaining)!=len(missing):
            batch.fx_snapshot=sorted(snapshot,key=lambda x:(x['currency'],x['date']))
            batch.fx_missing=remaining
            if not remaining:batch.status='queued';resumed.append(batch.id)
    return resumed
def save_rate(db,data,correct):
    currency=data.currency.strip().upper()
    if not CURRENCY_RE.fullmatch(currency):raise HTTPException(422,'币种须为三位大写字母')
    try:rate=Decimal(str(data.rate))
    except (InvalidOperation,ValueError):raise HTTPException(422,'汇率格式错误')
    if rate<=0:raise HTTPException(422,'汇率必须大于 0')
    advisory(db)
    existing=db.scalar(select(FxRate).where(FxRate.currency==currency,FxRate.rate_date==data.rate_date))
    created=False;updated=False
    if existing is None:
        db.add(FxRate(currency=currency,rate_date=data.rate_date,rate=rate));created=True
    elif correct and Decimal(existing.rate)!=rate:
        existing.rate=rate;updated=True
    db.flush()
    resumed=backfill_held(db)
    db.commit()
    for ident in resumed:queue.rpush('query-review:jobs',ident)
    row=db.scalar(select(FxRate).where(FxRate.currency==currency,FxRate.rate_date==data.rate_date))
    return {'created':created,'updated':updated,'resumed_batch_ids':resumed,'rate':serialize(row)}
def serialize(x):return {'id':x.id,'currency':x.currency,'rate_date':x.rate_date.isoformat(),'rate':scale(x.rate),'created_at':str(x.created_at),'updated_at':str(x.updated_at)}
def list_rates(db):return [serialize(x) for x in db.scalars(select(FxRate).order_by(FxRate.currency,FxRate.rate_date))]
