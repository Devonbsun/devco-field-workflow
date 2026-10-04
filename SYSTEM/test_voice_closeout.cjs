const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'voice_closeout.js'),'utf8');
function setup(options={}){
 const nodes={},calls=[],navigation=[],storage=new Map(),handlers={};
 function element(id){return nodes[id]||(nodes[id]={value:'',textContent:'',hidden:true,disabled:true,events:{},addEventListener(n,fn){this.events[n]=fn;},focus(){},submit(){throw Error('Unexpected auto-submit');}});}
 const note=element('note'),form=element('form');form.elements={note};
 const document={hidden:false,querySelector(){return form;},getElementById:element,addEventListener(n,fn){handlers[n]=fn;}};
 const window={devcoVoiceConfig:{job:'TEST',ju:'101',autostart:options.autostart!==false},devcoSaveBillingNote:async()=>{},devcoAcceptSavedNote(value){note.value=value;},addEventListener(n,fn){handlers[n]=fn;}};
 const context={window,document,location:{set href(v){navigation.push(v);}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},Date,Math,JSON,encodeURIComponent,AbortController,setInterval:()=>1,clearInterval(){},setTimeout(){},fetch:async(url,args)=>{
  calls.push({url,args});
  if(options.fetch)return options.fetch(url,args);
  let result=url==='/status'?{job:'TEST',ju:'101'}:url==='/voice-note'?{note:'Surveyed the pole.',review_reason:''}:{close:'ADSS',message:'Review before finalizing.'};
  return {ok:true,json:async()=>result};
 }};
 vm.runInNewContext(source,context);
 function event(type,transcript='',stage){const prompt=[...navigation].reverse().find(s=>s.includes('://prompt'));const url=new URL(prompt);return window.devcoVoiceEvent({session:url.searchParams.get('session'),stage:stage||url.searchParams.get('stage'),type,transcript,message:'Test message'});}
 return {nodes,note,window,calls,navigation,event,handlers,document};
}
test('automatic notes then close selection waits for final review',async()=>{
 const app=setup();assert.equal(app.navigation.length,0);
 await app.window.devcoVoiceReady();await app.window.devcoVoiceReady();
 assert.equal(app.navigation.filter(s=>s.includes('://prompt')).length,1);
 await app.event('result','Um I surveyed the pole');
 assert.equal(app.note.value,'Surveyed the pole.');
 assert.match(app.navigation.at(-1),/stage=close/);
 await app.event('result','ADSS');
 assert.equal(app.nodes['voice-close'].value,'ADSS');
 assert.equal(app.nodes['voice-finalize'].disabled,false);
 assert.equal(app.nodes['voice-finalize'].value,'ADSS');
 assert.equal(app.nodes['voice-review'].hidden,false);
 assert.equal(app.calls.filter(c=>c.url==='/finish').length,0);
});
test('manual typing cancels speech and ignores late transcript',async()=>{
 const app=setup();await app.window.devcoVoiceReady();app.note.value='Manual note';
 app.note.events.input();await app.event('result','Overwrite this note','notes');
 assert.equal(app.note.value,'Manual note');assert.equal(app.calls.filter(c=>c.url==='/voice-note').length,0);
});
test('a changed active JU never starts prompts',async()=>{
 const app=setup({fetch:async()=>({ok:true,json:async()=>({job:'TEST',ju:'102'})})});
 await app.window.devcoVoiceReady();assert.equal(app.navigation.filter(s=>s.includes('://prompt')).length,0);
 assert.match(app.nodes['voice-status'].textContent,/active JU changed/);
});
test('no close prompt after a failed note save',async()=>{
 const app=setup({fetch:async url=>({ok:url==='/status',json:async()=>url==='/status'?{job:'TEST',ju:'101'}:{error:'Save failed'}})});
 await app.window.devcoVoiceReady();await app.event('result','Test note');
 assert.equal(app.navigation.filter(s=>s.includes('stage=close')).length,0);
 assert.equal(app.nodes['voice-finalize'].disabled,true);
});
test('unclear speech retries once then leaves manual review available',async()=>{
 const app=setup();await app.window.devcoVoiceReady();await app.event('retry');await app.event('retry');
 assert.equal(app.navigation.filter(s=>s.includes('://prompt')).length,2);
 assert.equal(app.nodes['voice-review'].hidden,false);
 assert.equal(app.nodes['voice-finalize'].disabled,true);
});
test('validation-error reload never auto-prompts',async()=>{
 const app=setup({autostart:false});await app.window.devcoVoiceReady();assert.equal(app.navigation.length,0);
});
