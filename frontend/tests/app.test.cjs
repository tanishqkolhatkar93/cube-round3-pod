const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  const elements = new Map();
  const element = (tag = '') => ({tag, children: [], listeners: {}, hidden: false, textContent: '', className: '', disabled: false,
    addEventListener(type, fn) { this.listeners[type] = fn; },
    replaceChildren(...children) { this.children = children; }, append(...children) { this.children.push(...children); }, focus() {},
    classList: {toggle() {}}, elements: {token: {value: ''}, org_id: {focus() {}}}});
  const context = vm.createContext({console, FormData, AbortSignal, document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element, querySelectorAll: () => [], addEventListener() {},
  }, window: {confirm: () => true, scrollTo() {}}, localStorage: {getItem: () => null, setItem() {}}});
  const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
  vm.runInContext(source.replace(/initialize\(\);\s*$/, ''), context);
  vm.runInContext(`state.session = {org_id:'org_demo_alpha', actor:'operator'};
    state.workflowId = 'WF-A'; renderDetail = () => {}; loadRecentWorkflows = async () => {};`, context);
  return {context, elements, run: (code) => vm.runInContext(code, context)};
}

test('resume does not claim refreshed success when evidence refresh fails', async () => {
  const h = harness();
  h.run(`request = async (path) => { if(path.endsWith('/evidence')) throw new Error('offline'); return {}; };`);
  await h.run('resumeWorkflow()');
  assert.match(h.elements.get('global-notice').textContent, /Could not refresh/);
  assert.equal(h.elements.get('resume-button').disabled, false);
});

test('slow workflow response cannot replace a newer selected workflow', async () => {
  const h = harness();
  h.run(`var finishA; request = (path) => path.includes('WF-A')
    ? new Promise(resolve => {finishA = resolve;})
    : Promise.resolve({workflow:{workflow_id:'WF-B'}, evidence:{}});`);
  const first = h.run(`openWorkflow('WF-A')`);
  await h.run(`openWorkflow('WF-B')`);
  h.run(`finishA({workflow:{workflow_id:'WF-A'},evidence:{}})`);
  await first;
  assert.equal(h.run('state.workflow.workflow_id'), 'WF-B');
  assert.equal(h.run('state.workflowId'), 'WF-B');
});

test('logout invalidates an outstanding workflow response', async () => {
  const h = harness();
  h.run(`var finish; request = () => new Promise(resolve => {finish = resolve;});`);
  const pending = h.run(`openWorkflow('WF-A')`);
  h.run(`showLogin(); finish({workflow:{workflow_id:'WF-A'},evidence:{}});`);
  await pending;
  assert.equal(h.run('state.workflow'), null);
  assert.equal(h.run('state.bundle'), null);
});

test('successful workflow lookup clears its loading message', async () => {
  const h = harness();
  h.run(`byId('lookup-message').textContent = 'Loading workflow…';
    request = async () => ({workflow:{workflow_id:'WF-A'},evidence:{}});`);
  await h.run(`openWorkflow('WF-A')`);
  assert.equal(h.elements.get('lookup-message').textContent, '');
});

test('override does not hide a failed refresh or leave its submit button disabled', async () => {
  const h = harness();
  h.context.FormData = class { get(key) { return {new_verdict:'PASS',reason:'Reviewed'}[key]; } };
  h.run(`var submit = {disabled:false}; var form = {dataset:{recordId:'REC-A'}, querySelector:() => submit};
    request = async path => {if(path.endsWith('/evidence')) throw new Error('offline'); return {};};`);
  await h.run(`submitOverride({preventDefault(){},currentTarget:form})`);
  assert.match(h.elements.get('global-notice').textContent, /Could not refresh/);
  assert.equal(h.run('submit.disabled'), false);
});

test('old unauthorized response cannot sign out a newer session', async () => {
  const h = harness();
  h.run(`var finish; fetch = () => new Promise(resolve => {finish = resolve;});`);
  const pending = h.run(`request('/workflows/WF-A')`);
  h.run(`state.session = {org_id:'org_demo_bravo'};
    finish({ok:false,status:401,text:async ()=>'Expired'});`);
  await assert.rejects(pending, /Expired/);
  assert.equal(h.run('state.session.org_id'), 'org_demo_bravo');
});

test('empty intake and invalid image types/sizes are rejected', async () => {
  const h = harness();
  assert.match(h.run(`uploadError({type:'text/plain',size:10})`), /JPEG/);
  assert.match(h.run(`uploadError({type:'image/png',size:10000001})`), /10 MB/);
  assert.equal(h.run(`uploadError({type:'image/webp',size:100})`), '');
  h.context.FormData = class {get() {return '';}};
  await h.run(`submitImages({preventDefault(){}, currentTarget:{}})`);
  assert.match(h.elements.get('create-message').textContent, /at least one/);
});

