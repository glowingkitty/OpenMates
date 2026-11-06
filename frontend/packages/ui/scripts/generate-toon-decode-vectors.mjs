#!/usr/bin/env node
/**
 * Generates packages/openmates-rust/src/toon_decode_ts_vectors.json: TS-generated
 * parity vectors for the shared Rust TOON decoder (openmates_sdk::toon_decode).
 *
 * Every vector is an input string plus what the pinned `@toon-format/toon`
 * (frontend/packages/ui/package.json) `decode(input, { strict: false })` returns:
 * `{ json: JSON.stringify(result) }`, or `{ error: true }` when it throws. That is
 * the exact call embedStore.ts / chatSyncServiceHandlersAI.ts make.
 * The Rust tests (toon_decode_tests.rs) replay the file and compare JSON text
 * byte for byte; rustCore/__tests__/toonDecodeVectors.test.ts re-runs the TS
 * decoder over the committed inputs so drift fails CI.
 *
 * Usage: node generate-toon-decode-vectors.mjs [path-to-toon-dist-index.mjs] > out.json
 * (default module specifier: '@toon-format/toon').
 */
import { pathToFileURL } from 'node:url';

const specifier = process.argv[2] ? pathToFileURL(process.argv[2]).href : '@toon-format/toon';
const { decode, encode } = await import(specifier);

/** Realistic embed contents, encoded by the same library the backend format follows. */
const encoded = {
	web_search: {
		app_id: 'web', skill_id: 'search', query: 'best espresso machines 2026', provider: 'Brave Search',
		embed_ref: 'espresso-machines-k8D', status: 'finished',
		results: [
			{ title: 'Top 10 Espresso Machines', url: 'https://example.com/a?x=1,2', description: 'Reviewed: "Gaggia", Breville & more', page_age: '2 days ago', rank: 1 },
			{ title: 'Espresso: a guide', url: 'https://example.org/b', description: 'Pressure 9 bar, 93°C water', page_age: null, rank: 2 }
		],
		embed_ids: ['e1', 'e2', 'e3']
	},
	nested_results: {
		app_id: 'travel', skill_id: 'search_connections',
		results: [
			{ id: 'r1', legs: [{ from: 'BER', to: 'LHR', stops: 0 }, { from: 'LHR', to: 'JFK', stops: 1 }], price: { amount: 412.5, currency: 'EUR' } },
			{ id: 'r2', legs: [], price: { amount: -0, currency: 'EUR' }, tags: ['cheap', 'night'] }
		]
	},
	strings: {
		comma: 'a,b,c', colon: 'key: value', quote: 'say "hi"', backslash: 'C:\\path\\x', newline: 'line1\nline2\r\nline3',
		tab: 'a\tb', unicode: 'Grüße 日本語 😀', emoji_only: '🎉', looks_number: '42', looks_bool: 'true', looks_null: 'null',
		leading_space: '  padded  ', empty: '', dash: '- not a list', hash: '#hashtag', bracket: '[1]', brace: '{x}',
		control: 'bell\u0007end', nbsp: '\u00a0nbsp'
	},
	numbers: {
		int: 42, neg: -17, zero: 0, float: 3.14159, small: 1e-7, big: 1e21, bigint_like: 9007199254740993, exp: 2.5e10,
		tiny_neg: -0.000001, max: Number.MAX_SAFE_INTEGER, huge: 1.7976931348623157e308, fraction: 0.1
	},
	misc: { t: true, f: false, n: null, empty_obj: {}, empty_arr: [], nested: { deeper: { deepest: 'x', list: [1, 'two', true, null] } } },
	numeric_keys: { '10': 'ten', b: 'bee', '2': 'two', a: 'ay', '01': 'leading zero', '4294967295': 'not index', '-1': 'neg' },
	mixed_list: { items: [1, { a: 1, b: [2, 3] }, [4, 5], 'six', [], {}, [{ x: 1 }, { x: 2 }]] },
	array_of_arrays: { matrix: [[1, 2], [3, 4], ['a', 'b,c']] },
	code_embed: { language: 'python', filename: 'main.py', code: 'def f(x):\n    return x * 2\n\n# comment\nprint(f(3))\n', line_count: 5 },
	root_array_objects: [{ id: 1, name: 'a' }, { id: 2, name: 'b' }],
	root_primitive_array: [1, 'a', true, null],
	root_string: 'hello world',
	root_number: 12.5,
	root_empty_array: [],
	root_empty_object: {}
};

