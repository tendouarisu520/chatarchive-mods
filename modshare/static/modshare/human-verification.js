/* A consumed token is never reused, including after failed network requests. */
(() => {
  'use strict';
  const sitekey = document.documentElement.dataset.turnstileSitekey || '';
  let loading = null, script = null;
  function loadService() {
    if (typeof window.turnstile?.render === 'function') return Promise.resolve();
    if (loading) return loading;
    script?.remove();
    script = document.createElement('script');
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    loading = new Promise((resolve,reject) => {
      const current = script;
      const timeout = setTimeout(()=>finish(false),30000);
      function finish(ok) {
        clearTimeout(timeout); current.onload = current.onerror = null;
        if (ok && typeof window.turnstile?.render === 'function') resolve();
        else { current.remove(); reject(new Error('安全验证加载失败，请检查网络后点击重试。')); }
      }
      current.onload=()=>finish(true); current.onerror=()=>finish(false);
      document.head.append(current);
    }).finally(()=>{loading=null;});
    return loading;
  }
  function failureMessage(value) {
    const code = /^\d{6}$/.test(String(value)) ? String(value) : '';
    let hint = '请点击“重试验证”；若仍失败，可换浏览器或网络重试。';
    if (code==='110200') hint='当前域名未获验证授权，请联系管理员并提供此代码。';
    else if (['110100','110110','400020','400021','400070'].includes(code)) hint='验证配置异常，请联系管理员并提供此代码。';
    else if (code==='200100') hint='请校准设备时间并刷新页面。';
    else if (code==='200500') hint='验证窗口未能连接，请检查网络或拦截扩展后重试。';
    return `安全验证失败${code?'（'+code+'）':''}。${hint}`;
  }
  function mount(form, action) {
    if (!sitekey) return {consume:()=>undefined, reset:()=>{}, ready:Promise.resolve()};
    const field = document.createElement('div');
    field.className = 'field human-verification';
    const label = document.createElement('label'); label.textContent = '人机验证';
    const container = document.createElement('div');
    const message = document.createElement('p'); message.className = 'field-hint';
    message.setAttribute('role', 'status'); message.textContent = '正在加载安全验证…';
    const retry = document.createElement('button'); retry.type = 'button';
    retry.className = 'button small'; retry.textContent = '重试验证'; retry.hidden = true;
    field.append(label, container, message, retry);
    form.insertBefore(field, form.querySelector('button[type=submit]'));
    let token = '', widget, starting = false;
    const reported = new Set();
    function report(code) {
      if (!/^(?:\d{6}|script-load-failed)$/.test(code)||reported.has(code)||!window.fetch) return;
      reported.add(code);
      const cookie=document.cookie.split('; ').find(c=>c.startsWith('modcsrftoken='));
      const base=(document.documentElement.dataset.base||'').replace(/\/$/,'');
      window.fetch(base+'/api/auth/verification-report/',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRFToken':cookie?decodeURIComponent(cookie.slice(13)):''},
        body:JSON.stringify({action,code})}).catch(()=>{});
    }
    function failed(text) { token = ''; message.textContent = text; retry.hidden = false; }
    const gate = {
      consume() {
        if (!token) throw new Error('请先完成人机验证；验证失败时点击“重试验证”。');
        const value = token; token = ''; return value;
      },
      reset() {
        token = ''; retry.hidden = true; message.textContent = '请等待或完成新的安全验证。';
        if (widget !== undefined && window.turnstile) {
          try { window.turnstile.reset(widget); }
          catch {
            try { window.turnstile.remove(widget); } catch {}
            widget=undefined; container.replaceChildren(); gate.ready=start();
          }
        } else { gate.ready = start(); }
      },
      ready: null,
    };
    async function start() {
      if (starting) return;
      starting = true;
      try {
        await loadService();
        widget = window.turnstile.render(container, {
          sitekey, action, theme:'light', language:'zh-cn',
          size:form.clientWidth < 300 ? 'compact' : 'flexible', 'response-field':false,
          callback(value) { token = value; retry.hidden = true; message.textContent = '验证通过，可以继续。'; },
          'expired-callback'() { failed('验证已过期，请点击“重试验证”。'); },
          'timeout-callback'() { failed('验证超时，请点击“重试验证”。'); },
          'error-callback'(code) { failed(failureMessage(code)); report(String(code)); return true; },
        });
      } catch { failed('安全验证未能加载，请检查网络或刷新页面后重试。'); report('script-load-failed'); }
      finally { starting = false; }
    }
    retry.addEventListener('click', () => gate.reset());
    gate.ready = start();
    return gate;
  }
  window.ChatArchiveHumanVerification = {mount};
})();
