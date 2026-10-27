const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('modshare/static/modshare/app.js','utf8');

function setup({page='home',meMode='pending',ticketFails=false}={}){
  const nodes=new Map(),calls=[],listeners=new Map(),timers=[],navigations=[];
  function node(id){
    if(!nodes.has(id))nodes.set(id,{innerHTML:'',textContent:'',hidden:false,dataset:{},elements:{q:{value:''}},
      classList:{add(){},remove(){},toggle(){}},setAttribute(){},getAttribute(){return 'false';},
      addEventListener(type,fn){listeners.set(id+':'+type,fn);},querySelectorAll(){return [];},querySelector(){return null;},insertAdjacentHTML(){}});
    return nodes.get(id);
  }
  const document={documentElement:{dataset:{base:'',page,id:''}},cookie:'modcsrftoken=test-csrf',title:'',
    getElementById:node,querySelectorAll(){return [];},body:{append(){}},createElement(){return {click(){},remove(){}};}};
  const fetch=(url,options)=>{
    calls.push({url,options});
    if(url.includes('/api/me/'))return meMode==='reject'?Promise.reject(new Error('offline')):new Promise((resolve,reject)=>{
      options.signal?.addEventListener('abort',()=>reject(Object.assign(new Error('abort'),{name:'AbortError'})));
    });
    if(url.includes('/ticket/'))return Promise.resolve(ticketFails?
      {ok:false,status:401,json:async()=>({ok:false,error:{message:'请先登录。'}})}:
      {ok:true,status:200,json:async()=>({ok:true,data:{url:'/download/test-id/?ticket=short-lived-test',expires_in:900}})});
    return Promise.resolve({ok:true,status:200,json:async()=>({ok:true,data:{items:[],page:1,pages:1,total:0}})});
  };
  const context={document,location:{pathname:'/',search:'',assign(url){navigations.push(url);}},fetch,URLSearchParams,AbortController,FormData,
    setTimeout(fn,ms){timers.push({fn,ms});return timers.length;},clearTimeout(){},console};
  vm.runInNewContext(source,context);
  return {nodes,calls,listeners,timers,navigations};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  const slow=setup();await tick();await tick();
  assert(slow.calls.some(c=>c.url.includes('/api/resources/')),'Public list must start while account request is pending');
  assert(slow.nodes.get('content').innerHTML.includes('发现创作'),'Public page must render without waiting for account');
  const timeout=slow.timers.find(t=>t.ms===8000);assert(timeout,'Account request needs a bounded timeout');
  timeout.fn();await tick();await tick();
  assert(slow.nodes.get('content').innerHTML.includes('发现创作'),'Account timeout must preserve public content');
  const failed=setup({meMode:'reject'});await tick();await tick();
  assert(failed.nodes.get('content').innerHTML.includes('发现创作'),'Account failure must not replace public content');
  const protectedPage=setup({page:'manage'});await tick();
  assert(!protectedPage.calls.some(c=>c.url.includes('/api/manage/')),'Protected page must wait for identity');
  const download=setup();await tick();
  const link={dataset:{downloadRevision:'test-id',downloadReview:'1'},setAttribute(){},removeAttribute(){}};
  let prevented=false;
  const event={target:{closest(){return link;}},button:0,preventDefault(){prevented=true;}};
  const click=download.listeners.get('content:click');
  const first=click(event),second=click(event);await Promise.all([first,second]);
  const minted=download.calls.filter(c=>c.url.includes('/ticket/'));
  assert.equal(minted.length,1,'Repeated clicks must not issue duplicate tickets');
  assert.equal(minted[0].options.method,'POST');
  assert.equal(minted[0].options.headers['X-CSRFToken'],'test-csrf');
  assert.equal(JSON.parse(minted[0].options.body).review,true);
  assert(prevented);assert.deepEqual(download.navigations,['/download/test-id/?ticket=short-lived-test']);
  assert.equal(link.dataset.downloadBusy,undefined);
  const denied=setup({ticketFails:true});await tick();
  await denied.listeners.get('content:click')(event);
  assert.equal(denied.navigations.length,0,'Failed authorization must not navigate to raw download');
  assert.equal(denied.nodes.get('toast').textContent,'请先登录。');
  console.log('Public loading, identity failure/timeout, protected ordering, and authorized download dispatch checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
