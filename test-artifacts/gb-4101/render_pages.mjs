// Render the SPA pages in jsdom against the live test backend.
// Frontend is bundled to IIFE (jsdom has no ES-module scripts) and fetch is shimmed.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {JSDOM} from 'jsdom';
const ROOT=process.env.FRONTEND_ROOT||'/workspace/frontend',API=process.env.BASE||'http://127.0.0.1:19241',PORT=18241;
const BUNDLE=process.env.BUNDLE||new URL('./app.bundle.js',import.meta.url).pathname;
const bundle=fs.readFileSync(BUNDLE,'utf8');
const types={'.js':'text/javascript','.css':'text/css','.html':'text/html'};
const server=http.createServer((req,res)=>{
  if(req.url==='/app.js'){res.writeHead(200,{'Content-Type':'text/javascript'});res.end(bundle);return}
  if(req.url==='/index.html'||req.url==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end(fs.readFileSync(path.join(ROOT,'index.html'),'utf8').replace('type="module" src="/src/app.js"','src="/app.js"'));return}
  const file=path.join(ROOT,req.url.split('?')[0]);
  if(fs.existsSync(file)&&fs.statSync(file).isFile()){res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream'});res.end(fs.readFileSync(file));return}
  res.writeHead(404);res.end('');
});
await new Promise(r=>server.listen(PORT,r));
const login=await (await fetch(API+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:'operator@chenggang.test',password:'ColdChain!17'})})).json();
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function open(hash,role){
  return JSDOM.fromURL(`http://127.0.0.1:${PORT}/index.html#${hash}`,{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(window){
    window.localStorage.setItem('qr-session',JSON.stringify({...login,role}));
    window.fetch=(url,options={})=>{
      const headers={...(options.headers||{})};
      const session=JSON.parse(window.localStorage.getItem('qr-session')||'null');
      if(session&&!headers.Authorization)headers.Authorization='Bearer '+session.token;
      return fetch(API+String(url).replace(/^\/api/,''),{...options,headers});
    };
    window.URL.createObjectURL=()=>'blob:x';window.URL.revokeObjectURL=()=>{};
    window.addEventListener('error',e=>{window.__err=String(e.error&&e.error.stack||e.message)});
  }});
}
async function inspect(hash,label,role='operator'){
  const dom=await open(hash,role);await wait(2200);
  const d=dom.window.document;
  console.log(`[${label}] title=${d.querySelector('#page h1')?.textContent} rows=${d.querySelectorAll('tbody tr').length} forms=${[...d.querySelectorAll('form')].map(f=>f.id).join(',')} err=${dom.window.__err?'YES':'no'}`);
  return dom;
}
const history=await inspect('history','history');
const doc=history.window.document;
if(history.window.__err)console.log(history.window.__err.slice(0,600));
console.log('held badges:',doc.querySelectorAll('.badge.held').length);
const heldRow=[...doc.querySelectorAll('tbody tr')].find(r=>r.querySelector('.badge.held'));
console.log('held fx cell:',heldRow?.children[4]?.textContent.replace(/\s+/g,' ').trim());
console.log('held evidence hint:',heldRow?.children[5]?.textContent.trim());
const lockedRow=[...doc.querySelectorAll('tbody tr')].find(r=>r.querySelector('details.fx'));
const details=[...lockedRow?.querySelectorAll('details.fx summary')||[]].map(s=>s.textContent);
console.log('locked summaries:',details.join(' | '));
console.log('details closed by default:',[...lockedRow.querySelectorAll('details.fx')].every(d=>!d.open));
const set=(f,v)=>{doc.querySelector('#fx-form [name='+f+']').value=v};
if(process.env.MUTATE&&doc.querySelector('#fx-form')){
  set('currency','EUR');set('rate_date','2026-11-01');set('rate','7.85');
  doc.querySelector('#fx-correct').click();
  await wait(1600);
  console.log('correct notice:',doc.querySelector('#notice')?.textContent);
  const d2=doc.querySelector('#page');
  set('currency','usd');set('rate_date','2026-11-13');set('rate','7.15');
  doc.querySelector('#fx-form').dispatchEvent(new history.window.Event('submit',{bubbles:true,cancelable:true}));
  await wait(1600);
  console.log('backfill notice:',doc.querySelector('#notice')?.textContent);
}
const evidence=await inspect('evidence','evidence');
console.log('evidence fx line:',[...evidence.window.document.querySelectorAll('p.helper')].map(p=>p.textContent).find(t=>t.includes('锁定'))||'(none)');
const viewer=await inspect('history','history-viewer','viewer');
console.log('viewer has fx form:',!!viewer.window.document.querySelector('#fx-form'));
await inspect('review','review');await inspect('samples','samples');
server.close();process.exit(0);
