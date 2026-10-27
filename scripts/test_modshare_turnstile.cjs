const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sourceFile = path.join(__dirname, '../modshare/static/modshare/human-verification.js');
const source = fs.existsSync(sourceFile) ? fs.readFileSync(sourceFile, 'utf8') : '';
function setup(sitekey, unloaded=false) {
  const callbacks = []; const resets = [];
  class Element {
    constructor() { this.children = []; this.textContent = ''; this.hidden = false; this.clientWidth = 250; this.listeners={}; }
    append(...children) { this.children.push(...children); }
    insertBefore(element) { this.children.push(element); }
    setAttribute() {}
    addEventListener(name, listener) { this.listeners[name]=listener; }
    remove() { this.removed=true; }
    querySelector() { return new Element(); }
  }
  const window = { turnstile: {
    render(element, options) { callbacks.push(options); return 'widget-id'; },
    reset(widget) { resets.push(widget); },
  }};
  const service=window.turnstile;
  if(unloaded)delete window.turnstile;
  const head=new Element(); let clock=0;
  const context = { window, document: {head, documentElement:{dataset:{turnstileSitekey:sitekey}}, createElement:()=>new Element() },
    setTimeout:unloaded?(fn)=>setTimeout(fn,1):setTimeout, clearTimeout, Error,
    Date:unloaded?{now:()=>clock+=31000}:Date };
  vm.runInNewContext(source, context);
  assert.ok(window.ChatArchiveHumanVerification, 'Turnstile form helper must exist');
  return {window, callbacks, resets, form:new Element(), head, service};
}
(async () => {
  const disabled = setup('');
  assert.equal(disabled.window.ChatArchiveHumanVerification.mount(disabled.form, 'register').consume(), undefined);
  assert.equal(disabled.callbacks.length, 0);
  const enabled = setup('test-public-sitekey');
  const gate = enabled.window.ChatArchiveHumanVerification.mount(enabled.form, 'register');
  await gate.ready;
  assert.equal(enabled.callbacks[0].action, 'register');
  assert.equal(enabled.callbacks[0]['response-field'], false);
  assert.equal(enabled.callbacks[0].size, 'compact');
  assert.throws(() => gate.consume(), /验证/);
  enabled.callbacks[0].callback('token-one');
  assert.equal(gate.consume(), 'token-one');
  assert.throws(() => gate.consume(), /验证/);
  gate.reset();
  assert.deepEqual(enabled.resets, ['widget-id']);
  enabled.callbacks[0].callback('token-two');
  enabled.callbacks[0]['expired-callback']();
  assert.throws(() => gate.consume(), /验证/);
  enabled.callbacks[0].callback('token-three');
  enabled.callbacks[0]['error-callback']('error');
  assert.throws(() => gate.consume(), /验证/);
  gate.reset();
  enabled.callbacks[0].callback('new-token');
  assert.equal(gate.consume(), 'new-token');
  const broken=setup('test-public-sitekey',true);
  const recovery=broken.window.ChatArchiveHumanVerification.mount(broken.form,'login');
  await recovery.ready;
  assert.equal(broken.head.children.length,1,'initial script must be requested');
  assert.equal(broken.form.children[0].children[3].hidden,false,'failed load exposes retry');
  recovery.reset();
  assert.equal(broken.head.children.length,2,'retry must request a fresh script after load failure');
  broken.window.turnstile=broken.service;
  broken.head.children.at(-1).onload();
  await recovery.ready;
  broken.callbacks[0].callback('recovered');
  assert.equal(recovery.consume(),'recovered');
  broken.callbacks[0]['error-callback']('110200');
  assert.match(broken.form.children[0].children[2].textContent,/110200/,'keep the code for troubleshooting');
  assert.throws(()=>recovery.consume(),/验证/);
  console.log('Turnstile helper: disabled preview, action, responsive widget, single use, reset, expiry and failure checks passed');
})().catch(error => { console.error(error.message); process.exitCode = 1; });
