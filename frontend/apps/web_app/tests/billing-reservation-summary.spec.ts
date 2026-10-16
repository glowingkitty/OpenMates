/* eslint-disable @typescript-eslint/no-require-imports -- Playwright helpers use CommonJS. */
/** Isolated product REST proof for owner-scoped billing reservation aggregates. */
export {};

const { test, expect } = require('./helpers/cookie-audit');
const { getTestAccount, createSignupLogger, createStepScreenshotter } = require('./signup-flow-helpers');
const { loginToTestAccount } = require('./helpers/chat-test-helpers');
const { execFileSync } = require('node:child_process');
const { existsSync, readFileSync } = require('node:fs');
const path = require('node:path');

const API_URL = process.env.PLAYWRIGHT_TEST_API_URL?.replace(/\/$/, '');
const BILLING_PATH = '/v1/settings/billing';
const ROOT = path.resolve(__dirname, '../../../..');
const COMPOSE = path.join(ROOT, 'test-results/ci-private/compose.json');

// contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge
test('billing reservation totals require a session and contain no private hold identifiers',
  async ({ page, playwright }: { page: any; playwright: any }) => {
    test.setTimeout(120_000);
    if (!API_URL) throw new Error('Isolated PLAYWRIGHT_TEST_API_URL is required.');
    if (!getTestAccount().email) throw new Error('Fresh isolated test account is required.');
    const url = `${API_URL}${BILLING_PATH}`;

    const anonymous = await playwright.request.newContext();
    try {
      const denied = await anonymous.get(url);
      expect([401, 403]).toContain(denied.status());
      const invalidKey = await anonymous.get(url, {
        headers: { Authorization: 'Bearer sk-api-invalid-key' },
      });
      expect([401, 403]).toContain(invalidKey.status());
    } finally {
      await anonymous.dispose();
    }

    const log = createSignupLogger('billing-reservation-summary');
    const screenshot = createStepScreenshotter(log);
    await loginToTestAccount(page, log, screenshot);
    const response = await page.request.get(url);
    expect(response.ok()).toBe(true);
    const overview = await response.json();
    expect(Number.isInteger(overview.held_credits)).toBe(true);
    expect(Number.isInteger(overview.review_required_credits)).toBe(true);
    expect(overview.held_credits).toBe(0);
    expect(overview.review_required_credits).toBe(0);
    expect(overview).not.toHaveProperty('billing_reservations');
    expect(overview).not.toHaveProperty('charge_id');
    expect(overview).not.toHaveProperty('subject_hash');
  });

