import{batches}from'../stores/batch.js';import{header}from'../components/common/header.js';import{table}from'../components/common/table.js';import{badge}from'../components/common/badge.js';import{esc}from'../utils/html.js';import{lockedRates,missingRates}from'../utils/fx.js';import{notify,submit}from'../hooks/feedback.js';import{recordRate,correctRate}from'../api/fx.js';import{session}from'../stores/session.js';
function fxCell(x){
  const missing=x.fx_missing||[];
  const locked=x.fx_snapshot||[];
  if(!missing.length&&!locked.length)return '<span class="badge">已锁定</span> <span class="muted">全部人民币</span>';
  return (missing.length?'<span class="badge held">缺价</span> ':'<span class="badge">已锁定</span> ')+
    (missing.length?missingRates(missing):'')+
    (locked.length?lockedRates(locked):'');
}
export async function historyPage(el){
  const rows=await batches.load();const write=session.get().role!=='viewer';
  el.innerHTML=header('03','运行记录按批次留痕','接单时锁定汇率，外币账单按运输日折成人民币后比对；缺价批次挂起，补价入库后自动续跑，更正汇率只影响新批次。')+
  `<div class="panel"><div class="actions" style="margin-top:0;margin-bottom:20px"><button id="refresh">刷新队列</button><a href="#review">新建复核 →</a><span class="muted">${rows.length} 个批次</span></div>${table(['编号 / 批次','基准样本','提交时间','运行状态','折算汇率','执行证据'],rows.map(x=>['<span class="mono">#'+x.id+'</span><br>'+esc(x.name),'#'+x.sample_id,esc(x.created_at),badge(x.status),fxCell(x),['passed','different','failed'].includes(x.status)?`<a href="#evidence/${x.id}">打开证据 →</a>`:x.status==='held'?'补录汇率后自动续跑':'后台处理中，请刷新']))}</div>`+
  (write?`<section class="panel"><h2>补录 / 更正折算汇率</h2><p class="helper">补录按首个入库值固定；同币种同日再提交更正时，已锁定批次不改，只影响之后接单的批次。挂起的批次在汇率补齐后自动续跑。</p><form id="fx-form"><div class="fxform split"><div><label for="fx-currency">币种（三位字母）</label><input id="fx-currency" name="currency" maxlength="3" placeholder="USD" required></div><div><label for="fx-date">运输日</label><input id="fx-date" name="rate_date" type="date" value="2026-11-01" required></div></div><label for="fx-rate">汇率（1 外币折人民币）</label><input id="fx-rate" name="rate" inputmode="decimal" placeholder="7.1" required><div class="actions"><button class="primary" type="submit">补录缺失汇率</button><button type="button" id="fx-correct">更正已有汇率</button><a href="#history">取消</a></div></form></section>`:'');
  el.querySelector('#refresh').onclick=()=>historyPage(el);
  const form=el.querySelector('#fx-form');if(!form)return;
  const fields=form.elements;
  const send=async action=>{
    const data={currency:String(fields.currency.value||'').trim().toUpperCase(),rate_date:fields.rate_date.value,rate:fields.rate.value};
    const result=action==='correct'?await correctRate(data):await recordRate(data);
    const resumed=result.resumed_batch_ids||[];
    const verb=result.created?'汇率已入库':result.updated?'汇率已更正':'该汇率已存在，保留首个入库值';
    notify(verb+(resumed.length?`，续跑批次 ${resumed.join('、')}`:''));
    await historyPage(el);
  };
  form.onsubmit=e=>{e.preventDefault();submit(form,()=>send('record'))};
  el.querySelector('#fx-correct').onclick=()=>submit(form,()=>send('correct'));
}
