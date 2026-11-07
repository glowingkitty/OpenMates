/**
 * Case tables for the composer code-language and URL-kind parity vectors.
 * Import-free: the real TypeScript modules (codeLanguageDetection.ts, urlKinds.ts)
 * are passed in so Node type stripping can load this file in
 * generateLanguageUrlVectors.mjs and vitest can load it in languageUrlVectors.test.ts.
 * No provider-key-shaped strings appear in any case.
 */
export interface LanguageUrlModules {
	detectLanguageFromContent(text: string): string | null;
	detectLanguageFromVSCode(data: string | null | undefined): string | null;
	isYouTubeUrl(url: string): boolean;
	isGitHubRepoUrl(url: string): boolean;
	extractYouTubeVideoId(url: string): string | null;
}

const PAD = 'x'.repeat(1990);
const CONTENT_TEXTS: string[] = [
	'', ' ', '\n', 'plain prose about the weather', 'hello world\nsecond line',
	'#!/usr/bin/env python3\nprint(1)', '#!/usr/bin/env node\nconsole.log(1)', '#!/bin/bash\nls', '#!/bin/sh\nls', '#!/usr/bin/zsh\nls',
	'#!/usr/bin/ruby\nputs 1', '#!/usr/bin/perl\nprint 1', '#!/usr/bin/php\n<?php', '#!/usr/bin/env foo\nbar', '#!/usr/bin/env PYTHON\nx', '#!python bash',
	'<?xml version="1.0"?>\n<a/>', '<!DOCTYPE html>\n<html></html>', '<html lang="en">', '  <html>  ', '<?php echo 1;',
	'import os\nimport sys', 'from os import path', 'import x from "y"', "import { a } from 'b'", 'import\tx', 'import ', 'def run(a):\n  pass', 'def  run (a)', 'class Foo(Base):\n  pass',
	'class Foo < Bar', 'class Foo', 'class Foo:\n  pass', "const fs = require('fs')", 'const a=require( "b" )', 'export default function f() {}', 'export const a = 1', 'export  interface X {}',
	'export enum E {}', 'package main\nfunc main() {}', 'package com.example.app;\nclass A {}', 'use std::fmt;', 'fn main() {}', 'pub fn x() {}', 'impl Foo for Bar {}', 'impl',
	'// c\nfn main() {\n println!("x");\n}', 'fn  main()\nprintln!', 'public class Main {}', '\npublic class Main {}', '#include <stdio.h>', '#include "a.h"', '# include <x>', 'int main() {}', 'int  main  ()',
	'require "json"', "require 'json'", 'select * from t', 'SELECT 1', 'Insert INTO t VALUES (1)', 'update t set a=1', 'DELETE FROM t', 'create table t (a int)', 'ALTER TABLE t', 'drop table t', 'selectx', 'select', 'ſelect 1', 'DROPK',
	'key:\n  nested: 1', 'key:\n nested: 1', 'key:   \n  nested: 1', 'key: value\n  nested: 1', '{"a": 1}', '[1, 2, 3]', '  {"a":[1,2,{"b":null}]}  ', '{a: 1}', '{"a": 1', '[', '[]', '{}', '{"a": 1}\n\n', '{"a": 1} trailing',
	'{"a":"\\u00e9"}', '[1e3, -0.5, true, null, "x"]', '[01]', "{'a':1}", '{"a":1,"a":2}', '﻿{"a":1}',
	'sudo apt update', 'apt install x', 'npm run build', 'yarn add x', 'pip install x', 'docker ps', 'git status', 'curl http://example.invalid', 'wget x', 'gitx status', '$ ls -la', '$ls', '$  echo hi',
	'.a { color: red }', '#id{x:1}', '@media (min-width: 1px) {', '@import-x {', ':root {\n --a: 1\n}', ': root{', '.a-b_c  {',
	'# Title', '## Sub', '###### Six', '####### Seven', '#Title', '#', '- a\n- b\n- c', '- a\n- b', '* a\n* b\n* c\n* d', '+ a\n+ b\n+ c', '- a\nb\n- c\n- d', '-a\n-b\n-c',
	'line one\r\nline two', 'import os\r\nimport sys', '{"a":1}\r\n', 'key:\r\n  nested: 1', '- a\r\n- b\r\n- c', ' import os', ' # Title', '\u0085# Title',
	`fn main() {}${PAD}`, `${PAD}fn main()${'y'.repeat(20)}println!`, `${'x'.repeat(1990)}fn main() println!`, `${'x'.repeat(1991)}fn main() println!`,
	`${'x'.repeat(1992)}fn main()` + ' println!', `${'z'.repeat(1999)}😀fn main() println!`, `${'z'.repeat(1998)}😀 println!`,
	'a\n'.repeat(5) + '- a\n- b\n- c', `- a\n${'q'.repeat(2000)}\n- b\n- c`, `- a\n- b\n${'q'.repeat(1990)}\n- c\n- d`,
	`key:\n${' '.repeat(1)} x`, `key:${PAD}\n  x`, `key:\n${PAD}  x`, `{"a":"${'b'.repeat(3000)}"}`, `{"a":"${'b'.repeat(3000)}"`,
	'public class\tMain', 'public class', 'int main', 'class A < B', 'class A<B', 'class A < ', 'Python', '日本語のテキスト', '🚀 launch', 'α = 1\nβ = 2',
	'#!/usr/bin/env python\n# -*- coding: utf-8 -*-', 'import\nos', 'from . import x', 'from x import', 'from x  import y', 'export type A = 1', 'export default class A {}', 'exports.a = 1',
];

