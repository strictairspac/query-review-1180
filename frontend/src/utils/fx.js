import{esc}from'./html.js';
const fmt=x=>String(Number(x)).replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');
export function groupRates(list){
  const groups={};
  for(const x of list||[]){const key=x.currency;(groups[key]=groups[key]||[]).push(x)}
  return Object.entries(groups).map(([currency,items])=>{
    const rates=items.map(x=>Number(x.rate));const min=Math.min(...rates),max=Math.max(...rates);
    return {currency,days:items.length,min,max,same:min===max,items:items.slice().sort((a,b)=>String(a.date||a.rate_date).localeCompare(String(b.date||b.rate_date)))};
  });
}
export const rateRange=g=>g.same?fmt(g.min):fmt(g.min)+'–'+fmt(g.max);
export function lockedRates(list){
  const groups=groupRates(list);
  if(!groups.length)return '<span class="muted">全部人民币</span>';
  return groups.map(g=>`<details class="fx"><summary>${esc(g.currency)} · ${g.days} 天 · ${esc(rateRange(g))}</summary><div class="fx-list">${g.items.map(x=>`<span class="mono">${esc(x.date||x.rate_date)} · ${esc(fmt(x.rate))}</span>`).join('')}</div></details>`).join('');
}
export function missingRates(list){
  if(!list||!list.length)return '<span class="muted">无缺价</span>';
  return groupRates(list.map(x=>({currency:x.currency,date:x.date,rate:0}))).map(g=>`<div class="fx-missing"><span class="mono">${esc(g.currency)}</span> 缺 ${g.items.map(x=>esc(x.date)).join('、')} 的汇率</div>`).join('');
}
export function rateLine(list){
  const groups=groupRates(list);
  if(!groups.length)return '';
  return groups.map(g=>`${g.currency} ${g.days} 天 ${rateRange(g)}（${g.items.map(x=>`${x.date||x.rate_date} · ${fmt(x.rate)}`).join('；')}）`).join('；');
}