// contract-test: direct surface=rest_api assertions=billing.access.authenticated-first-party,billing.credits.idempotent-charge,billing.usage.receipt-token-breakdown
test('summary intent survives real personal reserve, replay, denial and settlement',
  async ({ page, playwright }: { page: any; playwright: any }) => {
    test.setTimeout(240_000);
    test.skip(process.env.GITHUB_ACTIONS !== 'true' || process.env.RUNNER_ENVIRONMENT !== 'github-hosted'
      || process.env.CI_TEST_MODE !== 'e2e', 'Requires the disposable isolated product stack');
    if (!API_URL) throw new Error('Isolated PLAYWRIGHT_TEST_API_URL is required.');
    expect(existsSync(COMPOSE)).toBe(true);
    const profile = JSON.parse(readFileSync(COMPOSE, 'utf8'));
    const apiEnv = profile.services?.api?.environment || {};
    expect(apiEnv.SERVER_ENVIRONMENT).toBe('development');
    expect(apiEnv.PRODUCTION_URL).toBe('http://localhost:5173');
    const primary = getTestAccount(1);
    const primaryEmail = primary.email;
    const secondaryEmail = getTestAccount(2).email;
    if (!primaryEmail || !secondaryEmail || primaryEmail === secondaryEmail) {
      throw new Error('Two distinct fresh isolated test accounts are required.');
    }
    const allowedEmails = Object.entries(apiEnv)
      .filter(([key]) => /^OPENMATES_TEST_ACCOUNT_CI_\d+_EMAIL$/.test(key))
      .map(([, value]) => value);
    expect(allowedEmails).toContain(primaryEmail);
    expect(allowedEmails).toContain(secondaryEmail);
    const unauthenticated = await playwright.request.newContext();
    try {
      const denied = await unauthenticated.post(`${API_URL}/internal/billing/reservation/record-intent`,
        { data: {} });
      expect(denied.status()).toBe(401);
    } finally {
      await unauthenticated.dispose();
    }

    // The isolated API container already holds the internal token, Directus
    // admin credential and Vault access. Only generated CI emails cross stdin;
    // the script prints a bounded non-private pass receipt.
    const program = `
import asyncio,base64,hashlib,json,logging,os,sys,uuid
from datetime import datetime,timezone
import httpx
logging.disable(logging.CRITICAL)
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.server_mode import is_payment_enabled

stage='guard'
async def main():
 global stage
 assert os.environ.get('SERVER_ENVIRONMENT')=='development' and is_payment_enabled()
 assert os.environ.get('PRODUCTION_URL')=='http://localhost:5173'
 assert os.environ.get('INTERNAL_API_SHARED_TOKEN') and os.environ.get('DIRECTUS_TOKEN')
 data=json.load(sys.stdin)
 emails=[data['primaryEmail'],data['secondaryEmail']]
 allowed={value for key,value in os.environ.items()
  if key.startswith('OPENMATES_TEST_ACCOUNT_CI_') and key.endswith('_EMAIL')}
 assert len(set(emails))==2 and all(mail in allowed for mail in emails)
 directus=DirectusService()
 encryption=EncryptionService()
 try:
  stage='fixture-owners'
  owners=[]
  for mail in emails:
   digest=base64.b64encode(hashlib.sha256(mail.strip().lower().encode()).digest()).decode()
   rows=await directus.get_items('directus_users',params={
    'filter[hashed_email][_eq]':digest,
    'fields':'id,hashed_email,vault_key_id,encrypted_credit_balance','limit':2},
    no_cache=True,admin_required=True,raise_on_error=True)
   assert len(rows)==1 and rows[0]['hashed_email']==digest
   assert str(uuid.UUID(rows[0]['id']))==rows[0]['id'] and rows[0]['vault_key_id']
   owners.append(rows[0])
  owner,other=owners
  owner_hash=hashlib.sha256(owner['id'].encode()).hexdigest()
  other_hash=hashlib.sha256(other['id'].encode()).hexdigest()
  before=int(await encryption.decrypt_with_user_key(owner['encrypted_credit_balance'],owner['vault_key_id']))
  assert before>=4
  charge_id='ai-ask:'+str(uuid.uuid4())+':summary'
  chat_id,message_id,summary_id=[str(uuid.uuid4()) for _ in range(3)]
  receipt={'schema_version':1,'input_tokens':12,'uncached_input_tokens':12,
   'cache_read_input_tokens':0,'cache_creation_input_tokens':0,'output_tokens':3,
   'usage_source':'provider_reported','entries':[{'model_id':'google/gemini-3.5-flash-lite',
    'inference_host':'google_ai_studio','pricing_version':'ci-summary-v1','purpose':'summary',
    'input_tokens':12,'uncached_input_tokens':12,'cache_read_input_tokens':0,
    'cache_creation_input_tokens':0,'cache_creation_5m_input_tokens':0,
    'cache_creation_1h_input_tokens':0,'output_tokens':3,
    'rates':{'input':'100','cache_read':'200','cache_write':None,
     'cache_write_1h':None,'output':'50'},
    'category_credits':{'input':'0.12','cache_read':'0','cache_write':'0',
     'cache_write_1h':'0','output':'0.06'},'raw_credits':'0.18'}],
   'raw_credits':'0.18','rounding_adjustment':'0.82','credits_charged':1,
   'settlement_state':'pending'}
  headers={'X-Internal-Service-Token':os.environ['INTERNAL_API_SHARED_TOKEN']}
  async with httpx.AsyncClient(base_url='http://api:8000',headers=headers,timeout=45) as client:
   async def post(endpoint,payload):
    response=await client.post(endpoint,json=payload)
    try: body=response.json()
    except ValueError: body={}
    return response.status_code,body
   stage='reserve'
   reserve={'user_id':owner['id'],'user_id_hash':owner_hash,
    'idempotency_key':charge_id,'quoted_credits':3,'app_id':'ai','skill_id':'ask'}
   code,first=await post('/internal/billing/reserve',reserve)
   assert code==200 and first['state']=='reserved' and first['created'] is True
   code,replay=await post('/internal/billing/reserve',reserve)
   assert code==200 and replay['created'] is False and replay['idempotent'] is True
   code,topup=await post('/internal/billing/reserve',{**reserve,'quoted_credits':4})
   assert code==200 and topup['created'] is False and topup['quoted_credits']==4
   stage='intent'
   intent={'charge_id':charge_id,'user_id':owner['id'],'user_id_hash':owner_hash,
    'app_id':'ai','skill_id':'ask','chat_id':chat_id,'message_id':message_id,
    'summary_message_id':summary_id,'llm_usage_breakdown':receipt}
   code,recorded=await post('/internal/billing/reservation/record-intent',intent)
   assert code==200 and recorded=={'state':'response_recorded',
    'charge_id':charge_id,'idempotent':False}
   code,same=await post('/internal/billing/reservation/record-intent',intent)
   assert code==200 and same['idempotent'] is True
   code,changed=await post('/internal/billing/reservation/record-intent',
    {**intent,'message_id':str(uuid.uuid4())})
   assert code==409 and changed.get('detail',{}).get('code')=='billing_intent_mismatch'
   code,denied=await post('/internal/billing/reservation/record-intent',
    {**intent,'user_id':other['id'],'user_id_hash':other_hash})
   assert code==409 and denied.get('detail',{}).get('code')=='reservation_identity_mismatch'
   stage='encrypted-intent'
   holds=await directus.get_items('billing_reservations',params={
    'filter[charge_id][_eq]':charge_id,
    'fields':'id,charge_id,state,quoted_credits,encrypted_intent,intent_vault_key_id,intent_digest',
    'limit':2},no_cache=True,admin_required=True,raise_on_error=True)
   assert len(holds)==1 and holds[0]['state']=='reserved' and holds[0]['quoted_credits']==4
   assert holds[0]['encrypted_intent'].startswith('vault:v')
   assert holds[0]['intent_vault_key_id']==owner['vault_key_id']
   clear=await encryption.decrypt_with_user_key(holds[0]['encrypted_intent'],owner['vault_key_id'])
   assert hashlib.sha256(clear.encode()).hexdigest()==holds[0]['intent_digest']
   frozen=json.loads(clear)
   assert frozen['state']=='response_recorded' and frozen['llm_usage_breakdown']==receipt
   assert set(frozen)=={'state','charge_id','chat_id','message_id','summary_message_id','llm_usage_breakdown'}
   stage='settle'
   charge={'user_id':owner['id'],'user_id_hash':owner_hash,'credits':1,
    'app_id':'ai','skill_id':'ask','idempotency_key':charge_id,
    'usage_details':{'chat_id':chat_id,'message_id':message_id,'root_chat_id':chat_id,
     'actual_chat_id':chat_id,'model_used':'google/gemini-3.5-flash-lite',
     'input_tokens':12,'output_tokens':3,'reservation_required':True,
     'llm_usage_breakdown':receipt}}
   code,settled=await post('/internal/billing/charge',charge)
   assert code==200 and settled['state']=='committed' and settled['charged_credits']==1
   code,again=await post('/internal/billing/charge',charge)
   assert code==200 and again['state']=='committed' and again['idempotent'] is True
  stage='persisted-receipt'
  holds=await directus.get_items('billing_reservations',params={
   'filter[charge_id][_eq]':charge_id,'fields':'state,actual_credits,encrypted_intent',
   'limit':2},no_cache=True,admin_required=True,raise_on_error=True)
  assert len(holds)==1 and holds[0]['state']=='settled' and holds[0]['actual_credits']==1
  assert holds[0]['encrypted_intent'].startswith('vault:v')
  usages=await directus.get_items('usage',params={
   'filter[charge_id][_eq]':charge_id,
   'fields':'id,user_id_hash,chat_id,created_at,encrypted_llm_usage_breakdown',
   'limit':2},no_cache=True,admin_required=True,raise_on_error=True)
  assert len(usages)==1 and usages[0]['user_id_hash']==owner_hash and usages[0]['chat_id']==chat_id
  assert usages[0]['encrypted_llm_usage_breakdown'].startswith('vault:v')
  public=json.loads(await encryption.decrypt_with_user_key(
   usages[0]['encrypted_llm_usage_breakdown'],owner['vault_key_id']))
  assert public['settlement_state']=='settled' and public['credits_charged']==1
  assert public['entries'][0]['purpose']=='summary' and public['entries'][0]['model_id']=='google/gemini-3.5-flash-lite'
  current=await directus.get_items('directus_users',params={
   'filter[id][_eq]':owner['id'],'fields':'id,encrypted_credit_balance','limit':1},
   no_cache=True,admin_required=True,raise_on_error=True)
  assert len(current)==1
  after=int(await encryption.decrypt_with_user_key(current[0]['encrypted_credit_balance'],owner['vault_key_id']))
  assert after==before-1
  return {'chat_id':chat_id,'year_month':datetime.fromtimestamp(usages[0]['created_at'],timezone.utc).strftime('%Y-%m')}
 finally:
  await directus.close()
  await encryption.close()

try:
 result=asyncio.run(main())
 print(json.dumps(result,separators=(',',':')))
except Exception as exc:
 print('summary intent roundtrip failed at '+stage+': '+type(exc).__name__,file=sys.stderr)
 sys.exit(1)
`;
    const output = execFileSync('docker', ['compose', '-f', COMPOSE, 'exec', '-T', 'api', 'python', '-c', program], {
      cwd: ROOT, input: JSON.stringify({ primaryEmail, secondaryEmail }), encoding: 'utf8', timeout: 150_000,
    });
    const result = JSON.parse(output.trim());
    const log = createSignupLogger('billing-summary-intent');
    const screenshot = createStepScreenshotter(log);
    await loginToTestAccount(page, log, screenshot, { credentials: primary });
    const detail = await page.request.get(`${API_URL}/v1/settings/usage/details`, {
      params: { type: 'chat', identifier: result.chat_id, year_month: result.year_month },
    });
    expect(detail.status()).toBe(200);
    const entries = (await detail.json()).entries;
    expect(entries).toHaveLength(1);
    expect(entries[0].llm_usage_breakdown.settlement_state).toBe('settled');
    expect(entries[0].llm_usage_breakdown.entries[0].purpose).toBe('summary');
    expect(entries[0]).not.toHaveProperty('encrypted_llm_usage_breakdown');
    const overview = await page.request.get(`${API_URL}${BILLING_PATH}`);
    expect(overview.status()).toBe(200);
    expect((await overview.json()).held_credits).toBe(0);
  });
