/* Small, session-authenticated UI. All file links use the controlled download endpoint. */
(() => {
  'use strict';
  const root = document.documentElement;
  const base = (root.dataset.base || '').replace(/\/$/, '');
  const page = root.dataset.page || 'home';
  const objectId = root.dataset.id || '';
  const content = document.getElementById('content');
  const params = new URLSearchParams(location.search);
  const state = {user:null,quota:{used:0,limit:5,remaining:5},limits:{max_file_bytes:50000000,max_preview_bytes:2000000},meReady:false};
  const statusNames = {pending:'待审核',published:'已发布',approved:'审核通过',rejected:'已驳回',unpublished:'已下架',draft:'待提交',banned:'已封禁',superseded:'已被新修订替换'};
  const roleNames = {owner:'超级管理员',admin:'管理员',user:'普通用户'};
  const icons = {
    search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>',
    file:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M6 3h8l4 4v14H6Z"/><path d="M14 3v5h4M9 12h6M9 16h6"/></svg>',
    upload:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/></svg>',
    download:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5"/></svg>'
  };
  function esc(value) {return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function url(path) {return base + path;}
  function id(value) {return encodeURIComponent(String(value));}
  function category(value) {return value==='presets'?'预设':'素材';}
  function size(value) {const n=Number(value)||0;return n>=1000000?`${(n/1000000).toFixed(n>=10000000?1:2)} MB`:n>=1000?`${(n/1000).toFixed(1)} KB`:`${n} B`;}
  function date(value,full=false) {if(!value)return '—';const d=new Date(value);if(Number.isNaN(d.getTime()))return '—';return d.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',...(full?{hour:'2-digit',minute:'2-digit',hour12:false}:{})}).replace(/\//g,'.');}
  function list(data) {return Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[];}
  function isManager() {return ['admin','owner'].includes(state.user?.role);}
  function csrf() {const cookie=document.cookie.split('; ').find(c=>c.startsWith('modcsrftoken='));return cookie?decodeURIComponent(cookie.slice('modcsrftoken='.length)):'';}
  async function api(path,options={}) {
    const {method='GET',body,signal}=options;
    const headers={Accept:'application/json'};
    if(method!=='GET'){headers['X-CSRFToken']=csrf();if(!(body instanceof FormData))headers['Content-Type']='application/json';}
    let response;
    try {response=await fetch(url('/api/'+path),{method,credentials:'same-origin',headers,signal,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});}
    catch(e){if(e.name==='AbortError')throw e;throw new Error('网络连接中断，请检查连接后重试。');}
    let payload;
    try {payload=await response.json();} catch{throw new Error(response.status===413?'文件超出服务器允许的大小，请选择 50 MB 以内的文件。':'服务器暂时未能返回内容，请稍后重试。');}
    if(!response.ok||payload.ok!==true){const e=new Error(payload.error?.message||'请求未完成，请稍后重试。');e.fields=payload.error?.fields||{};e.status=response.status;e.code=payload.error?.code;throw e;}
    return payload.data;
  }
  function mount(html) {content.innerHTML=html;content.setAttribute('aria-busy','false');document.querySelectorAll('[data-link]').forEach(a=>a.href=url(a.dataset.link));}
  function toast(message,error=false) {const el=document.getElementById('toast');el.textContent=message;el.classList.toggle('error',error);el.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{el.hidden=true;},5500);}
  function empty(title,copy,action='') {return `<div class="empty-state"><span class="empty-symbol" aria-hidden="true">◇</span><h2>${esc(title)}</h2><p>${esc(copy)}</p>${action}</div>`;}
  function notice(copy,danger=false) {return `<div class="notice${danger?' danger':''}">${copy}</div>`;}
  function badge(status) {return `<span class="status ${esc(status)}">${esc(statusNames[status]||status||'待审核')}</span>`;}
  function heading(title,sub,kicker='COMMUNITY COLLECTION',action='') {return `<div class="page-heading"><div><span class="eyebrow">${esc(kicker)}</span><h1>${esc(title)}</h1><p>${esc(sub)}</p></div>${action}</div>`;}
  function field(name,label,type='text',placeholder='',extra='') {return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" placeholder="${esc(placeholder)}" ${extra}><p class="field-error" id="error-${name}" hidden></p></div>`;}
  function formError(error,form) {
    const box=form.querySelector('.form-error');if(box){box.textContent=error.message;box.hidden=false;}
    const fields=error.fields||{};
    for(const [key,value] of Object.entries(fields)){const input=form.elements.namedItem(key);if(input?.setAttribute)input.setAttribute('aria-invalid','true');const el=form.querySelector(`#error-${CSS.escape(key)}`);if(el){el.textContent=Array.isArray(value)?value.join(' '):typeof value==='string'?value:'请检查此项。';el.hidden=false;if(input?.setAttribute)input.setAttribute('aria-describedby',el.id);}}
    const first=form.querySelector('[aria-invalid=true]');if(first)first.focus();else if(box){box.tabIndex=-1;box.focus();}
  }
  function clearErrors(form) {form.querySelectorAll('.form-error,.field-error,.form-success').forEach(el=>{el.hidden=true;});form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));}
  function busy(form,value,label) {
    for(const el of form.querySelectorAll('input,select,textarea,button')){if(el.id==='cancel-upload')continue;if(value){el.dataset.wasDisabled=String(el.disabled);el.disabled=true;}else{el.disabled=el.dataset.wasDisabled==='true';delete el.dataset.wasDisabled;}}
    const submit=form.querySelector('[type=submit]');if(submit){if(value){submit.dataset.oldText=submit.textContent;submit.textContent=label||'正在提交…';}else if(submit.dataset.oldText){submit.textContent=submit.dataset.oldText;delete submit.dataset.oldText;}}
  }
  function accountNav() {
    const el=document.getElementById('account-nav');
    if(!state.user){el.innerHTML=`<a href="${url('/login/')}" class="button small">登录 / 注册</a>`;return;}
    const u=state.user;
    el.innerHTML=`<details class="account-menu"><summary><span class="avatar">${esc((u.display_name||u.email||'创')[0])}</span><span class="account-name">${esc(u.display_label||u.display_name||'我的账号')}</span><span class="faint" aria-hidden="true">⌄</span></summary><div class="dropdown"><div class="account-email">${esc(u.email)}<br><span class="role-label">${esc(roleNames[u.role]||'普通用户')}</span></div><a href="${url('/my-uploads/')}">我的投稿</a>${isManager()?`<a href="${url('/manage/')}">管理中心</a>`:''}<a href="${url('/reset-password/')}">重设密码</a><button type="button" id="logout-button">退出登录</button></div></details>`;
    document.getElementById('logout-button').addEventListener('click',async e=>{e.target.disabled=true;try{await api('auth/logout/',{method:'POST',body:{}});location.assign(url('/'));}catch(err){e.target.disabled=false;toast(err.message,true);}});
  }
  async function loadMe() {
    const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),8000);
    try{const data=await api('me/',{signal:controller.signal});state.user=data.user;state.quota=data.quota||state.quota;state.limits=data.limits||state.limits;state.meReady=true;accountNav();}
    catch(error){if(error.name==='AbortError')throw new Error('账号状态读取超时，可刷新重试；公开资源仍可浏览。');throw error;}
    finally{clearTimeout(timeout);}
    const banner=document.getElementById('global-banner');
    if(state.user?.banned){banner.textContent=`你的账号已被封禁，暂时无法上传、修改或下载。原因：${state.user.ban_reason||'请联系管理员了解详情。'}`;banner.classList.add('danger');banner.hidden=false;}
    else if(state.meReady){banner.hidden=true;banner.classList.remove('danger');}
  }
  function requireUser(manage=false) {
    if(!state.user){mount(empty('先登录，再继续','登录后即可分享创作、查看投稿和下载资源。',`<a class="button primary" href="${url('/login/')}?next=${encodeURIComponent(location.pathname+location.search)}">登录账号 <span aria-hidden="true">→</span></a>`));return false;}
    if(manage&&!isManager()){mount(empty('此页面仅供管理员访问','你的账户没有管理权限。',`<a class="button" href="${url('/')}">返回资源首页</a>`));return false;}
    return true;
  }
  function tag(cat) {return `<span class="tag${cat==='presets'?' preset':''}">${category(cat)}区</span>`;}
  function example(r,compact=false) {
    const picture=r?.preview;if(!picture?.url)return '';
    const image=`<img src="${esc(compact?(picture.thumbnail_url||picture.url):picture.url)}" alt="${esc((r.title||'资源')+'例图')}" loading="lazy" decoding="async">`;
    return compact?`<div class="card-cover">${image}</div>`:`<figure class="example-figure"><a href="${esc(picture.url)}" target="_blank" rel="noopener">${image}</a><figcaption>资源例图 · 点击查看大图</figcaption></figure>`;
  }
  function ratingTag(r) {
    const rating=r.rating;if(!rating)return '';
    return `<div class="rating-summary"><span class="rating-tag ${esc(rating.key)}">${esc(rating.label)}</span><span>${rating.total?`${Number(rating.positive_percent).toFixed(1)}% 好评 · ${rating.total} 条评价${rating.small_sample?' · 评价较少':''}`:'等待第一份评价'}</span></div>`;
  }
  function interactionStats(r) {return `<div class="interaction-stats"><span>↓ ${Number(r.download_count)||0} 下载</span><span>♡ ${Number(r.favorite_count)||0} 喜爱</span><span>▽ ${Number(r.dislike_count)||0} 差评</span></div>${ratingTag(r)}`;}

  function resourceCard(r) {const f=r.file||{};return `<a class="resource-card" href="${url('/mods/'+id(r.id)+'/')}">${example(r,true)}<div class="card-top"><span class="file-glyph">${icons.file}<span>${esc((f.extension||'FILE').toUpperCase())}</span></span>${tag(r.category)}</div><h3>${esc(r.title)}</h3><p class="description">${esc(r.description)}</p><div class="card-meta"><span>${esc(size(f.size))}</span><span>·</span><span>${esc(date(r.published_at||r.created_at))}</span></div>${interactionStats(r)}<div class="card-bottom"><span class="card-author"><span class="mini-avatar" aria-hidden="true">${esc((r.author?.name||'创')[0])}</span>${esc(r.author?.name||'社区创作者')}</span><span class="card-arrow" aria-hidden="true">↗</span></div></a>`;}
  async function rankingsPage() {
    const metric=['downloads','likes'].includes(params.get('metric'))?params.get('metric'):'downloads';
    const period=['day','week','month','all'].includes(params.get('period'))?params.get('period'):'day';
    const cat=['characters','presets'].includes(params.get('category'))?params.get('category'):'';
    const query=new URLSearchParams({metric,period,category:cat,page:params.get('page')||'1'});
    const data=await api('rankings/?'+query);
    const filter=(key,choices,current)=>`<div class="tabs" aria-label="${key==='metric'?'排名指标':key==='period'?'统计周期':'资源分类'}">${choices.map(([value,label])=>{const q=new URLSearchParams({metric,period,category:cat});q.set(key,value);return `<a class="${current===value?'active':''}" ${current===value?'aria-current="true"':''} href="${url('/rankings/')}?${q}">${label}</a>`;}).join('')}</div>`;
    mount(`${heading('社区榜单','发现大家正在下载与喜爱的创作。','COMMUNITY PICKS')}<section class="panel ranking-filters">${filter('metric',[['downloads','下载榜'],['likes','喜爱榜']],metric)}${filter('period',[['day','日榜'],['week','周榜'],['month','月榜'],['all','总榜']],period)}${filter('category',[['','全部作品'],['characters','素材区'],['presets','预设区']],cat)}<p class="field-hint">北京时间 · 自然日 / 周一开始的自然周 / 自然月。下载按每人每件作品每日一次统计；取消的喜爱不计，再次喜爱保留首次时间。</p></section>${list(data).length?`<div class="resource-grid ranked-grid">${list(data).map(r=>`<article class="ranked-resource"><span class="rank-number${r.rank<=3?' podium':''}">#${r.rank}<small>${r.score} ${metric==='likes'?'喜爱':'下载'}</small></span>${resourceCard(r)}</article>`).join('')}</div>`:empty('这份榜单等待新的发现','当前周期还没有有效互动，去素材区或预设区看看吧。',`<a class="button primary" href="${url('/characters/')}">浏览素材区 →</a>`)}${pagination(data,'/rankings/',{metric,period,category:cat})}`);
  }
  function favoriteControl(r) {
    if(r.status!=='published')return '';
    if(!state.user)return `<a class="button full favorite-button" href="${url('/login/')}?next=${encodeURIComponent(location.pathname+location.search)}">登录后评价作品</a>`;
    return `<div class="reaction-buttons"><button id="favorite-button" class="button full favorite-button${r.liked?' liked':''}" aria-pressed="${Boolean(r.liked)}" ${state.user.banned?'disabled':''}>${r.liked?'♥ 已喜爱':'♡ 喜爱这份创作'} · ${Number(r.favorite_count)||0}</button><button id="dislike-button" class="button full dislike-button${r.disliked?' disliked':''}" aria-pressed="${Boolean(r.disliked)}" ${state.user.banned?'disabled':''}>${r.disliked?'▼ 已差评':'▽ 给予差评'} · ${Number(r.dislike_count)||0}</button></div>`;
  }

  function resourceManagement(r,privateView) {
    if(!isManager()||state.user.banned)return '';
    let actions='';
    if(r.status==='published')actions+=`<button class="button small danger full" data-action="unpublish" data-resource="${esc(r.id)}" data-title="${esc(r.title)}">下架作品</button>`;
    if(r.status==='unpublished')actions+=`<button class="button small full" data-action="restore" data-resource="${esc(r.id)}" data-title="${esc(r.title)}">恢复上架</button>`;
    if(privateView&&r.latest_revision?.status==='pending')actions+=`<button class="button small primary full" data-action="approve" data-review="${esc(r.latest_revision.id)}" data-title="${esc(r.title)}">通过当前修订</button><button class="button small danger full" data-action="reject" data-review="${esc(r.latest_revision.id)}" data-title="${esc(r.title)}">驳回当前修订</button>`;
    if(!privateView)actions+=`<a class="button small full" href="${url('/mods/'+id(r.id)+'/')}?private=1">查看待审修订与历史</a>`;
    actions+=`<a class="text-link" href="${url('/manage/users/'+id(r.author.id)+'/')}">查看作者账户 →</a>`;
    return `<section class="side-panel detail-management"><h3>作品管理</h3><p class="field-hint">操作会记录在审核与管理日志中。</p><div class="actions">${actions}</div></section>`;
  }
  function searchForm(q,placeholder='搜索标题或介绍') {return `<form id="search-form" class="search-form" role="search"><label class="sr-only" for="search-q">搜索资源</label><input id="search-q" name="q" type="search" value="${esc(q)}" placeholder="${esc(placeholder)}" maxlength="200"><button type="submit" aria-label="搜索">${icons.search}</button></form>`;}
  function pagination(data,path,extra={}) {
    const current=Number(data.page)||1,pages=Number(data.pages)||1;if(pages<2)return '';
    const href=p=>{const q=new URLSearchParams(extra);q.set('page',p);return url(path)+'?'+q.toString();};
    const pagesToShow=[...new Set([1,current-1,current,current+1,pages].filter(n=>n>0&&n<=pages))].sort((a,b)=>a-b);
    let out=current>1?`<a class="button small" href="${esc(href(current-1))}" aria-label="上一页">‹</a>`:`<button class="button small" disabled aria-label="上一页">‹</button>`;
    let previous=0;for(const n of pagesToShow){if(previous&&n-previous>1)out+='<span>…</span>';out+=`<a class="button small${n===current?' current':''}" href="${esc(href(n))}" ${n===current?'aria-current="page"':''}>${n}</a>`;previous=n;}
    out+=current<pages?`<a class="button small" href="${esc(href(current+1))}" aria-label="下一页">›</a>`:`<button class="button small" disabled aria-label="下一页">›</button>`;
    return `<nav class="pagination" aria-label="资源分页">${out}</nav>`;
  }
  function catalogSidebar() {return `<aside class="sidebar catalog-sidebar" aria-label="分享指南"><section class="side-panel"><div class="tiny-kicker">A PLACE FOR YOUR IDEAS</div><h3>你的灵感，值得被看见。</h3><p>分享你的素材与预设，<br>让更多创作在这里相遇。</p><a class="button small full" href="${url('/upload/')}">分享一份创作 <span aria-hidden="true">↗</span></a></section><section class="side-panel"><h3>分享须知</h3><div class="limit-row"><span>单文件上限</span><strong>50 MB</strong></div><div class="limit-row"><span>每日上传次数</span><strong>5 次 / 账户</strong></div><div class="limit-row"><span>开放方式</span><strong>审核后发布</strong></div></section><section class="side-panel"><span class="tiny-kicker">CREATE AND SHARE</span><p>请注明适用版本、安装方法与原作者，分享拥有授权的内容。</p><p>下载前阅读资源介绍，安装前备份存档。</p></section></aside>`;}
  async function catalog() {
    const cat=page==='characters'?'characters':page==='presets'?'presets':params.get('category')||'';
    const q=params.get('q')||'',num=params.get('page')||'1';
    const query=new URLSearchParams({q,page:num});if(cat==='characters'||cat==='presets')query.set('category',cat);
    const data=await api('resources/?'+query);
    const home=page==='home';const title=cat==='characters'?'素材收藏':cat==='presets'?'预设收藏':'最新分享';
    const hero=home?`<section class="hero" aria-labelledby="hero-title"><div><span class="eyebrow">CHATARCHIVE / A PLACE FOR CREATORS</span><h1 id="hero-title">发现创作，<em>分享灵感。</em></h1><p>收藏一个角色，邂逅一种可能。<br>这里汇集素材与预设，也等待你的下一份创作。</p><div class="hero-actions"><a class="button primary" href="${url('/characters/')}">探索素材 <span aria-hidden="true">→</span></a><a class="button" href="${url('/presets/')}">发现预设 <span aria-hidden="true">↗</span></a></div></div><div class="hero-side"><p><strong>每一份分享，都带来新的可能。</strong><br>公益资源社区 · 投稿审核后发布<br>登录下载，欢迎分享创作。</p><a class="button small" href="${url('/upload/')}">分享你的灵感 <span aria-hidden="true">↗</span></a></div><svg class="hero-scene" viewBox="0 0 420 360" fill="none" aria-hidden="true"><circle cx="216" cy="184" r="118" stroke="#72cbed" stroke-width="1.5"/><circle cx="216" cy="184" r="97" stroke="#7cd4ee" stroke-width="9" opacity=".15"/><circle cx="216" cy="184" r="142" stroke="#7fcae7" stroke-dasharray="3 11" opacity=".4"/><path d="M77 78h108M315 263h71M66 270h39M305 90h46" stroke="#58b9e2" stroke-width="2"/><path d="m73 78 6-6m-6 6 6 6M348 90l-5-5m5 5-5 5" stroke="#58b9e2" stroke-width="2"/><g transform="rotate(-12 216 184)"><rect x="151" y="115" width="119" height="159" rx="9" fill="#b6e9fa" stroke="#64bbe2"/><rect x="169" y="98" width="119" height="159" rx="9" fill="#f6fcff" stroke="#61b5db" stroke-width="1.5"/><path d="M191 127h72M191 143h51M191 211h48M191 227h70" stroke="#86cde9" stroke-width="3" stroke-linecap="round"/><rect x="191" y="158" width="42" height="38" rx="4" fill="#c7edfc"/><path d="m199 183 9-12 9 5 8-8" stroke="#61b9df" stroke-width="2"/><path d="M247 160v36m11-27v27m11-20v20" stroke="#9bd7ef" stroke-width="5" stroke-linecap="round"/></g><path d="M283 50h49l-7 10h-49Z" fill="#ffde7e"/><path d="M58 224h29l-6 8H52Z" fill="#ffde7e"/><circle cx="113" cy="121" r="7" fill="#ffa69e"/><circle cx="327" cy="230" r="5" fill="#ffa69e"/><path d="m299 300 6 6-6 6-6-6Z" fill="#5cc4e9"/><path d="M63 169c0-8 7-14 15-12 5-17 28-20 39-7 14-2 22 7 23 19Z" fill="#ffffff" opacity=".7"/><path d="M299 141c0-6 5-11 12-10 6-11 21-12 28-3 10-1 16 5 17 13Z" fill="#ffffff" opacity=".65"/></svg></section>`:heading(cat==='presets'?'预设区':'素材区',cat==='presets'?'让文字与参数，为下一段创作开场。':'在不同的故事中，遇见新的角色。','EXPLORE THE COLLECTION');
    const currentPath=home?'/':page==='characters'?'/characters/':'/presets/';
    const tabLink=c=>url('/')+(c?'?category='+c:'');
    mount(`${hero}<div class="catalog-layout"><section aria-label="资源列表"><div class="section-heading"><div><h2>${esc(title)}</h2><p>${q?`搜索「${esc(q)}」 · `:''}共 ${Number(data.total)||list(data).length} 份已发布资源</p></div><span class="sort-label">最新发布 ↓</span></div><div class="catalog-toolbar"><nav class="tabs" aria-label="资源分类"><a class="${!cat?'active':''}" href="${tabLink('')}">全部</a><a class="${cat==='characters'?'active':''}" href="${tabLink('characters')}">素材</a><a class="${cat==='presets'?'active':''}" href="${tabLink('presets')}">预设</a></nav>${searchForm(q)}</div>${list(data).length?`<div class="resource-grid">${list(data).map(resourceCard).join('')}</div>`:empty(q?'没有找到相关资源':'第一份分享，等待发布',q?'试试其他关键词，或浏览全部资源。':'这里将展示审核通过的素材和预设，欢迎分享你的创作。',`<a class="button" href="${url(q?currentPath:'/upload/')}">${q?'清除搜索':'上传资源'} <span aria-hidden="true">→</span></a>`)}${pagination(data,currentPath,{...(cat?{category:cat}:{}),...(q?{q}:{})})}</section>${catalogSidebar()}</div>`);
    document.getElementById('search-form').addEventListener('submit',e=>{e.preventDefault();const search=new URLSearchParams();const value=e.target.elements.q.value.trim();if(value)search.set('q',value);if(home&&cat)search.set('category',cat);location.assign(url(currentPath)+(search.size?'?'+search:''));});
  }
  function authPage() {
    const register=page==='register',reset=page==='reset';
    const title=register?'创建账号':reset?'重设密码':'欢迎归来';
    const intro=register?'邮箱验证后，即可加入创作社区。':reset?'验证账号邮箱，为你的账号设置新密码。':'登录，继续发现与分享。';
    let fields=field('email','邮箱','email','you@example.com','required maxlength="254" autocomplete="email"');
    if(register)fields+=field('display_name','昵称','text','大家会在资源页看到这个名字','required maxlength="40" autocomplete="nickname"');
    if(register||reset)fields+=`<div class="field"><label for="code">邮箱验证码</label><div class="input-action"><input id="code" name="code" placeholder="填写邮件中的验证码" required maxlength="12" autocomplete="one-time-code" inputmode="numeric"><button class="button" id="send-code" type="button">发送验证码</button></div><p class="field-hint" id="code-hint">验证码可能进入垃圾邮件，请注意查收。</p><p class="field-error" id="error-code" hidden></p></div>`;
    fields+=field('password',reset?'新密码':'密码','password',register||reset?'至少 10 位，请使用不易猜测的密码':'输入你的密码',`required ${register||reset?'minlength="10"':''} maxlength="128" autocomplete="${register||reset?'new-password':'current-password'}"`);
    if(register||reset)fields+=field('confirm','确认密码','password','再次输入密码','required maxlength="128" autocomplete="new-password"');
    mount(`<div class="auth-layout"><section class="auth-story"><span class="eyebrow">WELCOME TO CHATARCHIVE</span><h1>让灵感相遇，<br><span>让创作被看见。</span></h1><p>与同好分享素材和预设，<br>为下一段故事，收藏一份新的可能。</p><div class="auth-seal" aria-hidden="true">◇<small>CHATARCHIVE / SHARE YOUR CREATIVITY</small></div></section><section class="panel form-panel" aria-labelledby="auth-title"><h2 id="auth-title">${title}</h2><p class="form-intro">${intro}</p><form id="auth-form"><div class="form-error" role="alert" hidden></div><div class="form-success" role="status" hidden></div>${fields}<button class="button primary full" type="submit">${register?'验证邮箱并注册':reset?'更新密码':'登录账号'} <span aria-hidden="true">→</span></button><div class="form-links">${register?`<span>已有账号？<a href="${url('/login/')}">去登录</a></span>`:reset?`<a href="${url('/login/')}">返回登录</a>`:`<span>还没有账号？<a href="${url('/register/')}">创建账号</a></span><a href="${url('/reset-password/')}">忘记密码</a>`}</div><p class="form-footnote">${register?'每个邮箱仅可注册一个账号。请分享拥有授权的作品，共同维护社区。':'ChatArchive 模组分享站 使用独立账号，请使用本社区注册的邮箱登录。'}</p></form></section></div>`);
    const form=document.getElementById('auth-form');
    const verification=window.ChatArchiveHumanVerification.mount(form,register?'register':reset?'reset_password':'login');
    if(register||reset){
      const send=document.getElementById('send-code');let cooldownUntil=0;
      send.addEventListener('click',async()=>{clearErrors(form);const email=form.elements.email;if(!email.reportValidity())return;send.disabled=true;send.textContent='正在发送…';try{const result=await api('auth/send-code/',{method:'POST',body:{email:email.value.trim(),purpose:register?'register':'reset',turnstile_token:verification.consume()}});const seconds=Math.min(3600,Math.max(1,Number(result?.retry_after||result?.cooldown)||60));cooldownUntil=Date.now()+seconds*1000;document.getElementById('code-hint').textContent='验证码请求已提交，请查收邮箱；若未收到，请查看垃圾邮件。';toast('验证码请求已提交，请查收邮箱。');const tick=()=>{const remain=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000));send.textContent=remain?`${remain} 秒后重发`:'重新发送';send.disabled=remain>0;if(!remain)clearInterval(timer);};const timer=setInterval(tick,1000);tick();}catch(err){send.disabled=false;send.textContent='发送验证码';formError(err,form);}finally{verification.reset();}});
      form.addEventListener('submit',()=>{if(cooldownUntil>Date.now())send.dataset.wasDisabled='true';});
    }
    form.addEventListener('submit',async e=>{e.preventDefault();clearErrors(form);if(!form.reportValidity())return;const body=Object.fromEntries(new FormData(form));if((register||reset)&&body.password!==body.confirm){formError({message:'两次输入的密码不一致。',fields:{confirm:'请再次确认密码。'}},form);return;}busy(form,true);try{body.turnstile_token=verification.consume();await api(register?'auth/register/':reset?'auth/reset-password/':'auth/login/',{method:'POST',body});if(reset){busy(form,false);form.reset();form.querySelector('.form-success').textContent='密码已更新，请使用新密码登录。';form.querySelector('.form-success').hidden=false;return;}let next=params.get('next')||url('/');const safe=next.startsWith('/')&&!next.startsWith('//')&&!next.includes('\\')&&(!base||next===base||next.startsWith(base+'/'));location.assign(safe?next:url('/'));}catch(err){busy(form,false);formError(err,form);}finally{verification.reset();}});
  }
  function quotaPanel() {const q=state.quota;return `<section class="side-panel"><h3>今日剩余上传次数</h3><div class="quota-number">${Number(q.remaining)}<span>/ ${Number(q.limit)}</span></div><div class="quota-dots" aria-hidden="true">${Array.from({length:Number(q.limit)||5},(_,i)=>`<i class="${i<Number(q.used)?'used':''}"></i>`).join('')}</div><p>北京时间每日 00:00 重置。<br>素材与预设共用额度。</p></section>`;}
  async function uploadPage() {
    if(!requireUser())return;
    if(state.user.banned){mount(heading('上传资源','为下一位创作者，分享一份灵感。')+empty('当前账号无法投稿',state.user.ban_reason||'账号已被封禁，请联系管理员。'));return;}
    const edit=params.get('edit');let r=null;
    if(edit){r=await api('resources/'+id(edit)+'/?private=1');if(r.author?.id!==state.user.id){mount(empty('这份投稿不属于你','请在“我的投稿”中选择需要修改的作品。',`<a class="button" href="${url('/my-uploads/')}">我的投稿</a>`));return;}}
    const latest=r?.revisions?.find(v=>v.id===r.latest_revision?.id)||r;
    const cat=r?.category||params.get('category')||'characters';
    mount(`${heading(edit?'修改投稿':'分享你的创作',edit?'修改内容将重新审核；已发布版本在审核期间继续展示。':'上传素材或预设，审核通过后即可与大家相遇。','SHARE YOUR NEXT CREATION')}<div class="upload-layout"><section class="panel upload-panel"><form id="upload-form"><div class="form-error" role="alert" hidden></div>${edit?notice('修改文字或删除例图不消耗上传次数；替换资源文件、上传新例图计入今日额度。同次提交只计一次。'):''}${edit?`<input name="category" type="hidden" value="${esc(cat)}">`:`<div class="category-choice" role="group" aria-label="选择资源分类"><label><input type="radio" name="category" value="characters" ${cat!=='presets'?'checked':''}>素材区 <span class="faint">/ 压缩包</span></label><label><input type="radio" name="category" value="presets" ${cat==='presets'?'checked':''}>预设区 <span class="faint">/ 文本</span></label></div>`}${field('title','资源标题','text','给你的创作一个清晰的名字','required maxlength="120"') }<div class="field"><label for="description">资源介绍 <span>说明适用版本、安装方法与注意事项</span></label><textarea name="description" id="description" rows="7" required maxlength="20000" placeholder="介绍你的创作，让大家知道如何使用。"></textarea><p class="field-error" id="error-description" hidden></p><p class="field-hint">以纯文本展示，支持换行。请注明原作者与授权信息。</p></div><div class="field"><label for="file">${edit?'替换文件 <span>可选，不选择则保留现有文件</span>':'资源文件'}</label><div class="file-drop" id="file-drop">${icons.upload}<strong id="file-label">${edit?'点击或拖拽，选择替换文件':'点击或拖拽，选择你的文件'}</strong><small id="file-hint"></small><input name="file" id="file" type="file" ${edit?'':'required'} aria-describedby="file-hint error-file"></div><p class="field-error" id="error-file" hidden></p>${edit?`<p class="field-hint">现有文件：${esc(latest?.file?.name||r.file?.name)} · ${size(latest?.file?.size||r.file?.size)}</p>`:''}</div><div class="field preview-field" id="preview-field"><label for="preview">资源例图 <span>可选，一张图片</span></label><div class="file-drop preview-drop">${icons.upload}<strong id="preview-label">选择例图，让大家看见资源效果</strong><small>PNG / JPG / WebP · 最大 2 MB（2,000,000 字节）</small><input name="preview" id="preview" type="file" accept=".png,.jpg,.jpeg,.webp" aria-describedby="preview-hint error-preview"></div><p class="field-hint" id="preview-hint">例图随投稿审核后展示。请上传静态图片；新增或替换例图计入每日上传次数。</p><p class="field-error" id="error-preview" hidden></p><div class="selected-preview" id="selected-preview" hidden></div><button class="text-link" type="button" id="clear-preview" hidden>清除选中的图片</button>${latest?.preview?'<label class="preview-remove"><input type="checkbox" name="remove_preview" id="remove-preview" value="1">移除现有例图（审核通过后生效）</label>':''}</div><div class="progress-wrap" id="progress-wrap" role="status" hidden><progress id="upload-progress" value="0" max="100" aria-label="文件上传进度"></progress><div class="progress-label"><span id="progress-text">正在上传文件…</span><span id="progress-percent">0%</span></div></div><div class="upload-actions"><button class="button primary" type="submit">${edit?'提交修改，重新审核':'提交审核'} <span aria-hidden="true">↗</span></button><button id="cancel-upload" class="button" type="button" hidden>取消上传</button><a class="text-link" href="${url('/my-uploads/')}">查看我的投稿</a></div><p class="form-footnote">资源文件与例图一起提交只计一次。失败或取消不扣次数；审核驳回不会返还次数。</p></form></section><aside class="sidebar">${quotaPanel()}<section class="side-panel"><h3>支持的文件</h3><p><span class="gold">素材</span><br>ZIP / 7Z / RAR / CAPK</p><p><span class="gold">预设</span><br>TXT / JSON / JSONL / YAML / YML / TOML / INI / CFG / XML / MD / CSV</p><p>每个文件最多 50 MB（50,000,000 字节）。改后缀伪装的文件无法通过校验。</p><p>两区例图：一张 PNG / JPG / WebP，最大 2 MB。系统会优化展示尺寸并移除图片元数据。</p></section><section class="side-panel"><h3>分享之后</h3><p>投稿进入审核队列，审核结果与原因可在“我的投稿”查看。</p><p>已发布资源修改后，新的内容通过审核才会替换。</p></section></aside></div>`);
    const form=document.getElementById('upload-form'),file=document.getElementById('file'),drop=document.getElementById('file-drop');let xhr=null;
    const picture=document.getElementById('preview'),pictureBox=document.getElementById('selected-preview'),clearPicture=document.getElementById('clear-preview'),removePicture=document.getElementById('remove-preview');
    const currentPicture=latest?.preview||r?.preview;
    function showPicture(){
      const selected=picture.files[0];clearPicture.hidden=!selected;
      document.getElementById('preview-label').textContent=selected?`${selected.name} · ${size(selected.size)}`:'选择例图，让大家看见资源效果';
      pictureBox.replaceChildren();pictureBox.hidden=true;
      if(selected){
        if(selected.size>2000000||!['png','jpg','jpeg','webp'].includes(selected.name.split('.').pop().toLowerCase())){formError({message:'例图须为 2 MB 以内的 PNG、JPG 或 WebP。',fields:{preview:'请重新选择符合要求的图片。'}},form);return;}
        const reader=new FileReader();reader.addEventListener('load',()=>{if(picture.files[0]!==selected)return;const image=new Image();image.alt='所选例图预览';image.src=reader.result;pictureBox.append(image);pictureBox.hidden=false;});reader.readAsDataURL(selected);
      }else if(currentPicture&&!removePicture?.checked){
        const image=new Image();image.alt='现有例图';image.src=currentPicture.url;pictureBox.append(image);pictureBox.hidden=false;
      }
    }
    picture.addEventListener('change',()=>{clearErrors(form);if(picture.files[0]&&removePicture)removePicture.checked=false;showPicture();});
    clearPicture.addEventListener('click',()=>{picture.value='';clearErrors(form);showPicture();});
    removePicture?.addEventListener('change',()=>{if(removePicture.checked)picture.value='';showPicture();});
    if(edit){form.elements.title.value=latest?.title||r.title;form.elements.description.value=latest?.description||r.description;}
    const extensions={characters:['zip','7z','rar','capk'],presets:['txt','json','jsonl','yaml','yml','toml','ini','cfg','xml','md','csv']};
    const chosen=()=>form.elements.category.value;
    function setFormats(){const allowed=extensions[chosen()]||extensions.characters;file.accept=allowed.map(e=>'.'+e).join(',');document.getElementById('file-hint').textContent=allowed.map(e=>e.toUpperCase()).join(' / ')+' · 最多 50 MB';showPicture();}
    function selectedFile(){const f=file.files[0];document.getElementById('file-label').textContent=f?`${f.name} · ${size(f.size)}`:edit?'点击或拖拽，选择替换文件':'点击或拖拽，选择你的文件';}
    setFormats();form.querySelectorAll('[name=category]').forEach(input=>input.addEventListener('change',()=>{setFormats();file.value='';selectedFile();}));file.addEventListener('change',selectedFile);
    drop.addEventListener('dragover',e=>{e.preventDefault();if(!file.disabled)drop.classList.add('dragging');});drop.addEventListener('dragleave',()=>drop.classList.remove('dragging'));drop.addEventListener('drop',e=>{e.preventDefault();drop.classList.remove('dragging');if(!file.disabled&&e.dataTransfer.files.length===1){file.files=e.dataTransfer.files;selectedFile();}});
    document.getElementById('cancel-upload').addEventListener('click',()=>xhr?.abort());
    form.addEventListener('submit',e=>{
      e.preventDefault();clearErrors(form);if(!form.reportValidity())return;const f=file.files[0];
      if(f&&(f.size>Number(state.limits.max_file_bytes)||f.size>50000000)){formError({message:'文件不能超过 50 MB（50,000,000 字节）。',fields:{file:'请选择符合大小限制的文件。'}},form);return;}
      if(f&&!extensions[chosen()].includes(f.name.split('.').pop().toLowerCase())){formError({message:'所选文件格式不适用于当前分类。',fields:{file:'请选择上方列出的支持格式。'}},form);return;}
      const p=picture.files[0];
      if(p&&(p.size>Math.min(Number(state.limits.max_preview_bytes)||2000000,2000000)||!['png','jpg','jpeg','webp'].includes(p.name.split('.').pop().toLowerCase()))){formError({message:'例图须为 2 MB 以内的 PNG、JPG 或 WebP。',fields:{preview:'请重新选择符合要求的图片。'}},form);return;}
      if((f||p)&&Number(state.quota.remaining)<=0){formError({message:'今日 5 次上传额度已用完，北京时间 00:00 后重置。'},form);return;}
      const body=new FormData(form);if(!p)body.delete('preview');if(edit){body.delete('category');if(!f)body.delete('file');}
      busy(form,true,edit?'正在提交修改…':'正在上传…');const progress=document.getElementById('progress-wrap'),cancel=document.getElementById('cancel-upload');progress.hidden=false;cancel.hidden=false;document.getElementById('upload-progress').value=0;document.getElementById('progress-percent').textContent='0%';document.getElementById('progress-text').textContent=(f||p)?'正在上传文件…':'正在提交修改…';
      xhr=new XMLHttpRequest();xhr.open('POST',url('/api/'+(edit?'resources/'+id(edit)+'/revisions/':'uploads/')));xhr.withCredentials=true;xhr.setRequestHeader('X-CSRFToken',csrf());xhr.setRequestHeader('Accept','application/json');
      xhr.upload.addEventListener('progress',event=>{if(event.lengthComputable){const p=Math.round(event.loaded/event.total*100);document.getElementById('upload-progress').value=p;document.getElementById('progress-percent').textContent=p+'%';document.getElementById('progress-text').textContent=p===100?'文件已发送，服务器正在校验…':'正在上传文件…';}});
      const restore=()=>{busy(form,false);cancel.hidden=true;xhr=null;};
      xhr.addEventListener('load',()=>{let payload;try{payload=JSON.parse(xhr.responseText);}catch{payload={ok:false,error:{message:xhr.status===413?'文件超出服务器允许的大小。':'服务器暂时未能处理上传，请重试。'}};}const status=xhr.status;restore();if(status>=200&&status<300&&payload.ok){document.getElementById('progress-text').textContent='提交成功，已进入审核队列。';document.getElementById('progress-percent').textContent='100%';document.getElementById('upload-progress').value=100;location.assign(url('/my-uploads/')+'?submitted=1');}else{progress.hidden=true;formError({message:payload.error?.message||'上传未完成，请重试。',fields:payload.error?.fields},form);}});
      xhr.addEventListener('error',()=>{restore();progress.hidden=true;formError({message:'网络连接中断，上传未完成。请重试。'},form);});
      xhr.addEventListener('abort',()=>{restore();progress.hidden=true;toast('已取消发送。请在“我的投稿”中核对是否已提交成功。');});xhr.send(body);
    });
  }
  function visibleRevision(r) {return r.published_revision_id||r.revision_id||r.file?.revision_id||r.file?.id;}
  function downloadLink(revision,label='下载文件',classes='button primary full',review=false) {return `<a class="${classes}" href="${url((review?'/review-download/':'/download/')+id(revision)+'/')}" data-download-revision="${id(revision)}" data-download-review="${review?'1':'0'}">${icons.download}${esc(label)}</a>`;}
  content.addEventListener('click',async event=>{
    const link=event.target.closest('a[data-download-revision]');
    if(!link||event.button>0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    event.preventDefault();if(link.dataset.downloadBusy==='1')return;
    link.dataset.downloadBusy='1';link.setAttribute('aria-disabled','true');
    try{const result=await api('downloads/'+id(link.dataset.downloadRevision)+'/ticket/',{method:'POST',body:{review:link.dataset.downloadReview==='1'}});location.assign(result.url);}
    catch(error){toast(error.message,true);}
    finally{delete link.dataset.downloadBusy;link.removeAttribute('aria-disabled');}
  });
  async function detailPage() {
    const privateView=params.get('private')==='1';const r=await api('resources/'+id(objectId)+'/'+(privateView?'?private=1':''));const f=r.file||{};
    const revision=privateView?(f.revision_id||f.id||r.latest_revision?.id):visibleRevision(r);
    let download='';
    if(!state.user)download=`<a class="button primary full" href="${url('/login/')}?next=${encodeURIComponent(location.pathname+location.search)}">登录后下载 <span aria-hidden="true">→</span></a>`;
    else if(state.user.banned)download='<button class="button full" disabled>账号已封禁，无法下载</button>';
    else if(revision)download=downloadLink(revision,privateView?'下载审阅文件':'下载文件','button primary full',privateView);
    else download='<button class="button full" disabled>暂无可下载文件</button>';
    mount(`<nav class="breadcrumb" aria-label="当前位置"><a href="${url('/')}">首页</a><span aria-hidden="true">/</span><a href="${url(privateView?'/my-uploads/':r.category==='presets'?'/presets/':'/characters/')}">${privateView?'我的投稿':category(r.category)+'区'}</a><span aria-hidden="true">/</span><span>资源详情</span></nav><div class="detail-layout"><section class="panel"><div class="card-top">${tag(r.category)}${privateView?badge(r.status):'<span class="tiny-kicker">COMMUNITY COLLECTION</span>'}</div><h1 class="detail-title">${esc(r.title)}</h1><div class="detail-byline"><span>作者 · ${esc(r.author?.name||'社区创作者')}</span><span>${privateView?'提交':'发布'}于 ${date(r.published_at||r.created_at)}</span></div>${privateView&&r.latest_revision?.status==='pending'?notice('最新修改正在审核中。已发布的资源继续展示原审核版本。'):''}${example(r)}<h2 class="prose-title">资源介绍</h2><div class="prose">${esc(r.description)}</div>${privateView&&Array.isArray(r.revisions)?`<section class="revision-list"><h2 class="prose-title">修订与审核记录</h2>${r.revisions.map(v=>`<div class="revision-row"><div class="revision-top"><span>${badge(v.status)} <span class="faint">${date(v.created_at,true)}</span></span>${!state.user?.banned&&v.file?downloadLink(v.id,'下载此版本','button small',true):''}</div><p>${esc(v.title||r.title)}${v.file?` · ${esc(v.file.name)} · ${size(v.file.size)}`:''}</p>${example(v)}${v.reason?`<p>审核原因：${esc(v.reason)}</p>`:''}${v.description&&v.description!==r.description?`<details><summary class="faint revision-expand">查看此版本介绍</summary><div class="prose revision-prose">${esc(v.description)}</div></details>`:''}</div>`).join('')}</section>`:''}</section><aside class="sidebar"><section class="side-panel"><div class="file-glyph">${icons.file}<span>${esc((f.extension||'FILE').toUpperCase())} FILE</span></div><h3 class="file-name">${esc(f.name||'资源文件')}</h3><dl class="file-facts"><div><dt>文件大小</dt><dd>${size(f.size)}</dd></div><div><dt>文件格式</dt><dd>${esc((f.extension||'—').toUpperCase())}</dd></div><div><dt>资源分类</dt><dd>${category(r.category)}</dd></div></dl>${download}${favoriteControl(r)}<div id="detail-stats">${interactionStats(r)}</div><p class="field-hint">安装前请阅读介绍，备份现有文件与存档。</p>${f.sha256?`<details class="hash"><summary>查看 SHA-256 校验值</summary>${esc(f.sha256)}</details>`:''}</section>${resourceManagement(r,privateView)}${privateView&&r.author?.id===state.user?.id&&!state.user?.banned?`<section class="side-panel"><h3>完善这份创作</h3><p>修改内容将重新进入审核。</p><a class="button small full" href="${url('/upload/')}?edit=${id(r.id)}">修改并重新提交</a></section>`:''}</aside></div>`);
    const heart=document.getElementById('favorite-button'),negative=document.getElementById('dislike-button');
    function refreshReactions() {
      heart.classList.toggle('liked',r.liked);heart.setAttribute('aria-pressed',String(r.liked));heart.textContent=(r.liked?'♥ 已喜爱':'♡ 喜爱这份创作')+' · '+r.favorite_count;
      negative.classList.toggle('disliked',r.disliked);negative.setAttribute('aria-pressed',String(r.disliked));negative.textContent=(r.disliked?'▼ 已差评':'▽ 给予差评')+' · '+r.dislike_count;
      document.getElementById('detail-stats').innerHTML=interactionStats(r);
    }
    for(const [button,endpoint,field] of [[heart,'favorite','liked'],[negative,'dislike','disliked']]) {
      button?.addEventListener('click',async()=>{
        heart.disabled=negative.disabled=true;
        try {const value=await api('resources/'+id(r.id)+'/'+endpoint+'/',{method:'POST',body:{[field]:!r[field]}});Object.assign(r,value);refreshReactions();}
        catch(e){toast(e.message,true);}finally{heart.disabled=negative.disabled=false;}
      });
    }
    if(isManager()&&!state.user.banned)setupActions(async()=>{params.set('private','1');history.replaceState(null,'',url('/mods/'+id(r.id)+'/')+'?private=1');await detailPage();});
  }
  function submission(r,manage=false) {
    const latest=r.latest_revision;const f=r.file||{};const feedback=(r.status==='unpublished'?r.unpublish_reason:'')||latest?.reason||r.reason||r.unpublish_reason||'';
    let actions=`<a class="button small" href="${url('/mods/'+id(r.id)+'/')}?private=1">查看详情</a>`;
    if(manage){if(r.status==='published')actions+=`<button class="button small danger" data-action="unpublish" data-resource="${esc(r.id)}" data-title="${esc(r.title)}">下架资源</button>`;else if(r.status==='unpublished')actions+=`<button class="button small" data-action="restore" data-resource="${esc(r.id)}" data-title="${esc(r.title)}">重新上架</button>`;}
    else if(!state.user?.banned)actions+=`<a class="button small" href="${url('/upload/')}?edit=${id(r.id)}">修改投稿</a>`;
    const displayStatus=['published','unpublished'].includes(r.status)?r.status:latest?.status||r.status;
    return `<article class="submission"><div class="submission-head"><div><h3>${esc(r.title)}</h3><div class="submission-meta"><span>${category(r.category)}区</span><span>${esc(f.name||'等待文件')}</span><span>${size(f.size)}</span><span>${date(r.created_at,true)}</span>${manage?`<span>作者：${esc(r.author?.name||'—')}</span>`:''}</div></div>${badge(displayStatus)}</div><div class="submission-foot"><p class="submission-note">${feedback?`反馈：${esc(feedback)}`:latest?.status==='pending'?'最新修订正在等待审核。':r.status==='published'?'审核通过，大家可以浏览并下载。':r.status==='unpublished'?'资源已下架，再次上架须由管理员操作。':'审核进度与反馈会显示在这里。'}${latest&&['published','unpublished'].includes(r.status)&&latest.status==='pending'?` ${badge(latest.status)}`:''}</p><div class="actions">${actions}</div></div></article>`;
  }
  async function minePage() {
    if(!requireUser())return;const data=await api('my-resources/?page='+id(params.get('page')||'1'));
    mount(`${heading('我的投稿','在这里查看审核进度，完善每一份创作。','YOUR CREATIVE FOOTPRINT',state.user.banned?'':`<a class="button primary small" href="${url('/upload/')}">上传资源 <span aria-hidden="true">↗</span></a>`)}${params.get('submitted')?notice('投稿已提交，正在等待审核。你可以在这里查看后续进度。'):''}${notice(`今日已成功上传 <strong>${Number(state.quota.used)} / ${Number(state.quota.limit)}</strong> 次，还可上传 <strong>${Number(state.quota.remaining)}</strong> 次。北京时间 00:00 重置；仅修改文字或删除例图不消耗上传次数；新增或替换例图计一次。`)}${list(data).length?`<section class="submission-list" aria-label="我的投稿列表">${list(data).map(r=>submission(r)).join('')}</section>`:empty('你的第一份创作，即将在这里留下足迹','分享一份素材或预设，审核进度会显示在这里。',state.user.banned?'':`<a class="button primary" href="${url('/upload/')}">分享创作 <span aria-hidden="true">↗</span></a>`)}${pagination(data,'/my-uploads/')}`);
  }
  const actionLabels={approve:'通过审核',reject:'驳回投稿',unpublish:'下架资源',restore:'重新上架',ban:'封禁账号',unban:'解除封禁',promote:'任命管理员',demote:'罢免管理员'};
  const actionCopy={approve:'此版本将对所有访客发布，登录用户可下载文件。',reject:'请填写具体原因，帮助作者修改后再次提交。',unpublish:'资源将立即从公开列表移除，普通用户无法继续下载。',restore:'已审核版本将重新展示，并恢复登录下载。',ban:'该账号仍可登录查看提示，但将无法上传、修改或下载。',unban:'该账号将恢复上传、修改与下载权限。',promote:'该账号将获得审核、下架和管理普通账户的权限。',demote:'该账号的管理员权限将在下一次请求时失效。'};
  function setupActions(refresh) {
    content.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',()=>{
      const action=button.dataset.action;const endpoint=button.dataset.review?'manage/reviews/'+id(button.dataset.review)+'/':button.dataset.resource?'manage/resources/'+id(button.dataset.resource)+'/':'manage/users/'+id(button.dataset.user)+'/';
      const dialog=document.getElementById('action-dialog'),form=document.getElementById('dialog-form'),reason=document.getElementById('action-reason'),error=document.getElementById('dialog-error');
      document.getElementById('dialog-title').textContent=actionLabels[action];document.getElementById('dialog-copy').textContent=(button.dataset.title?`「${button.dataset.title}」 `:'')+actionCopy[action];document.getElementById('dialog-submit').textContent=actionLabels[action];reason.value='';reason.required=action!=='approve';document.getElementById('reason-required').textContent=reason.required?'（必填）':'（可选）';error.hidden=true;dialog.showModal();
      form.onsubmit=async e=>{e.preventDefault();error.hidden=true;if(!form.reportValidity())return;if(reason.required&&!reason.value.trim()){error.textContent='请填写操作原因。';error.hidden=false;reason.focus();return;}busy(form,true,'正在处理…');try{await api(endpoint,{method:'POST',body:{action,reason:reason.value.trim()}});busy(form,false);dialog.close();toast(actionLabels[action]+'成功。');await loadMe();await refresh();}catch(err){busy(form,false);error.textContent=err.message;error.hidden=false;}};
    }));
  }
  function manageNav(tab) {return `<nav class="manage-nav" aria-label="管理分类"><div class="tabs">${[['reviews','投稿审核'],['resources','资源管理'],['users','账户管理'],['audit','操作记录']].map(([key,label])=>`<a class="${tab===key?'active':''}" href="${url('/manage/')}?tab=${key}">${label}</a>`).join('')}</div></nav>`;}
  function review(r) {return `<article class="submission"><div class="submission-head"><div><h3>${esc(r.title)}</h3><div class="submission-meta"><span>${category(r.category)}区</span><span>作者：${esc(r.author?.name)}</span><span>${esc(r.author?.email||'')}</span><span>${date(r.created_at,true)}</span></div></div>${badge('pending')}</div>${example(r)}<div class="review-description">${esc(r.description)}</div><div class="submission-foot"><p class="submission-note">${esc(r.file?.name)} · ${size(r.file?.size)} · ${esc((r.file?.extension||'').toUpperCase())}</p><div class="actions">${state.user?.banned?'':downloadLink(r.id,'审阅文件','button small',true)}<a class="button small" href="${url('/mods/'+id(r.resource_id)+'/')}?private=1">修订记录</a><button class="button small danger" data-action="reject" data-review="${esc(r.id)}" data-title="${esc(r.title)}">驳回</button><button class="button small primary" data-action="approve" data-review="${esc(r.id)}" data-title="${esc(r.title)}">通过审核</button></div></div></article>`;}
  async function managePage() {
    if(!requireUser(true))return;let tab=params.get('tab')||'reviews';if(!['reviews','resources','users','audit'].includes(tab))tab='reviews';
    const q=params.get('q')||'';const query=new URLSearchParams({q,page:params.get('page')||'1'});
    const data=await api('manage/'+tab+'/?'+query);let body='';
    if(tab==='reviews')body=`<div class="manage-topbar"><span>待审核投稿 · ${list(data).length} 份</span><button class="button small" id="refresh-manage">刷新队列</button></div>${list(data).length?`<div class="review-list">${list(data).map(review).join('')}</div>`:empty('审核队列已清空','新的投稿会在这里出现。')}`;
    else if(tab==='resources')body=`<div class="manage-topbar"><span>全部资源 · ${Number(data.total)||list(data).length} 份</span>${searchForm(q)}</div>${list(data).length?`<div class="submission-list">${list(data).map(r=>submission(r,true)).join('')}</div>`:empty('暂无相关资源','调整搜索关键词后重试。')}${pagination(data,'/manage/',{tab,q})}`;
    else if(tab==='users')body=`<div class="manage-topbar"><span>账户 · ${Number(data.total)||list(data).length} 位</span>${searchForm(q,'搜索邮箱或昵称')}</div>${list(data).length?`<div class="table-wrap"><table><thead><tr><th>账户</th><th>角色</th><th>状态</th><th>投稿</th><th>注册时间</th><th>操作</th></tr></thead><tbody>${list(data).map(u=>`<tr><td>${esc(u.display_label||u.display_name)}<br><span class="muted">${esc(u.email)}</span></td><td><span class="role-label">${esc(roleNames[u.role]||u.role)}</span></td><td>${u.banned?badge('banned'):'正常'}</td><td>${Number(u.upload_count)||0}</td><td>${date(u.date_joined)}</td><td><a class="text-link" href="${url('/manage/users/'+id(u.id)+'/')}">查看账户 →</a></td></tr>`).join('')}</tbody></table></div>`:empty('没有找到相关账户','试试其他邮箱或昵称。')}${pagination(data,'/manage/',{tab,q})}`;
    else {const auditLabel={...actionLabels,login:'登录',upload:'提交文件',register:'注册',revision:'提交修订'};const label=value=>typeof value==='object'&&value?value.display_label||value.display_name||value.name||value.email||value.id:typeof value==='string'?value:String(value??'—');body=list(data).length?`<div class="table-wrap"><table><thead><tr><th>操作时间</th><th>操作者</th><th>动作</th><th>操作对象</th><th>原因</th></tr></thead><tbody>${list(data).map(a=>`<tr><td>${date(a.created_at,true)}</td><td>${esc(label(a.actor))}</td><td class="audit-action">${esc(auditLabel[a.action]||a.action)}</td><td>${esc(label(a.target))}</td><td>${esc(a.reason||'—')}</td></tr>`).join('')}</tbody></table></div>`:empty('暂无操作记录','审核、下架、封禁与角色变更都会留存记录。');}
    mount(`${heading('管理中心','认真对待每一份分享，也守护每一位创作者。','COMMUNITY CARE',`<span class="tag">${esc(roleNames[state.user.role])}</span>`)}${manageNav(tab)}${body}`);
    const refresh=document.getElementById('refresh-manage');if(refresh)refresh.addEventListener('click',()=>{refresh.disabled=true;managePage().catch(e=>{refresh.disabled=false;toast(e.message,true);});});
    document.getElementById('search-form')?.addEventListener('submit',e=>{e.preventDefault();const search=new URLSearchParams({tab});const value=e.target.elements.q.value.trim();if(value)search.set('q',value);location.assign(url('/manage/')+'?'+search);});setupActions(managePage);
  }
  async function userPage() {
    if(!requireUser(true))return;const data=await api('manage/users/'+id(objectId)+'/?page='+id(params.get('page')||'1'));const u=data.user;let actions='';
    const mayBan=u.role!=='owner'&&(u.role==='user'||state.user.role==='owner');
    if(mayBan)actions+=`<button class="button small${u.banned?'':' danger'}" data-action="${u.banned?'unban':'ban'}" data-user="${esc(u.id)}" data-title="${esc(u.display_label||u.display_name||u.email)}">${u.banned?'解除封禁':'封禁账号'}</button>`;
    if(state.user.role==='owner'&&u.role!=='owner')actions+=`<button class="button small" data-action="${u.role==='admin'?'demote':'promote'}" data-user="${esc(u.id)}" data-title="${esc(u.display_label||u.display_name||u.email)}">${u.role==='admin'?'罢免管理员':'任命管理员'}</button>`;
    mount(`<nav class="breadcrumb" aria-label="当前位置"><a href="${url('/manage/')}?tab=users">账户管理</a><span aria-hidden="true">/</span><span>账户详情</span></nav>${heading('账户详情','账户状态与该账号的全部投稿。','COMMUNITY ACCOUNTS')}<section class="panel user-profile"><div class="user-profile-info"><span class="avatar">${esc((u.display_name||u.email||'创')[0])}</span><div><h2>${esc(u.display_label||u.display_name||'社区用户')}</h2><p>${esc(u.email)}</p><p>${esc(roleNames[u.role])} · 注册于 ${date(u.date_joined)} · 投稿 ${Number(u.upload_count)||list(data.resources).length} 份</p></div></div><div class="actions">${u.banned?badge('banned'):'<span class="tag">账号正常</span>'}${actions}</div></section>${u.banned?notice(`封禁原因：${esc(u.ban_reason||'未注明')}`,true):''}${u.role==='owner'?notice('超级管理员是站点的唯一归属账号，无法在网站中封禁、降级或删除。'):u.role==='admin'&&state.user.role==='admin'?notice('普通管理员无法封禁其他管理员，也无法变更账号角色。'):''}<div class="section-heading"><div><h2>该账号的投稿</h2><p>包含待审核、已发布、驳回与下架资源。</p></div></div>${list(data.resources).length?`<section class="submission-list">${list(data.resources).map(r=>submission(r,true)).join('')}</section>`:empty('这个账号还没有投稿','新提交的资源会显示在这里。')}`);content.insertAdjacentHTML('beforeend',pagination(data.resource_pagination||{},'/manage/users/'+id(objectId)+'/'));setupActions(userPage);
  }
  const menu=document.getElementById('menu-toggle');menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));menu.setAttribute('aria-label',open?'收起导航':'展开导航');document.getElementById('main-nav').classList.toggle('open',open);});
  document.getElementById('dialog-close').addEventListener('click',()=>{if(!document.getElementById('dialog-submit').disabled)document.getElementById('action-dialog').close();});
  document.getElementById('dialog-cancel').addEventListener('click',()=>document.getElementById('action-dialog').close());
  document.getElementById('action-dialog').addEventListener('cancel',e=>{if(document.getElementById('dialog-submit').disabled)e.preventDefault();});
  document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===page){a.classList.add('active');a.setAttribute('aria-current','page');}});
  document.querySelectorAll('[data-link]').forEach(a=>a.href=url(a.dataset.link));
  const titles={home:'发现灵感',characters:'素材区',presets:'预设区',rankings:'社区榜单',login:'登录',register:'注册',reset:'重设密码',upload:'上传资源',mine:'我的投稿',detail:'资源详情',manage:'管理中心',user:'账户详情'};document.title=(titles[page]||'分享灵感')+' · ChatArchive 模组分享站';
  async function init() {
    const identity=loadMe().catch(e=>{const banner=document.getElementById('global-banner');banner.textContent='账号状态暂时无法读取：'+e.message;banner.hidden=false;});
    if(!['home','characters','presets','rankings'].includes(page))await identity;
    try{if(['home','characters','presets'].includes(page))await catalog();else if(['login','register','reset'].includes(page))authPage();else if(page==='rankings')await rankingsPage();else if(page==='upload')await uploadPage();else if(page==='mine')await minePage();else if(page==='detail')await detailPage();else if(page==='manage')await managePage();else if(page==='user')await userPage();else mount(empty('页面暂时不可用','请返回首页继续探索。',`<a class="button" href="${url('/')}">返回首页</a>`));}
    catch(e){mount(empty(e.status===404?'资源暂时不可用':e.status===403?'暂无访问权限':'暂时无法加载',e.message,`<button class="button" id="retry-page">重新加载</button><a class="button" href="${url('/')}">返回首页</a>`));document.getElementById('retry-page')?.addEventListener('click',()=>location.reload());}
  }
  init();
})();
