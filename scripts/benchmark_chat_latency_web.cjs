#!/usr/bin/env node
/**
 * Live dev, real-inference browser latency probe.
 * Uses a numbered disposable test account and one disposable Project.
 * Records a real Playwright video for every invocation, including failures.
 * Persists only timing markers and case identifiers, never prompts or answers.
 * Answer timing reads the rendered message body, excluding Thinking and activity.
 * Run only against the fixed dev origin; never substitute production credentials.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const phase = process.argv[2];
const projectId = process.argv[3];
const output = process.argv[4];
if (!['before', 'after'].includes(phase) || !/^[0-9a-f-]{36}$/.test(projectId) || !output) throw new Error('usage: benchmark_chat_latency_web.cjs before|after PROJECT_ID OUTPUT_DIR');
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const env = Object.fromEntries(fs.readFileSync(path.resolve(__dirname, '../.env'),'utf8').split(/\r?\n/).filter(x=>x.includes('=') && !x.startsWith('#')).map(x=>{ const i=x.indexOf('='); let v=x.slice(i+1).trim(); if ((v.startsWith('"')&&v.endsWith('"'))||(v.startsWith("'")&&v.endsWith("'"))) v=v.slice(1,-1); return [x.slice(0,i).trim(),v] }));
const slot=process.env.BENCHMARK_SLOT||'4';
if(!/^\d{1,2}$/.test(slot)) throw new Error('invalid numbered dev test slot');
const email=env[`OPENMATES_TEST_ACCOUNT_${slot}_EMAIL`], password=env[`OPENMATES_TEST_ACCOUNT_${slot}_PASSWORD`], otpKey=env[`OPENMATES_TEST_ACCOUNT_${slot}_OTP_KEY`];
if (!email||!password) throw new Error('dedicated test credentials missing');
function totp(secret) { const abc='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits='', arr=[]; for(const c of secret.toUpperCase().replace(/[^A-Z2-7]/g,'')){bits+=abc.indexOf(c).toString(2).padStart(5,'0');while(bits.length>=8){arr.push(parseInt(bits.slice(0,8),2));bits=bits.slice(8)}} const b=Buffer.alloc(8);b.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const d=crypto.createHmac('sha1',Buffer.from(arr)).update(b).digest();const off=d[19]&15;return String((d.readUInt32BE(off)&0x7fffffff)%1000000).padStart(6,'0') }
const cases=[['simple',1,'Reply with exactly one sentence explaining why the sky looks blue.'],['simple',2,'Reply with exactly one sentence explaining why the sky looks blue.'],['complex',1,'Compare two ways to improve city bus reliability under a fixed budget; discuss tradeoffs and recommend a phased plan in four concise bullet points. Do not use tools.'],['simple',3,'Reply with exactly one sentence explaining why the sky looks blue.'],['complex',2,'Compare two ways to improve city bus reliability under a fixed budget; discuss tradeoffs and recommend a phased plan in four concise bullet points. Do not use tools.'],['complex',3,'Compare two ways to improve city bus reliability under a fixed budget; discuss tradeoffs and recommend a phased plan in four concise bullet points. Do not use tools.']];
(async()=>{let browser,context,page; const results=[]; try { browser=await chromium.launch({headless:true,args:['--no-sandbox']}); context=await browser.newContext({viewport:{width:1440,height:900},recordVideo:{dir:output,size:{width:1440,height:900}}}); page=await context.newPage(); await page.goto('https://app.dev.openmates.org/',{waitUntil:'domcontentloaded'}); await page.getByTestId('header-login-signup-btn').click(); await page.getByTestId('tab-login').click(); await page.getByTestId('login-email-input').fill(email); await page.getByTestId('login-continue-button').click(); await page.getByTestId('login-password-input').fill(password); await page.getByTestId('login-submit-button').click(); const otp=page.getByTestId('login-otp-input'); const auth=page.locator('[data-authenticated="true"]'); await Promise.race([otp.waitFor({state:'visible',timeout:30000}),auth.waitFor({state:'visible',timeout:30000})]); if(await otp.isVisible()){await otp.fill(totp(otpKey)); if(await page.getByTestId('login-submit-button').isVisible()) await page.getByTestId('login-submit-button').click().catch(()=>{});} await auth.waitFor({state:'visible',timeout:30000}); await page.getByTestId('message-editor').waitFor({state:'visible',timeout:30000});
for(const [complexity,trial,prompt] of cases.filter(([c,t])=>!process.env.BENCHMARK_ONLY||process.env.BENCHMARK_ONLY.split(',').includes(`${c}-${t}`))){const rec={phase,client:'web',complexity,trial,status:'started',cold:trial===1&&complexity==='simple',prompt_id:complexity,started_utc:new Date().toISOString()};try{await page.goto(`https://app.dev.openmates.org/#project-id=${projectId}`,{waitUntil:'domcontentloaded'}); if(!(await page.getByTestId('project-workspace-header').isVisible().catch(()=>false))) await page.getByText('Latency comparison', {exact:false}).first().click(); await page.getByTestId('project-workspace-header').waitFor({state:'visible',timeout:30000}); await page.getByTestId('project-tab-folders').click(); await page.getByTestId('project-folder-create-menu-button').click(); await page.getByTestId('project-create-chat').click();const editor=page.getByTestId('message-editor');await editor.waitFor({state:'visible',timeout:30000}); await page.getByTestId('message-field').click(); await editor.click(); await page.keyboard.insertText(prompt); const send=page.getByTestId('composer-send-button').filter({visible:true}); await send.waitFor({state:'visible',timeout:10000}); await page.waitForFunction(async () => {
    const read = () => {
      const sends = [...document.querySelectorAll('[data-testid="composer-send-button"]')].filter(button => button.getClientRects().length > 0);
      if (sends.length !== 1) return null;
      const wrapper = sends[0].closest('[data-action="message-input"]');
      const selector = [...(wrapper?.querySelectorAll('[data-testid="composer-model-selector"]') || [])].find(button => button.getClientRects().length > 0);
      return selector && !selector.disabled && selector.getAttribute('data-loading') === 'false'
        ? wrapper.getAttribute('data-current-chat-id') : null;
    };
    const context = read();
    if (!context || !/^[0-9a-f-]{36}$/.test(context)) return false;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return read() === context;
  }, null, {timeout:30000}); if(await send.count()!==1) throw new Error('expected one visible composer Send'); await page.evaluate(() => {
  const start = performance.now();
  const result = {};
  const userCount = document.querySelectorAll('[data-testid="message-user"]').length;
  const assistantCount = document.querySelectorAll('[data-testid="message-assistant"]').length;
  const editor = [...document.querySelectorAll('[data-testid="message-editor"]')].find(element => element.getClientRects().length > 0);
  const sendButton = [...document.querySelectorAll('[data-testid="composer-send-button"]')].find(element => element.getClientRects().length > 0);
  let previousAnswer = '';
  const inspect = () => {
    if (result.send_ms === undefined) return;
    const t = performance.now() - start;
    if (result.input_clear_ms === undefined && editor && !editor.innerText.trim()) result.input_clear_ms = t;
    if (result.user_row_ms === undefined && document.querySelectorAll('[data-testid="message-user"]').length > userCount) result.user_row_ms = t;
    // Older deployment boundary; retained for like-for-like BEFORE records.
    if (result.typing_ms === undefined && document.querySelector('[data-testid="typing-indicator"]')) result.typing_ms = t;
    const pending = document.querySelector('[data-testid="pending-assistant-response"]');
    const assistants = document.querySelectorAll('[data-testid="message-assistant"]');
    const assistant = assistants.length > assistantCount ? assistants[assistants.length - 1] : null;
    if (result.response_shell_ms === undefined && (pending || assistant)) result.response_shell_ms = t;
    if (result.accepted_thinking_ms === undefined && pending?.querySelector('[data-testid="assistant-transient-thinking"]')) result.accepted_thinking_ms = t;
    if (result.thinking_content_ms === undefined && assistant?.querySelector('[data-testid="thinking-section"]')) result.thinking_content_ms = t;
    const model = (pending || assistant)?.querySelector('[data-testid="generated-by-container"]');
    if (result.model_visible_ms === undefined && model?.textContent.trim()) result.model_visible_ms = t;
    // The read-only ProseMirror contains the answer, unlike chat-message-text,
    // which also contains Thinking, skill activity, and response status.
    const body = [...(assistant?.querySelectorAll('.chat-message-body [data-testid="message-content"] .ProseMirror') || [])]
      .find(node => !node.closest('[data-testid="assistant-activity-group"], [data-testid="assistant-response-thinking"]'));
    const answer = (body?.innerText || '').trim();
    if (answer && answer !== previousAnswer) {
      if (result.first_text_ms === undefined) result.first_text_ms = t;
      result.last_text_change_ms = t;
      previousAnswer = answer;
    }
    const stillActive = pending || assistant?.querySelector('.assistant-response-active, [data-testid="assistant-response-status"]');
    const completedAttribution = assistant?.querySelector('[data-testid="generated-by"]');
    if (result.first_text_ms !== undefined && !stillActive && completedAttribution) {
      result.final_status_ms ??= t;
    } else {
      delete result.final_status_ms;
    }
  };
  sendButton?.addEventListener('click', () => {
    result.send_ms = performance.now() - start;
    const wrapper = sendButton?.closest('[data-action="message-input"]');
    const selector = [...(wrapper?.querySelectorAll('[data-testid="composer-model-selector"]') || [])].find(button => button.getClientRects().length > 0);
    result.selection_ready_at_click = !!selector && !selector.disabled && selector.getAttribute('data-loading') === 'false';
    result.visible_composer_count_at_click = [...document.querySelectorAll('[data-action="message-input"]')].filter(node => node.getClientRects().length > 0).length;
    inspect();
  }, { once: true, capture: true });
  const observer = new MutationObserver(inspect);
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true,
    attributeFilter: ['class', 'data-status'] });
  window.__benchmark = { result, observer };
});await send.click(); await page.waitForFunction(()=>window.__benchmark?.result?.user_row_ms!==undefined,null,{timeout:8000}); await page.waitForFunction(()=>window.__benchmark?.result?.first_text_ms!==undefined,null,{timeout:150000}); await page.waitForFunction(()=>{const x=window.__benchmark?.result;if(!x?.first_text_ms||x.final_status_ms===undefined)return false;return performance.now()-x.last_text_change_ms>2200},null,{timeout:150000}); const data=await page.evaluate(()=>{const x=window.__benchmark; x.observer.disconnect(); const result={...x.result}; result.completion_ms=result.last_text_change_ms; return result}); Object.assign(rec,data,{status:'passed',url_hash:crypto.createHash('sha256').update(page.url()).digest('hex').slice(0,12)}); }catch(e){Object.assign(rec, await page.evaluate(() => ({...(window.__benchmark?.result || {})})).catch(() => ({})));rec.status='failed';rec.error=String(e).slice(0,350); await page.screenshot({path:path.join(output,`${complexity}-${trial}-failure.png`)}).catch(()=>{});results.push(rec);break;}results.push(rec);fs.writeFileSync(path.join(output,'metrics.json'),JSON.stringify({phase,client:'web',project_id_hash:crypto.createHash('sha256').update(projectId).digest('hex').slice(0,12),runs:results},null,2));console.log(JSON.stringify({complexity,trial,status:rec.status,send_to_first_text_ms:rec.first_text_ms===undefined?null:Math.round(rec.first_text_ms-rec.send_ms),send_to_completion_ms:rec.completion_ms===undefined?null:Math.round(rec.completion_ms-rec.send_ms)})); }
}catch(e){console.error(String(e).slice(0,500));}finally{if(page)await page.close().catch(()=>{});if(context)await context.close().catch(()=>{});if(browser)await browser.close().catch(()=>{});fs.writeFileSync(path.join(output,'metrics.json'),JSON.stringify({phase,client:'web',project_id_hash:crypto.createHash('sha256').update(projectId).digest('hex').slice(0,12),runs:results},null,2));} if(results.length!==(process.env.BENCHMARK_ONLY?process.env.BENCHMARK_ONLY.split(',').length:cases.length)||results.some(x=>x.status!=='passed'))process.exitCode=1;})();
