"""Staged end-to-end checks for per-transport-day RMB folding and rate locking.

Two stages because the worker must not drain the queue between them:
  python3 fx_e2e.py accept   # accept a complete batch, then open a price gap
  python3 fx_e2e.py verify   # start worker first; assert held/resume/correction behaviour
Disposable database seeded by scripts.seed_demo.
"""
import json,os,sys,time,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import psycopg2
BASE=os.environ.get('BASE','http://127.0.0.1:19240')
DSN=os.environ['PG_DSN']
STATE=os.environ.get('STATE','/tmp/fx_e2e_state.json')
def sql(query):
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return cur.fetchall() if cur.description else None
def call(path,method='GET',body=None,token=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(BASE+path,data=data,method=method,headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read() or b'{}')
def login(email):
    s,d=call('/auth/login','POST',{'email':email,'password':'ColdChain!17'});assert s==200,(s,d);return d['token']
def get_batch(token,batch):
    s,d=call('/batches',token=token);return next(x for x in d if x['id']==batch)
def wait_status(token,batch,expect,limit=40):
    row=None
    for _ in range(limit*4):
        row=get_batch(token,batch)
        if row['status']==expect:return row
        time.sleep(0.25)
    assert row and row['status']==expect,(row,batch)
    return row
SQL="SELECT customer, SUM(amount) AS total FROM invoices WHERE temperature <= 8 GROUP BY customer HAVING SUM(amount) > 100 ORDER BY customer"
def accept(token,name):
    s,d=call('/batches','POST',{'name':name,'sample_id':1,'candidate_sql':SQL},token);assert s==202,(s,d);return d
def accept_pair():
    pairs=[(c.strip(),str(d)) for c,d in sql("SELECT DISTINCT currency, transport_date FROM invoices WHERE currency<>'CNY' ORDER BY 1,2")]
    return pairs[len(pairs)//2]
def stage_accept():
    op=login('operator@chenggang.test');tag=str(int(time.time()));cur,day=accept_pair()
    complete=accept(op,'fx-complete-'+tag);assert complete['status']=='queued',complete
    sql(f"DELETE FROM fx_rates WHERE currency='{cur}' AND rate_date=DATE '{day}'")
    held=accept(op,'fx-held-'+tag);assert held['status']=='held' and held['fx_missing']==[{'currency':cur,'date':day}],held
    held2=accept(op,'fx-held2-'+tag);assert held2['status']=='held',held2
    json.dump({'tag':tag,'pair':[cur,day],'complete':complete['id'],'held':held['id'],'held2':held2['id'],'locked':[x for x in complete['fx_snapshot'] if (x['currency'],x['date'])==(cur,day)][0]['rate']},open(STATE,'w'))
    print('accepted',complete['id'],'held',held['id'],held2['id'],'pair',cur,day)
def stage_verify():
    st=json.load(open(STATE));op=login('operator@chenggang.test');viewer=login('viewer@chenggang.test');cur,day=st['pair']
    # a rate deleted from the mother table must not disturb a batch that locked it at acceptance
    done=wait_status(op,st['complete'],'passed')
    assert (cur,day) in [(x['currency'],x['date']) for x in done['fx_snapshot']]
    assert get_batch(op,st['held'])['status']=='held'
    ev=call('/evidence/'+str(st['complete']),token=op)[1]['result']
    assert ev['original']['rows']==ev['candidate']['rows'] and ev['equivalent']
    print('lock survives deletion:',st['locked'])
    # concurrent backfill: exactly one first value lands, both parked batches resume on it
    values=['7.1533','7.9999','6.0001']
    def post(v):return call('/fx/rates','POST',{'currency':cur,'rate_date':day,'rate':v},op)
    with ThreadPoolExecutor(len(values)) as pool:responses=list(pool.map(post,values))
    assert all(s in (200,201) for s,_ in responses),responses
    assert sum(1 for s,_ in responses if s==201)==1,responses
    created=[d for d in (r[1] for r in responses) if d['created']]
    assert len(created)==1,created
    winner=created[0]['rate']['rate']
    stored=sql(f"SELECT rate FROM fx_rates WHERE currency='{cur}' AND rate_date=DATE '{day}'")[0][0]
    assert Decimal(stored)==Decimal(winner),(stored,winner)
    assert sorted(created[0]['resumed_batch_ids'])==sorted([st['held'],st['held2']]),created[0]
    print('first stored value wins:',winner)
    for ident in (st['held'],st['held2']):
        row=wait_status(op,ident,'passed')
        locked=[x['rate'] for x in row['fx_snapshot'] if (x['currency'],x['date'])==(cur,day)]
        assert locked==[format(Decimal(winner),'f')],(locked,winner)
        assert row['fx_missing']==[],row
    # a later correction writes the mother table only; locked batches and their evidence stay put
    before=call('/evidence/'+str(st['held']),token=op)[1]['result']['original_checksum']
    corr=call('/fx/rates','PUT',{'currency':cur,'rate_date':day,'rate':'8.4321'},op)[1]
    assert corr['updated'] and Decimal(corr['rate']['rate'])==Decimal('8.4321') and corr['resumed_batch_ids']==[],corr
    assert Decimal(sql(f"SELECT rate FROM fx_rates WHERE currency='{cur}' AND rate_date=DATE '{day}'")[0][0])==Decimal('8.4321')
    assert call('/evidence/'+str(st['held']),token=op)[1]['result']['original_checksum']==before
    fresh=accept(op,'fx-fresh-'+st['tag'])
    assert any(x['currency']==cur and x['date']==day and Decimal(x['rate'])==Decimal('8.4321') for x in fresh['fx_snapshot']),fresh['fx_snapshot']
    # both sides fold with one snapshot and agree with a hand-computed RMB total
    expected={}
    for customer,value in sql("""SELECT i.customer, SUM(CASE WHEN i.currency='CNY' THEN i.amount ELSE ROUND(i.amount*f.rate,2) END)
                                 FROM invoices i LEFT JOIN fx_rates f ON f.currency=i.currency AND f.rate_date=i.transport_date
                                 WHERE i.temperature<=8 GROUP BY i.customer"""):
        expected[customer]=Decimal(value)
    expected=[[c,str(v)] for c,v in sorted(expected.items())]
    fresh=wait_status(op,fresh['id'],'passed')
    ev=call('/evidence/'+str(fresh['id']),token=op)[1]['result']
    assert [[c,str(v)] for c,v in ev['original']['rows']]==expected,(ev['original']['rows'],expected)
    assert ev['original']['rows']==ev['candidate']['rows'] and ev['original_checksum']==ev['candidate_checksum']
    # drill: a deliberately different candidate stays different, not an error
    s,d=call('/batches','POST',{'name':'fx-diff-'+st['tag'],'sample_id':1,'candidate_sql':"SELECT customer, SUM(amount) AS total FROM invoices WHERE temperature > 8 GROUP BY customer ORDER BY customer"},op)
    diff=wait_status(op,d['id'],'different');print('difference stays a difference:',diff['id'])
    # viewer may read rates, never write them
    assert call('/fx/rates',token=viewer)[0]==200
    assert call('/fx/rates','POST',{'currency':'GBP','rate_date':'2026-11-11','rate':'9.1'},viewer)[0]==403
    assert call('/fx/rates','PUT',{'currency':'GBP','rate_date':'2026-11-11','rate':'9.2'},viewer)[0]==403
    assert call('/fx/rates','POST',{'currency':'gbp','rate_date':'2026-11-11','rate':'9.1'},op)[0]==201
    assert call('/fx/rates','POST',{'currency':'GBP','rate_date':'2026-11-11','rate':'9.5'},op)[0]==200
    assert call('/fx/rates','POST',{'currency':'GBP','rate_date':'2026-11-11','rate':'0'},op)[0]==422
    print(json.dumps({'locked_survives_deletion':True,'first_value_wins':winner,'resumed':[st['held'],st['held2']],'correction_isolated':True,'rmb_matches_hand_calc':True,'different_detected':True,'viewer_readonly':True},ensure_ascii=False,indent=2))
if __name__=='__main__':
    {'accept':stage_accept,'verify':stage_verify}[sys.argv[1]]()
