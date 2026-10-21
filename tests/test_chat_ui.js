// DOM controlado para lógica; não substitui inspeção visual em navegador.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('web/index.html','utf8');
const elements = new Map();
class Element {
  constructor(tag='div') { this.tagName=tag;this.children=[];this.events={};this.style={};this.value='';this.dataset={};this.classes=new Set();this.scrollHeight=100;this.classList={toggle:(key,on)=>{if(on)this.classes.add(key);else this.classes.delete(key);}}; }
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return (this._text||'')+this.children.map(e=>e.textContent).join('');}
  append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
  appendChild(node){this.append(node);return node;}
  replaceChildren(...nodes){this._text='';this.children=[];this.append(...nodes);}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(e=>e!==this);}
  setAttribute(key,value){this[key]=value;}
  addEventListener(event,fn){this.events[event]=fn;}
  focus(){this.focused=true;}
}
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element());
const el=id=>elements.get(id);
const requests=[];
let entries=[],failChat=false,mobile=false,opened=0,lastTarget,confirmDelete=false,failDelete=false,confirmation='';
const document={body:new Element(),getElementById:el,querySelector:()=>({content:'secret-token'}),querySelectorAll:()=>[],createElementNS:(_,tag)=>new Element(tag),createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;},addEventListener:()=>{}};
const context={console,document,setTimeout:()=>0,clearTimeout:()=>{},window:{confirm:text=>{confirmation=text;return confirmDelete;},matchMedia:()=>({matches:mobile,addEventListener:()=>{}}),open:()=>{opened++;lastTarget={location:{replace:url=>{lastTarget.url=url;}},close:()=>{}};return lastTarget;}},
  fetch:async(path,options)=>{
    requests.push({path,options});
    const body=options?.body?JSON.parse(options.body):{};
    if(path==='/api/conversations')return {ok:true,json:async()=>({conversations:entries,model:'local-test'})};
    if(path==='/api/new'){const item={id:'a'.repeat(32),title:'Nova conversa',updated:new Date().toISOString()};entries=[item];return {ok:true,json:async()=>item};}
    if(path==='/api/chat'){
      if(failChat)return {ok:false,json:async()=>({error:'Modelo indisponível'})};
      entries[0].title=body.message;return {ok:true,json:async()=>({reply:'**Resposta**\n\n- Item'})};
    }
    if(path.startsWith('/api/conversation?'))return {ok:true,json:async()=>({...entries[0],messages:[{role:'user',content:'Anterior'},{role:'assistant',content:'Olá'}]})};
    if(path==='/api/delete'){
      if(failDelete)return {ok:false,json:async()=>({error:'Falha ao excluir'})};
      entries=entries.filter(item=>item.id!==body.conversation_id);
      return {ok:true,json:async()=>({ok:true})};
    }
    if(path==='/api/lab')return {ok:true,json:async()=>({url:'http://127.0.0.1:12345'})};
    return {ok:true,json:async()=>({reply:'Salvo'})};
  }};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/markdown.js','utf8'),context);
vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
const settle=()=>new Promise(setImmediate);
async function main(){
  await settle();
  await vm.runInContext('refreshRecent()',context);
  assert.equal(el('sendBtn').disabled,false);
  el('prompt').value='<script>alert(1)</script>';
  await el('chatForm').events.submit({preventDefault(){}});
  assert.equal(el('messages').children.length,2);
  assert.equal(el('welcome').hidden,true);
  assert.equal(el('chatTitle').textContent,'<script>alert(1)</script>',el('toast').textContent);
  assert.equal(el('messages').children[0].children[1].textContent,'<script>alert(1)</script>');
  const request=requests.find(r=>r.path==='/api/chat');
  assert.equal(request.options.headers['X-Lucios-Token'],'secret-token');
  assert.equal(JSON.parse(request.options.body).conversation_id,'a'.repeat(32));
  assert.equal(el('messages').children[1].children[1].children[0].children[1].tagName,'strong');
  el('search').value='inexistente';el('search').events.input();
  assert.match(el('recentList').textContent,/Nenhuma conversa/);
  el('search').value='';el('search').events.input();
  el('newBtn').events.click();assert.equal(el('welcome').hidden,false);assert.equal(el('messages').children.length,0);
  await el('recentList').children.find(e=>e.className==='recent-row').children[0].events.click();
  await settle();assert.equal(el('messages').children.length,2);
  failChat=true;el('prompt').value='Tente novamente';
  await el('chatForm').events.submit({preventDefault(){}});
  assert.equal(el('messages').children.length,2);assert.equal(el('prompt').value,'Tente novamente');
  assert.match(el('toast').textContent,/indisponível/);
  await el('labBtn').events.click();assert.equal(opened,1);assert.equal(lastTarget.url,'http://127.0.0.1:12345');
  mobile=true;el('menuBtn').events.click();assert.equal(el('scrim').hidden,false);assert.equal(el('workspace').inert,true);
  el('closeSidebar').events.click();assert.equal(el('scrim').hidden,true);assert.equal(el('sidebar').inert,true);
  const container=new Element();context.container=container;
  vm.runInContext('renderMarkdown("```html\\n<img src=x onerror=alert(1)>\\n```", container)',context);
  assert.equal(container.children[0].tagName,'pre');assert.equal(container.children[0].children[0].children.length,0);
  assert.match(container.textContent,/<img/);
  const deleteButton=()=>el('recentList').children.find(e=>e.className==='recent-row').children[1];
  let before=requests.filter(r=>r.path==='/api/delete').length;
  await deleteButton().events.click();
  assert(confirmation.includes(entries[0].title));
  assert.equal(requests.filter(r=>r.path==='/api/delete').length,before);
  assert.equal(el('messages').children.length,2);
  confirmDelete=true;failDelete=true;
  await deleteButton().events.click();
  assert.equal(el('messages').children.length,2);assert.equal(entries.length,1);
  assert.match(el('toast').textContent,/Falha ao excluir/);
  failDelete=false;
  entries.unshift({id:'b'.repeat(32),title:'Outro chat',updated:new Date().toISOString()});
  await vm.runInContext('refreshRecent()',context);
  await deleteButton().events.click();
  assert.equal(el('messages').children.length,2);assert.equal(entries.length,1);
  await deleteButton().events.click();
  assert.equal(entries.length,0);assert.equal(el('messages').children.length,0);
  assert.equal(el('welcome').hidden,false);assert.equal(el('recentCount').textContent,'0');
  console.log('Chat UI: flows, recent search, safe Markdown, errors, lab and mobile menu passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