/** Hand-written and malformed inputs (non-strict leniency and hard failures). */
const raw = {
	empty_input: '',
	only_blank_lines: '\n\n  \n',
	only_comment: '# just a comment',
	comment_lines: '# header\na: 1\n# middle\nb: 2',
	bom_prefix: '\ufeffa: 1',
	crlf_lines: 'a: 1\r\nb: two\r\n',
	trailing_spaces: 'a: 1   \nb: x  ',
	tab_indent_nonstrict: 'a:\n\tb: 1\n\tc: 2',
	mixed_tab_space_indent: 'a:\n \tb: 1',
	odd_indent_nonstrict: 'a:\n   b: 1\n   c: 2',
	depth_jump_nonstrict: 'a:\n      b: 1',
	over_indented_sibling: 'a:\n  b: 1\n    c: 2',
	over_indented_root: '  a: 1',
	over_indented_second_root: 'a: 1\n  b: 2',
	length_mismatch_inline: 'tags[3]: a,b',
	length_mismatch_tabular: 'rows[3]{id,name}:\n  1,a\n  2,b',
	length_mismatch_list: 'items[1]:\n  - a\n  - b\n  - c',
	extra_tabular_rows: 'rows[1]{id}:\n  1\n  2\n  3',
	tabular_cell_count_mismatch: 'rows[2]{id,name}:\n  1,a\n  2',
	tabular_then_key: 'rows[2]{id,name}:\n  1,a\n  2,b\nnext: 3',
	tabular_row_with_colon: 'rows[2]{id,url}:\n  1,"http://x"\n  2,b: c',
	blank_line_in_tabular: 'rows[2]{id}:\n  1\n\n  2',
	blank_line_in_list: 'items[2]:\n  - a\n\n  - b',
	unterminated_quote_value: 'a: "abc',
	unterminated_quote_key: '"abc: 1',
	chars_after_quote: 'a: "abc"def',
	bad_escape: 'a: "x\\qy"',
	unicode_escape: 'a: "caf\\u00e9"',
	lone_surrogate_escape: 'a: "\\ud83d"',
	truncated_unicode_escape: 'a: "\\u12"',
	quoted_key_spaces: '"my key"   : 5',
	quoted_key_no_colon: '"my key" 5',
	duplicate_keys_nonstrict: 'a: 1\nb: 2\na: 3',
	duplicate_field_names: 'rows[1]{a,a}:\n  1,2',
	missing_colon_root_multi: 'abc\ndef',
	root_primitive_quoted: '"quoted root"',
	root_primitive_number: '-0',
	root_primitive_bool: 'false',
	root_bracket_empty: '[]',
	root_bracket_empty_then_more: '[]\na: 1',
	root_header_then_more: '[2]: 1,2\nx: 1',
	inline_empty_values: 'a[3]: ,,',
	inline_spaces: 'a[2]:   x  ,  y  ',
	pipe_delimiter: 'a[3|]: x|y,z|w',
	tab_delimiter: 'rows[2\t]{id\tname}:\n  1\tAda, Lovelace\n  2\tBob',
	header_delimiter_mismatch: 'rows[2|]{id,name}:\n  1|a\n  2|b',
	invalid_length: 'a[01]: x',
	invalid_length_word: 'a[n]: x',
	unterminated_bracket: 'a[2: x,y',
	whitespace_before_bracket: 'a [2]: x,y',
	content_after_fields_colon: 'rows[1]{id}: 1',
	keyed_header: 'users[2:]{age,city}:\n  ada: 36,London\n  bob: 41,Paris',
	keyed_header_nested_fields: 'm[1:]{a{b,c},d}:\n  k: 1,2,3',
	keyed_header_without_fields: 'm[1:]:\n  k: 1',
	keyed_cell_mismatch: 'm[1:]{a,b}:\n  k: 1',
	nested_field_group: 'rows[1]{id,pos{x,y}}:\n  7,1.5,-2',
	list_dash_alone: 'items[2]:\n  -\n  - x',
	list_item_object_siblings: 'items[1]:\n  - a: 1\n    b: 2\n    c:\n      d: 3',
	list_item_header_first: 'items[1]:\n  - rows[2]{id}:\n      1\n      2\n    name: x',
	list_item_nested_array: 'items[2]:\n  - [2]: a,b\n  - []',
	list_item_keyless_fields: 'items[1]:\n  - [1]{a}:\n    1',
	list_item_extra_spaces: 'items[1]:\n  -    spaced: 1',
	keyless_header_nested: 'a:\n  [2]: 1,2',
	numbers_edge: 'a: 007\nb: 1e400\nc: -1e-400\nd: 1.0\ne: 1E3\nf: .5\ng: 5.\nh: +1\ni: 0x10\nj: 1_000',
	empty_object_value: 'a:\nb: 1',
	nested_empty_object: 'a:\n  b:\n  c: 2',
	list_array_no_items: 'items[2]:\nnext: 1',
	hash_inside_nested: 'a:\n  #not comment? b: 1\n  c: 2',
	proto_key: '__proto__: 1\nconstructor: 2',
	unquoted_key_with_quote: 'a"b:c": 1',
	value_with_brackets: 'a: [x]: y',
	colon_in_unquoted_value: 'url: https://example.com:8080/x',
	deep_nesting: 'a:\n  b:\n    c:\n      d:\n        e: deep',
	key_with_unicode: 'größe: 5\n日本: 語',
	root_list_without_header: '- a\n- b'
};

const vectors = [];
const record = (name, input) => {
	try {
		vectors.push({ name, input, json: JSON.stringify(decode(input, { strict: false })) });
	} catch {
		vectors.push({ name, input, error: true });
	}
};
for (const [name, value] of Object.entries(encoded)) record(`encoded_${name}`, encode(value));
for (const [name, input] of Object.entries(raw)) record(name, input);

process.stdout.write(`${JSON.stringify({
	source: 'scripts/generate-toon-decode-vectors.mjs',
	library: '@toon-format/toon@4.4.0',
	call: 'decode(input, { strict: false })',
	vectors
}, null, '\t')}\n`);
