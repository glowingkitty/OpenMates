// contract-test-file: tooling
// Actual UI field projection only. No key, store, parser, account or runtime IO.
const{test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),ts=require('typescript');
const source=path.resolve(__dirname,'../resolvedSavedEmbedBody.ts'),directory=fs.mkdtempSync(path.join(os.tmpdir(),'openmates-embed-body-'));
fs.writeFileSync(path.join(directory,'body.cjs'),ts.transpileModule(fs.readFileSync(source,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText);
const{projectResolvedSavedEmbedBody:project}=require(path.join(directory,'body.cjs'));
const ID='33333333-3333-4333-8333-333333333333';
const dto=(extra={})=>({schema_version:1,embed_id:ID,type:'code',status:'finished',text_preview:'Exact preview.',source:'selected_cookie_ws',read_only:true,cached:false,content:{code:'js:exact.js\r\nconst value = "[EMAIL_1]";',language:'js',filename:'exact.js'},...extra});
test('exact code is not header-stripped, newline-normalized, PII-restored or assigned a synthetic status',()=>{
 for(const status of ['finished','error']){const source=dto({status}),out=project(ID,source);assert.equal(out.kind,'code');assert.equal(out.status,status);assert.equal(out.code,source.content.code);assert.equal(out.language,'js');assert.equal(out.filename,'exact.js');assert.equal(Object.isFrozen(out),true);source.content.code='changed';assert.notEqual(out.code,'changed');}
 assert.equal(project(ID,dto({content:'Exact raw code\r\n'})).code,'Exact raw code\r\n');
});
test('explicit text/markdown types render exact content and unknown fields do not become guessed code',()=>{
 for(const type of ['text','markdown']){const source=dto({type,content:'Exact <tag> [EMAIL_1]\nvalue.'}),out=project(ID,source);assert.equal(out.kind,type);assert.equal(out.content,source.content);}
 for(const source of [dto({type:'future-kind'}),dto({content:{text:'Generic text is not code'}})]){const out=project(ID,source);assert.equal(out.kind,'unsupported');assert.equal(out.preview,'Exact preview.');assert.equal('code' in out,false);}
});
test('mismatched source and unsupported execution/provenance fail with fixed nonpersonal errors',()=>{
 for(const extra of [{embed_id:'other'},{status:'streaming'},{status:null},{source:'local_profile'},{cached:true},{read_only:false},{schema_version:2},{content:{code:'private',language:{wrong:true}}}])assert.throws(()=>project(ID,dto(extra)),{message:'invalid_resolved_saved_embed_body'});
 let read=false;const source=dto();Object.defineProperty(source,'status',{get(){read=true;throw Error('private value');},enumerable:true});assert.throws(()=>project(ID,source),{message:'invalid_resolved_saved_embed_body'});assert.equal(read,false);
});