const VSCODE_VALUES: (string | null)[] = [
	null, '', '{}', '[]', 'null', '7', '"mode"', 'true', '{"mode":"python"}', '{"mode":""}', '{"mode":null}', '{"mode":7}', '{"mode":["a"]}', '{"mode":{"a":1}}',
	'{"mode":"typescript","multiCursorText":null}', '{"version":1,"mode":"rust"}', '{"mode":"a","mode":"b"}', 'not json', '{', '{"mode":"caf\\u00e9"}', '{"mode":"  "}', '{"Mode":"x"}',
	'[{"mode":"python"}]', '{"mode":"python"} trailing', ' {"mode":"go"} ', '{"mode":"🚀"}',
];

const URLS: string[] = [
	'', 'not a url', 'https://example.invalid/', 'ftp://youtu.be/dQw4w9WgXcQ',
	'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'http://youtube.com/watch?v=dQw4w9WgXcQ', 'https://m.youtube.com/watch?v=dQw4w9WgXcQ', 'https://youtu.be/dQw4w9WgXcQ',
	'https://youtu.be/dQw4w9WgXcQ?t=10', 'https://www.youtube.com/embed/dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ', 'https://www.youtube.com/v/dQw4w9WgXcQ',
	'HTTPS://WWW.YOUTUBE.COM/WATCH?V=dQw4w9WgXcQ', 'HTTPS://YOUTU.BE/dQw4w9WgXcQ', 'https://www.youtube.com/watch?v=short', 'https://www.youtube.com/watch?v=dQw4w9WgXcQextra',
	'https://www.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ', 'https://www.youtube.com/watch?feature=x&v=dQw4w9WgXcQ&t=1', 'https://www.youtube.com/watch?v=dQw4w9WgXc-', 'https://www.youtube.com/watch?v=___________',
	'https://www.youtube.com/playlist?list=PL1', 'https://www.youtube.com/', 'https://music.youtube.com/watch?v=dQw4w9WgXcQ', 'https://www.youtube.com/watch/dQw4w9WgXcQ',
	'https://evil.invalid/?v=dQw4w9WgXcQ', 'https://evil.invalid/youtu.be/dQw4w9WgXcQ', 'https://evil.invalid/youtube.com/embed/dQw4w9WgXcQ', ' https://youtu.be/dQw4w9WgXcQ', 'https://youtu.be/', 'https://youtu.be/abc',
	'https://www.youtube.com/SHORTS/dQw4w9WgXcQ', 'https://www.youtube.com/shorts/dQw4w9WgXcQ?v=AAAAAAAAAAA', 'https://youtu.be/dQw4w9WgXcQ&v=BBBBBBBBBBB',
	'https://github.com/owner/repo', 'https://www.github.com/owner/repo', 'http://github.com/owner/repo', 'HTTPS://GITHUB.COM/Owner/Repo', 'https://github.com/owner/repo/', 'https://github.com/owner/repo?tab=readme', 'https://github.com/owner/repo#readme',
	'https://github.com/owner/repo/', 'https://github.com/owner/repo//', 'https://github.com/owner/repo/issues', 'https://github.com/owner', 'https://github.com/', 'https://github.com', 'https://github.com/owner/',
	'https://github.com/features/copilot', 'https://github.com/topics/rust', 'https://github.com/collections/x', 'https://github.com/marketplace/y', 'https://github.com/explore/z', 'https://github.com/login/oauth',
	'https://github.com/Features/x', 'https://github.com/owner/repo.git', 'https://github.com/o/r?a=b#c', 'https://github.com/o/r?', 'https://github.com/o/r#', 'https://github.com/o/r?a b',
	'https://github.com/o/r?a=1\n', 'https://github.com/o/r?a=\t1', 'https://github.com/o/r#x y', 'https://github.com/o/r\n', 'https://github.com/o /r', 'https://github.com/o/r r', 'https://github.com/o\\r', 'https://github.com/o\\r/x',
	'https://github.com/./r', 'https://github.com/../r', 'https://github.com/o/..', 'https://github.com/o/.', 'https://github.com/a/b/..', 'https://github.com/%41/%42', 'https://github.com/o%2Fx/r', 'https://github.com/ö/ü', 'https://github.com/日本/語',
	'https://github.com:443/o/r', 'https://user@github.com/o/r', 'https://github.com.evil.invalid/o/r', 'https://evilgithub.com/o/r', 'https://gist.github.com/o/r', 'https://raw.github.com/o/r',
	'https://github.com/o/r?a=https://github.com/x/y', 'https://github.com/-/-', 'https://github.com/_/_', 'https://github.com/o/r ', 'https://github.com/o/ r', 'https://github.com/o/r?é', 'ssh://github.com/o/r',
	'https://ſhorts.invalid', 'https://www.youtube.com/ſhorts/dQw4w9WgXcQ', 'https://github.com/o/r?a\r', 'https://github.com/K/r',
];

export function buildLanguageUrlVectors(modules: LanguageUrlModules) {
	const language = [];
	for (const text of CONTENT_TEXTS) {
		for (const vscode of [null, '{"mode":"python"}']) {
			language.push({
				in: vscode === null ? { text } : { text, vsCodeEditorData: vscode },
				out: { vsCode: modules.detectLanguageFromVSCode(vscode), content: modules.detectLanguageFromContent(text) },
			});
		}
	}
	for (const vsCodeEditorData of VSCODE_VALUES) {
		language.push({
			in: vsCodeEditorData === null ? {} : { vsCodeEditorData },
			out: { vsCode: modules.detectLanguageFromVSCode(vsCodeEditorData), content: null },
		});
	}
	const urls = URLS.map((url) => ({
		in: { url },
		out: { youtube: modules.isYouTubeUrl(url), githubRepo: modules.isGitHubRepoUrl(url), videoId: modules.extractYouTubeVideoId(url) },
	}));
	return { language, urls };
}
