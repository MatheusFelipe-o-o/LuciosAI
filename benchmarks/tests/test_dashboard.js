// Teste de lógica DOM em ambiente controlado; não substitui inspeção visual.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('dashboard.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements=new Map();
let lineCount=0;
class Element{
  constructor(id=''){this.id=id;this.children=[];this.style={};this.dataset={};this.events={};this.value='';this.hidden=false;this.checked=false;this.disabled=false;this._text='';this.classes=new Set();this.classList={toggle:(name,on)=>{if(on)this.classes.add(name);else this.classes.delete(name);}};}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent??String(x)).join('');}
  append(...nodes){this.children.push(...nodes);if(['model','complexModel','resultScenario'].includes(this.id)&&this.children.length===nodes.length)this.value=String(nodes[0]?.value??'');}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(name,value){this[name]=value;}
  getBoundingClientRect(){return {width:800,height:205};}
  getContext(){return new Proxy({}, {get:(target,name)=>name==='lineTo'?(...args)=>{assert(args.every(Number.isFinite));lineCount++;}:()=>{},set:()=>true});}
  querySelectorAll(selector){if(this.id==='scenarios')return checks.filter(c=>selector==='input'||c.checked);if(this.id==='legend')return legends;if(this.id==='benchmarkForm')return [...elements.values(),...checks,...presets].filter(c=>c.id!=='cancelBtn');return [];}
  showModal(){this.open=true;} close(){this.open=false;}
}
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element(match[1]));
for(const match of html.matchAll(/<input[^>]*id="([^"]+)"[^>]*value="([^"]+)"/g))elements.get(match[1]).value=match[2];
const checks=['limpeza','conversa','memoria_busca','memoria_ambigua','complexa','encerramento'].map(value=>Object.assign(new Element(),{value,checked:true}));
const presets=['rapido','completo'].map(p=>{const e=new Element();e.dataset.preset=p;return e;});
const legends=['cpu','gpu','ram','vram'].map(k=>{const e=new Element();e.dataset.series=k;return e;});
const requests=[];
const initial={fase:'ocioso',ativo:false,atual:null,etapas:{},amostras:[],concluidas:0,total:0,duracao_s:0,resultado:null,hardware:null,historico_hardware:[]};
const context={console,Node:Element,Option:function(label,value){const e=new Element();e.textContent=label;e.value=value;return e;},
  document:{getElementById:id=>{assert(elements.has(id),id);return elements.get(id);},querySelector:()=>({content:'__TOKEN__'}),querySelectorAll:()=>presets,createElement:()=>new Element(),createTextNode:text=>{const e=new Element();e.textContent=text;return e;}},
  window:{devicePixelRatio:1,addEventListener:()=>{}},setTimeout:()=>0,
  fetch:async(path,options)=>{requests.push({path,options});return {ok:true,json:async()=>path==='/api/state'?initial:path==='/api/models'?{modelos:['llama3.2:latest'],disponivel:true}:{ok:true}};}};
vm.createContext(context);vm.runInContext(script,context);
const el=id=>elements.get(id);
async function main(){
  await new Promise(setImmediate);
  const hw={instante:Date.now()/1000,cpu_percent:23,ram_percent:50,ram_usada_mb:8192,ram_total_mb:16384,cpu_status:'disponível',gpus:[{nome:'GPU de teste',uso_percent:45,vram_percent:40,vram_usada_mb:2457,vram_total_mb:6144,temperatura_c:50,potencia_w:30}]};
  context.TEST_STATE={...initial,fase:'executando',ativo:true,concluidas:1,total:3,duracao_s:2,atual:{modelo:'modelo teste',cenario:'conversa',fase:'medicao',numero:2},hardware:hw,historico_hardware:[{...hw,instante:hw.instante-1},hw],etapas:{a:{etapa:'execucao/inferencia_resposta',status:'executando',duracao_s:1.25}}};
  vm.runInContext('render(TEST_STATE)',context);
  assert.equal(el('startBtn').disabled,true);assert.equal(el('cancelBtn').hidden,false);
  assert.match(el('gpuValue').textContent,/45/);assert.match(el('stageRows').textContent,/Inferência da resposta/);assert.match(el('stageRows').textContent,/1,250 s/);assert(lineCount>0);
  const stats={media_s:1,media:30,pico:50,n:3};
  const result={pontuacao:{nota:780,velocidade:.8,estabilidade:.9,confiabilidade:1,perfil:'teste',provisorio:false,motivo:'Índice técnico.'},modo:'ollama_real',hardware:{cpu_percent:stats,ram_usada_mb:{pico:8192},gpus:[]},resumos:[{cenario:'conversa',sucessos:3,total:{n:3,media_s:1},etapas:[{etapa:'execucao',inclusivo:stats,exclusivo:stats}]}]};
  context.TEST_STATE={...context.TEST_STATE,fase:'concluido',ativo:false,resultado:result,concluidas:3,amostras:[{fase:'medicao',estado:'concluido'}]};
  vm.runInContext('render(TEST_STATE)',context);
  assert.equal(el('scoreValue').textContent,'780');assert.equal(el('resultView').hidden,false);assert(el('resultRows').children.length>0);assert.equal(el('startBtn').disabled,false);
  context.TEST_STATE.resultado={...result,modo:'simulado',pontuacao:{nota:null,motivo:'Simulação'}};
  vm.runInContext('render(TEST_STATE)',context);
  assert.equal(el('scoreValue').textContent,'—');assert.match(el('scoreCaption').textContent,/Simulação/);
  el('simulated').checked=true;el('repetitions').value='1';el('warmups').value='0';el('model').value='llama3.2:latest';checks.forEach(c=>c.checked=c.value==='conversa');
  await el('benchmarkForm').events.submit({preventDefault(){}});
  const req=requests.find(r=>r.path==='/api/start');assert(req);assert.equal(req.options.headers['X-Lucios-Token'],'__TOKEN__');assert.deepEqual(JSON.parse(req.options.body).cenarios,['conversa']);
  await el('helpBtn').events.click();assert.equal(el('scoreDialog').open,true);
  console.log('Dashboard DOM logic: passed (not visual browser QA)');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
