// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseTuiMarkdown, renderTuiMarkdownLines} from '../src/tuiMarkdown.js';
import {cells, lineText} from '../src/tuiText.js';

const lines = (content:string,width=80,resolveEmbedAlias?: (id:string)=>string|undefined) =>
  renderTuiMarkdownLines(content,width,{resolveEmbedAlias});
const plain = (content:string,width=80,resolveEmbedAlias?: (id:string)=>string|undefined) =>
  lines(content,width,resolveEmbedAlias).map(lineText).join('\n');

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('headings and nested emphasis render as styled fixed-cell text without visible markers',()=>{
  const rendered=lines('Intro\n## **Oceanic+** details\nA **bold *inner* phrase** and *quiet* note.');
  assert.deepEqual(rendered.map(lineText),['Intro','','Oceanic+ details','A bold inner phrase and quiet note.']);
  const heading=rendered[2]; assert.ok(typeof heading!=='string'&&heading.bold&&heading.color);
  const paragraph=rendered[3]; assert.ok(typeof paragraph!=='string');
  assert.ok(paragraph.spans?.some(span=>span.text==='bold inner phrase'&&span.bold));
  assert.ok(paragraph.spans?.some(span=>span.text.includes('quiet')&&!span.bold));
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('inline wiki and embed references retain readable labels and compact usable commands',()=>{
  const seen:string[]=[];
  const output=plain('Try [Oceanic+](embed:fitness-search-1) with [Apple Watch](wiki:Apple_Watch).',80,id=>{seen.push(id);return 'fit-s_c-1';});
  assert.deepEqual(seen,['fitness-search-1']);
  assert.equal(output,'Try Oceanic+ (/embed fit-s_c-1) with Apple Watch (/wiki Apple_Watch).');
  assert.equal(plain('Open [source](embed:missing)',80,()=>undefined),'Open source (/embed missing)');
  assert.equal(plain('[!](embed:missing)'), 'Embed (/embed missing)');
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('escaped markdown, inline code and ordinary code fences stay literal',()=>{
  assert.equal(plain('\\*\\*literal\\*\\* `**code** [x](embed:id)` **real**'), '**literal** **code** [x](embed:id) real');
  const output=plain('```ts\nconst x = "[x](embed:id) **bold**";\n```\nAfter **code**.');
  assert.equal(output,'```ts\nconst x = "[x](embed:id) **bold**";\n```\nAfter code.');
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('results-view fences produce typed blocks, dedupe refs and never expose special syntax',()=>{
  const blocks=parseTuiMarkdown('Before\n```embeds_results_view\ntitle: Nearby classes\nembeds: one, two, one\nsources: src, src\nhighlight: two\n```\nAfter',60);
  assert.deepEqual(blocks.filter(block=>block.type==='results-view'),[{type:'results-view',title:'Nearby classes',embeds:['one','two'],sources:['src'],highlight:['two']}]);
  assert.deepEqual(blocks.filter(block=>block.type==='line').map(block=>lineText(block.line)),['Before','After']);
  const legacy=parseTuiMarkdown('~~~embeds_map_view\nembeds: id, id\n',80);
  assert.deepEqual(legacy,[{type:'results-view',title:'Results view',embeds:['id'],sources:[],highlight:[]}]);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('Unicode wrap keeps style and width on every line',()=>{
  const rendered=lines('**漢🧪 café é** [Apple Watch](wiki:Apple_Watch)',9);
  assert.ok(rendered.length>2);
  assert.ok(rendered.every(line=>cells(lineText(line))<=9));
  assert.equal(rendered.map(lineText).join(''),'漢🧪 café é Apple Watch (/wiki Apple_Watch)');
  assert.ok(rendered.some(line=>typeof line!=='string'&&line.spans?.some(span=>span.bold)));
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('invalid references and hostile terminal bytes remain plain safe text',()=>{
  const output=plain('[bad](embed:../../secret) [script](javascript:alert(1)) [site](https://example.org/a) \x1b[31mred\x1b]0;title\x07',200);
  assert.ok(output.includes('[bad](embed:../../secret)'));
  assert.ok(output.includes('[script](javascript:alert(1))'));
  assert.ok(output.includes('site (https://example.org/a)'));
  assert.ok(!output.includes('\x1b'));
  assert.ok(!output.includes('\x07'));
});
