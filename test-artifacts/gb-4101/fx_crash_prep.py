"""Interruption and duplicate-delivery checks: restart resumes on locked rates,
retries never create a second evidence row."""
import json,os,time,urllib.request
import psycopg2
BASE=os.environ.get('BASE','http://127.0.0.1:19240')
DSN=os.environ['PG_DSN']
def sql(q):
    with psycopg2.connect(DSN) as c:
        with c.cursor() as cur:
            cur.execute(q);return cur.fetchall() if cur.description else None
def call(path,method='GET',body=None,token=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(BASE+path,data=data,method=method,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    with urllib.request.urlopen(req) as r:return r.status,json.load(r)
def main():
    token=call('/auth/login','POST',{'email':'operator@chenggang.test','password':'ColdChain!17'})[1]['token']
    ident=sql("SELECT id FROM batches WHERE status='passed' ORDER BY id LIMIT 1")[0][0]
    before=sql(f"SELECT result::text FROM evidence WHERE batch_id={ident}")[0][0]
    snap=json.loads(sql(f"SELECT fx_snapshot::text FROM batches WHERE id={ident}")[0][0])
    print('baseline evidence rows',sql(f"SELECT count(*) FROM evidence WHERE batch_id={ident}")[0][0])
    # Simulate a crash after the evidence commit and a rate change while the artifact is missing.
    sql(f"UPDATE batches SET status='running' WHERE id={ident}")
    pair=snap[0]
    sql(f"UPDATE fx_rates SET rate=rate+1 WHERE currency='{pair['currency']}' AND rate_date=DATE '{pair['date']}'")
    open('/tmp/fx_crash_target','w').write(str(ident))
    print('marked running',ident,'and changed mother-table rate for',pair['currency'],pair['date'])
if __name__=='__main__':main()
