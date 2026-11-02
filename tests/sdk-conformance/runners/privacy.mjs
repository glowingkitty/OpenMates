// contract-test: supporting surface=sdks.npm assertions=pii.surface.semantic-parity
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const {preparePrivacy,restorePrivacy,SessionClientError}=await import('../../../frontend/packages/openmates-cli/dist/sdk-entry.js');
const option=name=>process.argv[process.argv.indexOf(name)+1];
const capability='local.privacy.v1';
assert.equal(option('--capability'),capability);
const raw=readFileSync(option('--fixture'));
const vectors=JSON.parse(raw).capabilities[capability].vectors;
assert.ok(vectors.length);
const results=[];
for(const vector of vectors){
  const before=structuredClone(vector), value=structuredClone(vector.input);
  const expand=vector.expand??{};
  if(expand.text_bytes) value.text='x'.repeat(expand.text_bytes);
  if(expand.mapping_count) value.mappings=Array(expand.mapping_count).fill(null);
  if(expand.encoded_bytes) {value.mappings=[''];const overhead=Buffer.byteLength(JSON.stringify(value),'utf8');value.mappings=['x'.repeat(expand.encoded_bytes-overhead)];}
  if(expand.existing_count)value.existing_mappings=Array.from({length:expand.existing_count},(_,i)=>({original:`unrelated-${i}`,placeholder:`[KEEP_${i}]`}));
  if(expand.email_repeats)value.text='a@b.co '.repeat(expand.email_repeats);
  if(expand.prepare_json_bytes){value.existing_mappings=[{original:'unrelated',placeholder:'[KEEP]',padding:''}];const overhead=Buffer.byteLength(JSON.stringify(value),'utf8');value.existing_mappings[0].padding='x'.repeat(expand.prepare_json_bytes-overhead);}
  if(expand.canonical_json_bytes)value.mappings[1]='x'.repeat(expand.canonical_json_bytes-expand.canonical_overhead);
  if(expand.placeholder_bytes){value.text='x'.repeat(expand.plain_repeats);value.existing_mappings=[{original:'x',placeholder:'['+'A'.repeat(expand.placeholder_bytes-2)+']'}];}
  if(expand.original_bytes){value.text='[X]'.repeat(expand.token_repeats);value.mappings=[{original:'y'.repeat(expand.original_bytes),placeholder:'[X]'}];}
  let output;
  try {
    output=value.operation==='prepare' ? preparePrivacy(value.text,{memories:value.memories,existingMappings:value.existing_mappings,enhanced:value.enhanced}) : {text:restorePrivacy(value.text,value.mappings)};
  } catch(error) {
    assert.ok(error instanceof SessionClientError);
    assert.equal(error.code,vector.error,vector.id);
    assert.ok(!error.message.includes('synthetic private value'));
  }
  if(output){
    assert.ok(!vector.error,vector.id);
    if(vector.expected_text_length)assert.equal(output.text,(vector.expected_repeat_character??'x').repeat(vector.expected_text_length));
    if(vector.expected)assert.deepEqual(output,vector.expected,vector.id);
    if(vector.mapping_values){
      assert.deepEqual(output.mappings.map(m=>({original:m.original,type:m.type})),vector.mapping_values,vector.id);
      const tokens=output.mappings.map(m=>m.placeholder);
      assert.equal(new Set(tokens).size,tokens.length);
      for(const mapping of output.mappings){
        assert.match(mapping.placeholder,/^\[OM_PII_[A-F0-9]{32}\]$/);
        assert.ok(output.text.includes(mapping.placeholder));
        assert.ok(!output.text.includes(mapping.original));
      }
    }
    if(vector.prepared_text_length)assert.equal(Buffer.byteLength(output.text,'utf8'),vector.prepared_text_length);
    if(vector.prepared_token_output)assert.equal(output.text,output.mappings[0].placeholder);
    if(vector.roundtrip_input)assert.equal(restorePrivacy(output.text,output.mappings),value.text);
    if(Object.hasOwn(vector,'restored')) assert.equal(restorePrivacy(output.text,output.mappings),vector.restored,vector.id);
  }
  assert.deepEqual(vector,before);
  results.push({id:vector.id,status:'passed'});
}
console.log(JSON.stringify({capability,language:'npm',status:'passed',fixtureSha256:createHash('sha256').update(raw).digest('hex'),results}));
