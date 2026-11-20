"""Strict read-only bounded SQL execution against a single seeded business table."""
import json,hashlib,time
from collections import Counter
import sqlglot
from sqlglot import exp
from sqlalchemy import text
from ..config.database import engine
ALLOWED_FUNCTIONS={'SUM','COUNT','AVG','MIN','MAX','ROUND','COALESCE','CAST'}
ALLOWED_COLUMNS={'customer','route','amount','temperature','invoice_id','status'}
CTE_NAME='__invoices_cny'
def validate_sql(sql):
    try: trees=sqlglot.parse(sql,read='postgres')
    except Exception as exc: raise ValueError('SQL 无法解析：'+str(exc)[:180])
    if len(trees)!=1 or not isinstance(trees[0],exp.Select): raise ValueError('只允许单条 SELECT')
    tree=trees[0]
    if tree.args.get('into') or tree.args.get('locks') or tree.find(exp.With): raise ValueError('不允许 INTO、锁或 CTE')
    tables=list(tree.find_all(exp.Table))
    if not tables or any(t.name!='invoices' or t.db or t.catalog for t in tables): raise ValueError('只允许访问 invoices 表')
    for col in tree.find_all(exp.Column):
        if col.name in ('currency','transport_date'): raise ValueError('currency/transport_date 只用于折算，不在复核口径内')
        if col.name not in ALLOWED_COLUMNS and col.name!='*': raise ValueError('未知业务字段：'+col.name)
    for f in tree.find_all(exp.Func):
        if f.sql_name() not in ALLOWED_FUNCTIONS: raise ValueError('不允许函数：'+f.sql_name())
    if len(list(tree.walk()))>250: raise ValueError('SQL 结构过大')
    return tree.sql(dialect='postgres')
def _cny_cte(snapshot):
    """One RMB view of invoices: foreign bills multiply the locked transport-day rate.

    A foreign row the snapshot does not price raises a typed error instead of
    folding NULL or treating the amount as RMB.
    """
    col=lambda name:exp.column(name,table='i')
    unpriced=exp.cast(exp.Concat(expressions=[exp.Literal.string('缺折算汇率: '),col('currency')]),'NUMERIC')
    rate=exp.column('rate',table='r') if snapshot else exp.Null()
    amount=exp.Case(ifs=[exp.If(this=exp.EQ(this=col('currency'),expression=exp.Literal.string('CNY')),true=col('amount')),
                         exp.If(this=exp.Is(this=rate,expression=exp.Null()),true=unpriced)],
                    default=exp.func('ROUND',exp.Mul(this=col('amount'),expression=rate),exp.Literal.number(2)))
    query=exp.Select(expressions=[col('invoice_id'),col('customer'),col('route'),amount.as_('amount'),col('temperature'),col('status')]).from_(exp.alias_(exp.table_('invoices'),'i'))
    if snapshot:
        values=exp.Values(expressions=[exp.Tuple(expressions=[exp.Literal.string(x['currency']),exp.cast(exp.Literal.string(x['date']),'DATE'),exp.cast(exp.Literal.string(format(x['rate'])),exp.DataType.build('DECIMAL(18,6)'))]) for x in snapshot],alias=exp.TableAlias(this=exp.to_identifier('r'),columns=[exp.to_identifier('currency'),exp.to_identifier('rate_date'),exp.to_identifier('rate')]))
        query=query.join(exp.Join(this=values,kind='LEFT',on=exp.And(this=exp.EQ(this=exp.column('currency',table='r'),expression=col('currency')),expression=exp.EQ(this=exp.column('rate_date',table='r'),expression=col('transport_date')))))
    return exp.CTE(this=query,alias=exp.TableAlias(this=exp.to_identifier(CTE_NAME)))
def rewrite_rmb(sql,snapshot):
    """Run the reviewed SQL over a CTE that folds every bill into RMB at locked rates."""
    tree=sqlglot.parse_one(sql,read='postgres')
    for table in list(tree.find_all(exp.Table)):
        # Keep the original qualifier so `invoices.customer` style references still resolve.
        replacement=exp.Table(this=exp.to_identifier(CTE_NAME),alias=exp.TableAlias(this=exp.to_identifier(table.alias or 'invoices')))
        table.replace(replacement)
    tree.set('with',exp.With(expressions=[_cny_cte(snapshot)]))
    return tree.sql(dialect='postgres')
def execute_query(sql,snapshot):
    sql=rewrite_rmb(validate_sql(sql),snapshot)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text("SET LOCAL statement_timeout='2500ms'"))
            conn.execute(text('SET LOCAL ROLE query_reader'))
            try:
                plan=conn.execute(text('EXPLAIN (ANALYZE, FORMAT JSON, BUFFERS) '+sql)).scalar()
                started=time.perf_counter()
                cursor=conn.execute(text(sql)); columns=list(cursor.keys()); rows=cursor.fetchmany(1001)
            except Exception as exc:
                if '缺折算汇率' in str(exc): raise ValueError('账单存在未锁定的外币运输日，请先补录汇率再重跑该批次') from exc
                raise
            if len(rows)>1000: raise ValueError('结果超过 1000 行，请聚合或 LIMIT')
            rows=[[str(v) if v is not None else None for v in row] for row in rows]
            return {'columns':columns,'rows':rows,'row_count':len(rows),'elapsed_ms':round((time.perf_counter()-started)*1000,3),'plan':plan}
def compare(original,candidate,snapshot):
    left=execute_query(original,snapshot);right=execute_query(candidate,snapshot)
    canon=lambda data:Counter(json.dumps(row,ensure_ascii=False) for row in data['rows'])
    a,b=canon(left),canon(right)
    equivalent=len(left['columns'])==len(right['columns']) and a==b
    digest=lambda x:hashlib.sha256(json.dumps(sorted(canon(x).items()),ensure_ascii=False).encode()).hexdigest()
    return {'equivalent':equivalent,'comparison':'忽略行顺序、保留重复行；按输出列位置比较，数字按数据库文本表示','fx':{'snapshot':snapshot},'original':left,'candidate':right,'original_checksum':digest(left),'candidate_checksum':digest(right),'missing_rows':list((a-b).elements())[:10],'extra_rows':list((b-a).elements())[:10],'note':'执行时间受缓存与机器负载影响；不据一次耗时断言优化收益'}
