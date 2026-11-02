// No SDK/network invocation: exercise the actual fixed runner's error helper.
// NAPI-shaped Error fixtures are unit data, not an actual native-addon proof.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
const path=process.env.OPENMATES_TEST_ALLOCATION_RUNNER_SOURCE??fileURLToPath(new URL('./api-key-foundation.mjs',import.meta.url));
const source=readFileSync(path,'utf8');
const helpers=source.split('\n').filter(line=>line.startsWith('const errorCode='));
assert.equal(helpers.length,1,'one actual reviewed runner normalizer');
const normalize=vm.runInNewContext(helpers[0]+'\nerrorCode;',Object.create(null));
const native=(code,message='The operation was cancelled.')=>Object.assign(new Error(JSON.stringify({code,message})),{code:'GenericFailure'});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
test('raw NAPI status cannot mask original structured queued cancellation',()=>{
  const failure=native('cancelled');
  assert.equal(normalize(failure),'cancelled');
  const actual={error:normalize(failure)};
  assert.equal(actual.error,'cancelled');assert.equal('value' in actual,false);
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
test('other structured denials and normalized public facade codes keep original semantics',()=>{
  assert.equal(normalize(native('forbidden','This operation is not available.')),'forbidden');
  assert.equal(normalize(Object.assign(new Error('The operation was cancelled.'),{code:'cancelled'})),'cancelled');
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
test('unknown or malformed native reason never guesses cancellation or emits private diagnostics',()=>{
  const marker='synthetic-private-server-diagnostic';
  for(const reason of [marker,JSON.stringify({code:'cancelled'}),JSON.stringify({code:1,message:marker})]) {
    const failure=Object.assign(new Error(reason),{code:'GenericFailure'});
    assert.equal(normalize(failure),'GenericFailure');
    assert.equal(JSON.stringify({error:normalize(failure)}).includes(marker),false);
  }
});
// contract-test: supporting surface=sdks.npm assertions=sdk.library.explicit-headless,sdk.auth.credential-separation
test('absent envelope fields and non-string payload fields retain existing fallback without inventing cancelled',()=>{
  for(const reason of ['{}',JSON.stringify({message:'safe'}),JSON.stringify({code:'cancelled',message:1})]) {
    assert.equal(normalize(Object.assign(new Error(reason),{code:'GenericFailure'})),'GenericFailure');
  }
  assert.equal(normalize({} ),undefined);
  assert.equal(normalize({code:'forbidden'}),'forbidden');
  assert.notEqual(normalize(native('forbidden','A safe refusal.')),'cancelled');
});
