import time,json,traceback
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .config.database import Session
from .config.settings import ARTIFACTS_DIR
from .models.batch import Batch
from .models.sample import Sample
from .models.evidence import Evidence
from .services.fx import advisory,backfill_held,uncovered_pairs
from .services.query_engine import compare
from .services.queue import queue
artifacts=Path(ARTIFACTS_DIR)
artifacts.mkdir(parents=True,exist_ok=True)
heartbeat=artifacts/'worker.heartbeat'
def write_artifact(batch_id,result):
    """Re-emit the JSON artifact without touching the stored evidence row."""
    artifacts.mkdir(parents=True,exist_ok=True)
    (artifacts/f'review-{batch_id}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
def status_of(result):
    if 'error' in result:return 'failed'
    return 'passed' if result.get('equivalent') else 'different'
def run_one(batch_id):
    with Session() as db:
        # Row lock serialises retries of the same batch: only one worker may produce its evidence.
        batch=db.get(Batch,batch_id,with_for_update=True)
        if not batch or batch.status=='held':return
        existing=db.scalar(select(Evidence).where(Evidence.batch_id==batch_id))
        if existing:
            # Interrupted after the evidence was committed: only restore the artifact file.
            write_artifact(batch_id,existing.result)
            if batch.status in ('queued','running'):batch.status=status_of(existing.result);db.commit()
            return
        sample=db.get(Sample,batch.sample_id)
        missing=uncovered_pairs(db,batch.fx_snapshot or [])
        if missing:
            # Upstream gained an unpriced bill after acceptance: park instead of folding NULL amounts.
            batch.status='held';batch.fx_missing=missing;db.commit();return
        batch.status='running';db.commit()
        try:
            result=compare(sample.original_sql,batch.candidate_sql,batch.fx_snapshot or [])
        except Exception as exc:
            result={'error':str(exc)[:500]}
        batch.status=status_of(result)
        db.add(Evidence(batch_id=batch_id,result=result))
        try:db.commit()
        except IntegrityError:
            db.rollback()
            stored=db.scalar(select(Evidence).where(Evidence.batch_id==batch_id))
            if stored:result=stored.result;batch.status=status_of(result);db.commit()
        write_artifact(batch_id,result)
while True:
    try:
        heartbeat.write_text(str(time.time()))
        item=queue.blpop('query-review:jobs',timeout=2)
        if item:run_one(int(item[1]))
        else:
            with Session() as db:pending=list(db.scalars(select(Batch.id).where(Batch.status.in_(['queued','running']))))
            for ident in pending:run_one(ident)
            if not pending:
                # Revisit parked batches: a price may have landed without a follow-up write.
                with Session() as db:
                    advisory(db);resumed=backfill_held(db);db.commit()
                for ident in resumed:queue.rpush('query-review:jobs',ident)
    except Exception:traceback.print_exc();time.sleep(2)
