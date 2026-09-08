/**
 * Generated app-skill file download contract regression tests.
 * Exercises selection across media types and safe local filesystem behavior.
 * Uses deterministic response streams; live dev CLI runs provide direct proof.
 * No credentials or provider traffic are used by this supporting test suite.
 * Run with the package's Node TypeScript test loader.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, writeFile, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {downloadGeneratedFiles, generatedFileOptions, collectGeneratedFiles} from '../src/generatedFiles.js';
const url='https://api.example.test/v1/generated-assets/asset/files/original/download?token=test';
const result={data:{embed_id:'asset',files:{original:{format:'wav',download_url:url},preview:{format:'mp3',download_url:url+'&preview=1'}}}};
const fetchAudio=async()=>new Response('new audio');
// contract-test: supporting surface=cli assertions=cli.generated-files.cwd-default,cli.generated-files.destination
test('JSON is URL-only unless an explicit destination requests a download',()=>{
 assert.equal(generatedFileOptions({json:true}).enabled,false);
 assert.equal(generatedFileOptions({json:true,'output-dir':'music'}).enabled,true);
 assert.equal(generatedFileOptions({json:true,filename:'clip.wav'}).enabled,true);
 assert.equal(generatedFileOptions({}).enabled,true);
 assert.throws(()=>generatedFileOptions({output:'clip.wav',filename:'other.wav'}));
 assert.throws(()=>generatedFileOptions({filename:'../clip.wav'}));
 assert.throws(()=>generatedFileOptions({filename:'clip.wav'},{requests:[{},{}]}));
});
// contract-test: supporting surface=cli assertions=cli.generated-files.cwd-default
test('shared discovery saves full-quality artifacts and ignores search links',()=>{
 assert.equal(collectGeneratedFiles(result).length,1);
 assert.equal(collectGeneratedFiles({results:[result.data,result.data]}).length,1);
 assert.equal(collectGeneratedFiles({results:[{url:'https://example.test/image.png'}]}).length,0);
 for(const [variant,format] of [['full','png'],['original','mp4'],['master','glb'],['original','mp3']]){
  const found=collectGeneratedFiles({embed_id:'asset',files:{[variant]:{format,download_url:url},poster:{format:'jpg',download_url:url+'&poster=1'}}});
  assert.equal(found.length,1);assert.equal(found[0].filename.endsWith('.'+format),true);
 }
 assert.equal(collectGeneratedFiles({final:{artifacts:[{asset_id:'a',path:'out/a.csv',download_url:url},{asset_id:'a',path:'out/b.csv',download_url:url+'&b=1'}]}}).length,2);
});
// contract-test: supporting surface=cli assertions=cli.generated-files.safe-visible,cli.generated-files.destination
test('automatic names preserve files; explicit names atomically replace them',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'openmates-files-'));
 try{
  const options=generatedFileOptions({'output-dir':dir});
  const first=await downloadGeneratedFiles(result,options,fetchAudio);
  const second=await downloadGeneratedFiles(result,options,fetchAudio);
  assert.notEqual(first[0].path,second[0].path);
  const target=join(dir,'named.wav');await writeFile(target,'old audio');
  await downloadGeneratedFiles(result,generatedFileOptions({output:target}),fetchAudio);
  assert.equal(await readFile(target,'utf8'),'new audio');
  await writeFile(target,'keep me');
  await assert.rejects(downloadGeneratedFiles(result,generatedFileOptions({output:target}),async()=>new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode('partial'));c.error(new Error('disconnected'));}}))));
  assert.equal(await readFile(target,'utf8'),'keep me');
  assert.equal((await readdir(dir)).some(name=>name.includes('.partial')),false);
 }finally{await rm(dir,{recursive:true,force:true});}
});
