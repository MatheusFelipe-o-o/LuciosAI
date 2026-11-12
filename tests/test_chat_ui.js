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
  querySelectorAll(selector){
    const found=[];
    const visit=node=>{for(const child of node.children){
      if(selector==='[data-turn-action]'&&child['data-turn-action']!==undefined)found.push(child);
      visit(child);
    }};
    visit(this);return found;
  }
}
for(const match of html.matchAll(/id="([^"]+)"/g))elements.set(match[1],new Element());
const el=id=>elements.get(id);
el('modelMenu').hidden=true;
const requests=[];
let entries=[],failChat=false,mobile=false,opened=0,lastTarget,confirmDelete=false,failDelete=false,confirmation='';
let conversation=null, answerNumber=0;
const document={body:new Element(),getElementById:el,querySelector:()=>({content:'secret-token'}),querySelectorAll:()=>[],createElementNS:(_,tag)=>new Element(tag),createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;},addEventListener:()=>{}};
const context={console,document,TextDecoder,setTimeout:()=>0,clearTimeout:()=>{},window:{confirm:text=>{confirmation=text;return confirmDelete;},matchMedia:()=>({matches:mobile,addEventListener:()=>{}}),open:()=>{opened++;lastTarget={location:{replace:url=>{lastTarget.url=url;}},close:()=>{}};return lastTarget;}},
  fetch:async(path,options)=>{
    requests.push({path,options});
    const body=options?.body?JSON.parse(options.body):{};
    if(path==='/api/conversations')return {ok:true,json:async()=>({conversations:entries,model:'local-test'})};
    if(path==='/api/models')return {ok:true,json:async()=>({models:['small:latest','large:latest'],available:true})};
    if(path==='/api/new'){
      const item={id:'a'.repeat(32),title:'Nova conversa',updated:new Date().toISOString()};
      entries=[item];conversation={...item,model:body.model||'auto',messages:[],editable:false,editable_turn:null};
      return {ok:true,json:async()=>item};
    }
    if(path==='/api/model'){conversation.model=body.model;return {ok:true,json:async()=>({model:body.model})};}
    if(path==='/api/files/prepare'){
      if(body.message.includes('currículo'))return {ok:true,json:async()=>({selection:{
        id:'choice-one',interpretation:'Encontrar o currículo mais atual',request:body.message,
        query:'currículo',total:2,candidates:[
          {path:'CV_2026.pdf',extension:'.pdf',modified:'2026-01-01T10:00',
           name_date:'2026-01-01',reason:'nome relacionado a currículo'},
          {path:'Currículo_2024.docx',extension:'.docx',modified:'2025-01-01T10:00',
           name_date:'2024-01-01',reason:'nome relacionado a currículo'}]
      }})};
      return {ok:true,json:async()=>({proposal:{id:'proposal-one',interpretation:'Criar uma nota de teste',
        operation:'create',source:'nota.md',target:null,root:'Documentos',preview:'create: nota.md',
        request:body.message}})};
    }
    if(path==='/api/files/select')return {ok:true,json:async()=>({proposal:{
      id:'proposal-two',interpretation:'Ler o currículo escolhido',operation:'read',
      source:'CV_2026.pdf',target:null,root:'Documentos',preview:'read: CV_2026.pdf'}})};
    if(path==='/api/files/decide'){
      conversation.messages.push({role:'user',content:'Crie uma nota'},
        {role:'assistant',content:body.confirm?'Ação concluída':'Ação negada'});
      return {ok:true,json:async()=>({result:'Ação concluída',conversation})};
    }
    if(path==='/api/chat-stream'){
      if(failChat)return {ok:false,json:async()=>({error:'Modelo indisponível'})};
      const reply='**Resposta**\n\n- Item';
      if(!conversation.messages.length)entries[0].title=body.message;
      conversation.title=entries[0].title;
      conversation.messages.push({role:'user',content:body.message},
        {role:'assistant',content:reply,alternatives:[{content:reply,model:conversation.model}],selected:0});
      conversation.editable=true;conversation.editable_turn=conversation.messages.length-2;
      const lines=[{type:'delta',text:'**Res'},{type:'delta',text:'posta**\n\n- Item'},
        {type:'done',conversation}].map(x=>JSON.stringify(x)+'\n');
      let next=0;
      return {ok:true,body:{getReader:()=>({
        read:async()=>next<lines.length?{done:false,value:Buffer.from(lines[next++])}:{done:true},
        releaseLock:()=>{}
      })}};
    }
    if(path.startsWith('/api/conversation?'))return {ok:true,json:async()=>conversation};
    if(path==='/api/retry'){
      const answer=conversation.messages.at(-1);answerNumber++;
      const text='Alternativa '+answerNumber;
      answer.alternatives.push({content:text,model:conversation.model});
      answer.selected=answer.alternatives.length-1;answer.content=text;
      return {ok:true,json:async()=>({conversation})};
    }
    if(path==='/api/turn-stream'){
      let text;
      if(body.action==='edit'){
        conversation.messages.at(-2).content=body.message;
        text='Resposta revisada';
        conversation.messages.at(-1).alternatives=[{content:text,model:conversation.model}];
        conversation.messages.at(-1).selected=0;
        conversation.title=body.message;entries[0].title=body.message;
      }else{
        answerNumber++;text='Alternativa '+answerNumber;
        const answer=conversation.messages.at(-1);
        answer.alternatives.push({content:text,model:conversation.model});
        answer.selected=answer.alternatives.length-1;
      }
      conversation.messages.at(-1).content=text;
      const lines=[{type:'delta',text:text.slice(0,4)},{type:'delta',text:text.slice(4)},
        {type:'done',conversation}].map(x=>JSON.stringify(x)+'\n');
      let next=0;
      return {ok:true,body:{getReader:()=>({
        read:async()=>next<lines.length?{done:false,value:Buffer.from(lines[next++])}:{done:true},
        releaseLock:()=>{}
      })}};
    }
    if(path==='/api/select-answer'){
      const answer=conversation.messages.at(-1);answer.selected=body.index;
      answer.content=answer.alternatives[body.index].content;
      return {ok:true,json:async()=>({conversation})};
    }
    if(path==='/api/edit'){
      conversation.messages.at(-2).content=body.message;
      conversation.messages.at(-1).content='Resposta revisada';
      conversation.messages.at(-1).alternatives=[{content:'Resposta revisada',model:conversation.model}];
      conversation.messages.at(-1).selected=0;
      conversation.title=body.message;entries[0].title=body.message;
      return {ok:true,json:async()=>({conversation})};
    }
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
  await el('modelBtn').events.click();
  assert.equal(el('modelOptions').children.length,3);
  await el('modelOptions').children[2].events.click();
  assert.equal(el('modelName').textContent,'large:latest');
  el('prompt').value='<script>alert(1)</script>';
  await el('chatForm').events.submit({preventDefault(){}});
  assert.equal(el('messages').children.length,2);
  assert.equal(el('welcome').hidden,true);
  assert.equal(el('chatTitle').textContent,'<script>alert(1)</script>',el('toast').textContent);
  assert.equal(el('messages').children[0].children[1].textContent,'<script>alert(1)</script>');
  const request=requests.find(r=>r.path==='/api/chat-stream');
  assert.equal(request.options.headers['X-Lucios-Token'],'secret-token');
  assert.equal(JSON.parse(request.options.body).conversation_id,'a'.repeat(32));
  assert.equal(JSON.parse(requests.find(r=>r.path==='/api/new').options.body).model,'large:latest');
  assert.equal(el('messages').children[1].children[1].children[0].children[1].tagName,'strong');
  el('search').value='inexistente';el('search').events.input();
  assert.match(el('recentList').textContent,/Nenhuma conversa/);
  el('search').value='';el('search').events.input();
  el('newBtn').events.click();assert.equal(el('welcome').hidden,false);assert.equal(el('messages').children.length,0);
  await el('recentList').children.find(e=>e.className==='recent-row').children[0].events.click();
  await settle();assert.equal(el('messages').children.length,2);
  assert.equal(el('modelName').textContent,'large:latest');
  failChat=true;el('prompt').value='Tente novamente';
  await el('chatForm').events.submit({preventDefault(){}});
  assert.equal(el('messages').children.length,2);assert.equal(el('prompt').value,'Tente novamente');
  assert.match(el('toast').textContent,/indisponível/);
  failChat=false;
  await el('modelBtn').events.click();
  await el('modelOptions').children[1].events.click();
  assert.equal(el('modelName').textContent,'small:latest');
  const answerActions=()=>el('messages').children.at(-1).children[2];
  await answerActions().children[0].events.click();
  assert.equal(el('messages').children.at(-1).children[1].textContent,'Alternativa 1');
  assert.equal(answerActions().children[2].textContent,'2 de 2');
  await answerActions().children[1].events.click();
  assert.match(el('messages').children.at(-1).children[1].textContent,/Resposta/);
  const editButton=el('messages').children.at(-2).children[2].children[0];
  editButton.events.click();
  const editForm=el('messages').children.at(-2).children[1].children[0];
  editForm.children[0].value='Prompt revisado';
  await editForm.events.submit({preventDefault(){}});
  assert.equal(el('chatTitle').textContent,'Prompt revisado');
  assert.equal(el('messages').children.at(-2).children[1].textContent,'Prompt revisado');
  assert.equal(conversation.messages.at(-1).alternatives.length,1);
  el('prompt').value='Próxima pergunta';
  await el('chatForm').events.submit({preventDefault(){}});
  assert.equal(el('messages').children.length,4);
  assert.equal(el('messages').children[0].children.length,2);
  assert.equal(el('messages').children[1].children.length,2);
  await el('labBtn').events.click();assert.equal(opened,1);assert.equal(lastTarget.url,'http://127.0.0.1:12345');
  mobile=true;el('menuBtn').events.click();assert.equal(el('scrim').hidden,false);assert.equal(el('workspace').inert,true);
  el('closeSidebar').events.click();assert.equal(el('scrim').hidden,true);assert.equal(el('sidebar').inert,true);
  const container=new Element();context.container=container;
  vm.runInContext('renderMarkdown("```html\\n<img src=x onerror=alert(1)>\\n```", container)',context);
  assert.equal(container.children[0].tagName,'pre');assert.equal(container.children[0].children[0].children.length,0);
  assert.match(container.textContent,/<img/);
  const deleteButton=()=>el('recentList').children.find(e=>e.className==='recent-row').children[1];
  const existingCount=el('messages').children.length;
  let before=requests.filter(r=>r.path==='/api/delete').length;
  await deleteButton().events.click();
  assert(confirmation.includes(entries[0].title));
  assert.equal(requests.filter(r=>r.path==='/api/delete').length,before);
  assert.equal(el('messages').children.length,existingCount);
  confirmDelete=true;failDelete=true;
  await deleteButton().events.click();
  assert.equal(el('messages').children.length,existingCount);assert.equal(entries.length,1);
  assert.match(el('toast').textContent,/Falha ao excluir/);
  failDelete=false;
  entries.unshift({id:'b'.repeat(32),title:'Outro chat',updated:new Date().toISOString()});
  await vm.runInContext('refreshRecent()',context);
  await deleteButton().events.click();
  assert.equal(el('messages').children.length,existingCount);assert.equal(entries.length,1);
  await deleteButton().events.click();
  assert.equal(entries.length,0);assert.equal(el('messages').children.length,0);
  assert.equal(el('welcome').hidden,false);assert.equal(el('recentCount').textContent,'0');
  el('fileModeBtn').events.click();
  assert.equal(el('fileModeBtn')['aria-pressed'],'true');
  el('prompt').value='Crie uma nota';
  await el('chatForm').events.submit({preventDefault(){}});
  const card=el('messages').children.at(-1);
  assert.equal(card.className,'approval-card');
  assert.match(card.textContent,/Criar uma nota de teste/);
  assert.equal(requests.filter(r=>r.path==='/api/files/decide').length,0);
  await card.children.at(-1).children[1].events.click();
  assert.equal(requests.filter(r=>r.path==='/api/files/decide').length,1);
  assert.match(el('messages').textContent,/Ação concluída/);
  el('prompt').value='Ache o currículo mais atual';
  await el('chatForm').events.submit({preventDefault(){}});
  const selectionCard=el('messages').children.at(-1);
  assert.match(selectionCard.className,/selection-card/);
  assert.match(selectionCard.textContent,/CV_2026.pdf/);
  assert.equal(requests.filter(r=>r.path==='/api/files/select').length,0);
  await selectionCard.children[4].children[0].events.click();
  assert.equal(requests.filter(r=>r.path==='/api/files/select').length,1);
  assert.equal(el('messages').children.at(-1).className,'approval-card');
  console.log('Chat UI: flows, recent search, safe Markdown, errors, lab and mobile menu passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
