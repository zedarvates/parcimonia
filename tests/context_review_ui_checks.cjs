// Unit tests of the generated script with a tiny DOM stand-in; no browser automation.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const data = html.match(/<script type="application\/json" id="packet">([\s\S]*?)<\/script>/)[1];
const script = html.match(/<script nonce="local-review">([\s\S]*?)<\/script>/)[1];
const elements = new Map();
class Element {
  constructor(tag='div') { this.tag=tag;this.value='';this.checked=false;this.textContent='';this.children=[];this.disabled=false;this.style={}; }
  set id(value) {this._id=value;elements.set(value,this)}
  get id() {return this._id}
  append(...items) {this.children.push(...items)}
  replaceChildren(...items) {this.children=items}
  setAttribute() {}
  addEventListener(name, action) {this[name+'Handler']=action}
  click() {if(this.onclick)this.onclick()}
}
for(const match of html.matchAll(/\bid="([^"]+)"/g)){const node=new Element();node.id=match[1]}
elements.get('packet').textContent=data;
elements.get('filter').value='all';
const memory = new Map();
const context=vm.createContext({document:{getElementById:id=>elements.get(id),createElement:tag=>new Element(tag)},
  localStorage:{getItem:key=>memory.get(key)||null,setItem:(key,value)=>memory.set(key,value)},
  window:{scrollTo(){}},console,JSON,Date,Set,Blob,URL,setTimeout});
new vm.Script(script).runInContext(context);
function run(code){return vm.runInContext(code,context)}
assert.equal(elements.get('progress').textContent,'0 / 2');
const initial=JSON.parse(run('JSON.stringify(exportRecord())'));
assert.equal(initial.claim_allowed,false);
assert.equal(initial.auto_act_allowed,false);
assert.ok(Object.values(initial.annotations).every(a=>Object.values(a.labels).every(v=>v===null)));
// Synthetic annotation exercises empty vs unknown and explicit attribution.
run(`state.reviewer='fixture-reviewer';$('reviewer').value=state.reviewer;$('sourceReviewed').checked=true;
$('language').value='fr';$('kindMode').value='known';$('taskKind').value='extract';
$('evidenceBasis').value='recorded_input';$('rationale').value='Synthetic contract test';
for(const name of fieldNames)$(name+'Mode').value='unknown';$('provided_fieldsMode').value='none';
$('complete').checked=true;save();`);
const reviewed=JSON.parse(run('JSON.stringify(exportRecord())'));
const annotation=Object.values(reviewed.annotations)[0];
assert.deepEqual(annotation.labels.provided_fields,[]);
assert.equal(annotation.labels.required_context,null);
assert.equal(annotation.labeler_id,'fixture-reviewer');
assert.equal(annotation.complete,true);
assert.equal(elements.get('progress').textContent,'1 / 2');
assert.throws(()=>run(`importReview({kind:'context_human_review',packet_id:'foreign',annotations:{}})`),/correspond/);
// Changing the current annotator must not silently reattribute other completed cases.
run(`index=1;draw();state.reviewer='another-fixture-reviewer';$('reviewer').value=state.reviewer;save();`);
const changed=JSON.parse(run('JSON.stringify(exportRecord())'));
assert.equal(Object.values(changed.annotations).find(a=>a.complete).labeler_id,'fixture-reviewer');
// Imported unknown modes cannot turn an unreviewed field into completed review.
context.imported=reviewed;
run(`const first=Object.keys(imported.annotations)[0];imported.annotations[first].field_modes.required_context='forged';importReview(imported);`);
assert.equal(elements.get('progress').textContent,'0 / 2');
assert.ok(memory.size>0);
console.log('Generated UI script: blank labels, provenance review, null vs empty, attribution, autosave and import guards passed.');
