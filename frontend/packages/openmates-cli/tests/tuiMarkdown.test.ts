// contract-test-file: infrastructure
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseTuiMarkdown, renderTuiMarkdownLines} from '../src/tuiMarkdown.js';
import {cells, graphemeCellWidth, lineText} from '../src/tuiText.js';

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

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content,terminal-pointer.visible-action-parity
test('wide graphemes and nested escaped Markdown retain cell widths and trusted actions',()=>{
  const graphemes:[string,number][]=[['👩‍💻',2],['🇩🇪',2],['1️⃣',2],['e\u0301',1],['漢',2],['\u0301',0]];
  for(const [grapheme,width] of graphemes){
    assert.equal(graphemeCellWidth(grapheme),width);
    assert.equal(cells(grapheme),width);
  }
  const content='**👩‍💻🇩🇪1️⃣e\u0301漢 *nested* \\*literal\\*** [Open](wiki:guide) \\[inert](wiki:guide)';
  const rendered=lines(content,8);
  assert.ok(rendered.every(line=>cells(lineText(line))<=8));
  assert.equal(rendered.map(lineText).join(''),'👩‍💻🇩🇪1️⃣e\u0301漢 nested *literal* Open (/wiki guide) [inert](wiki:guide)');
  const actions=rendered.flatMap(line=>typeof line==='string'?[]:(line.spans??[]).flatMap(span=>span.action?[span.action]:[]));
  assert.ok(actions.length>0);
  assert.ok(actions.every(action=>action.kind==='command'&&action.command==='/wiki guide'));
  assert.equal(lines('```text\n[Open](wiki:guide) 👩‍💻\n```',8).flatMap(line=>
    typeof line==='string'?[]:(line.spans??[]).filter(span=>span.action)).length,0);
});

// contract-test: supporting surface=cli assertions=terminal-ui.chat.rich-content
test('semantic discovery equals the protocol blocks of complete Markdown without wrapping prose',()=>{
  const samples=[
    'Text **bold**\n```embeds_results_view\nembeds: one\n```\nAfter',
    '~~~text\n```interactive_question\n{}\n```\n~~~',
    '```interactive_question\n'+JSON.stringify({type:'choice',id:'q',question:'Pick',options:[{id:'a',text:'A'}]})+'\n```',
    '```interactive_response\n{"id":"q","selection":["a"]}\n```',
    '```interactive_question\nmalformed\n```\n~~~embeds_map_view\nembeds: two',
    '```interactive_question\n{"id":"q"}',
  ];
  for(const content of samples)for(const questionBlocks of [true,false])
    assert.deepEqual(parseTuiMarkdown(content,8,{semanticOnly:true,questionBlocks}),
      parseTuiMarkdown(content,8,{questionBlocks}).filter(block=>block.type!=='line'));
});