test('multiple previews are local and cleared on sign-out', () => {
  const h = harness();
  let revoked = 0;
  h.context.URL = {createObjectURL: () => 'blob:local', revokeObjectURL: () => {revoked++;}};
  h.run(`renderUploads = () => {}; addImages([{name:'a',type:'image/png',size:20},{name:'b',type:'image/jpeg',size:30}]);`);
  assert.equal(h.run('state.uploads.length'), 2);
  h.run('showLogin()');
  assert.equal(revoked, 2);
  assert.equal(h.run('state.uploads.length'), 0);
});

test('duplicate submit is ignored while processing', async () => {
  const h = harness();
  h.run('state.submitting = true; request = () => {throw new Error("must not call");};');
  await h.run('submitImages({preventDefault(){},currentTarget:{}})');
});

test('missing associations never reach upload API', async () => {
  const h = harness();
  h.context.FormData = class {get(k) {return k === 'route' ? 'fba' : 'false';}};
  h.run(`state.uploads = [{unit:'',stage:'receiving'}]; request = () => {throw new Error('must not call');};`);
  await h.run('submitImages({preventDefault(){},currentTarget:{}})');
  assert.match(h.elements.get('create-message').textContent, /Confirm each/);
});

test('default image cards have no stage or manager selector, and removal works', () => {
  const h = harness();
  let revoked = 0;
  h.context.URL = {createObjectURL: () => 'blob:local', revokeObjectURL: () => {revoked++;}};
  h.run(`addImages([{name:'front.png',type:'image/png',size:20},{name:'back.png',type:'image/png',size:20}])`);
  const flatten = el => [el, ...(el.children || []).flatMap(flatten)];
  const list = h.elements.get('upload-list');
  const nodes = flatten(list);
  assert.equal(nodes.filter(n => n.tag === 'select').length, 0);
  assert.equal(nodes.filter(n => n.tag === 'img').length, 2);
  assert.equal(h.run(`Object.hasOwn(state.uploads[0], 'stage')`), false);
  nodes.find(n => n.tag === 'button').listeners.click();
  assert.equal(h.run('state.uploads.length'), 1);
  assert.equal(revoked, 1);
});

test('multiple images submit without stage metadata and retain server associations', async () => {
  const h = harness();
  h.context.FormData = class {get(k) { return {route:'mfn',returned:'false'}[k]; }};
  h.context.URL = {revokeObjectURL() {}};
  h.run(`var requests = []; var opened;
    state.uploads = [1,2].map(n => ({unit:'U1',file:{type:'image/png',n},url:'blob:' + n}));
    openWorkflow = async id => {opened = id;};
    request = async (path, options) => {
      requests.push({path,options});
      if(path.startsWith('/uploads')) return {receipt_id:'R'+options.body.n,stage: options.body.n === 1 ? 'receiving' : 'pack'};
      return {workflow_id:'WF-1',status:'NEEDS_REVIEW'};
    };`);
  await h.run(`submitImages({preventDefault(){},currentTarget:{querySelectorAll(){return [];}}})`);
  const requests = h.run('requests');
  assert.equal(requests.length, 3);
  assert.ok(requests.slice(0, 2).every(r => r.path === '/uploads?unit_id=U1'));
  assert.deepEqual(JSON.parse(requests[2].options.body).receipts, ['R1','R2']);
  assert.equal(h.run('opened'), 'WF-1');
  assert.match(h.elements.get('create-message').textContent, /acceptance is not approval/);
  assert.equal(h.run('state.submitting'), false);
});

test('ambiguous image shows capture-reference resolution and never starts workflow', async () => {
  const h = harness();
  h.context.FormData = class {get(k) {return {route:'mfn',returned:'false'}[k];}};
  h.run(`state.uploads = [{unit:'U1',file:{name:'photo',type:'image/png'},url:'blob:1'}];
    var calls = []; request = async path => {calls.push(path); throw new ApiError('Multiple trusted captures; supply the reference.',409,{required_information:'capture_ref'});};`);
  await h.run(`submitImages({preventDefault(){},currentTarget:{querySelectorAll(){return [];}}})`);
  assert.equal(h.run('calls.length'), 1);
  assert.equal(h.run('state.uploads[0].needsCaptureRef'), true);
  assert.match(h.run('state.uploads[0].status'), /Unresolved/);
  assert.equal(h.run('state.submitting'), false);
  h.run(`state.uploads[0].captureRef = 'capture/photo.png'; request = async path => {calls.push(path); throw new Error('stop after retry');};`);
  await h.run(`submitImages({preventDefault(){},currentTarget:{querySelectorAll(){return [];}}})`);
  assert.match(h.run('calls.at(-1)'), /capture_ref=capture%2Fphoto.png/);
});

test('structured unresolved API errors retain actionable details', async () => {
  const h = harness();
  h.run(`fetch = async () => ({ok:false,status:422,text:async () => JSON.stringify({detail:{status:'unresolved',code:'capture_unresolved',message:'Register the capture first.'}})});`);
  await assert.rejects(h.run(`request('/uploads?unit_id=U1')`), error => {
    assert.equal(error.message, 'Register the capture first.');
    assert.equal(error.detail.status, 'unresolved');
    return true;
  });
});
