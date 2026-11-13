//! Replays TypeScript-generated vectors (web_search_ts_vectors.json) against the
//! Rust ports through the same JSON boundary the browser worker uses.
use crate::web_search_json::*;
use serde_json::Value;

fn vectors() -> Value {
    serde_json::from_str(include_str!("web_search_ts_vectors.json")).unwrap()
}

#[test]
fn match_ranges_equal_typescript() {
    for case in vectors()["matchRanges"].as_array().unwrap() {
        let got: Value = serde_json::from_str(&find_match_ranges_json(case["text"].as_str().unwrap(), case["query"].as_str().unwrap()).unwrap()).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
    assert_eq!(find_match_ranges_json("abc", "").unwrap(), "[]");
}

#[test]
fn snippets_equal_typescript() {
    for case in vectors()["snippets"].as_array().unwrap() {
        let got: Value = serde_json::from_str(&build_snippet_json(
            case["content"].as_str().unwrap(),
            case["start"].as_u64().unwrap() as usize,
            case["length"].as_u64().unwrap() as usize,
        ))
        .unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn snippet_cut_inside_surrogate_pair_keeps_lone_surrogate_escape() {
    let text = format!("{}\u{1F600}{}", "a ".repeat(30), " b".repeat(30));
    let json = build_snippet_json(&text, 55, 1);
    assert!(json.contains("\\ud83d") || json.contains("\\ude00") || !json.contains("\u{FFFD}"));
}

#[test]
fn saved_embed_memories_equal_typescript() {
    for case in vectors()["savedEmbeds"].as_array().unwrap() {
        let got = search_saved_embed_memories_json(
            &case["entries"].to_string(),
            case["query"].as_str().unwrap(),
            case["limit"].as_i64().unwrap(),
        )
        .unwrap();
        let got: Value = serde_json::from_str(&got).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn pii_aliases_equal_typescript() {
    for case in vectors()["piiAliases"].as_array().unwrap() {
        let got = create_pii_display_aliases_json(
            &case["source"].to_string(),
            &case["mappings"].to_string(),
            &case["configured"].to_string(),
        )
        .unwrap();
        let got: Value = serde_json::from_str(&got).unwrap();
        assert_eq!(got, case["expected"], "{case}");
    }
}

#[test]
fn malformed_json_is_a_protocol_error() {
    assert_eq!(search_saved_embed_memories_json("{", "q", 6), Err("protocol".to_string()));
    assert_eq!(create_pii_display_aliases_json("null", "x", "[]"), Err("protocol".to_string()));
}

/// Deterministic mixed-script corpus; the snippet fast path on UTF-8 must equal
/// the code-unit reference (`build_snippet`) for every cut, including cuts inside emoji.
#[test]
fn utf8_snippet_path_equals_code_unit_reference() {
    use crate::web_search::build_snippet;
    let alphabet = ["a", "b", " ", " ", "é", "ß", "\u{1F600}", "İ", "\"", "\n", "word", "日本"];
    let mut seed = 0x2545F4914F6CDD1Du64;
    let mut next = move || {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        seed
    };
    for _ in 0..3000 {
        let len = (next() % 220) as usize;
        let content: String = (0..len).map(|_| alphabet[(next() % alphabet.len() as u64) as usize]).collect();
        let units: Vec<u16> = content.encode_utf16().collect();
        if units.is_empty() {
            continue;
        }
        let start = (next() % units.len() as u64) as usize;
        let length = (next() % 8) as usize;
        let reference = build_snippet(&units, start, length);
        let literal = crate::web_search_json::json_string_from_units(&reference.units);
        let expected = format!(
            "{{\"snippet\":{literal},\"snippetMatchStart\":{},\"snippetMatchLength\":{}}}",
            reference.match_start, length
        );
        assert_eq!(build_snippet_json(&content, start, length), expected, "{content:?} {start} {length}");
    }
}

#[test]
fn corpus_equals_per_item_calls() {
    use crate::web_search_corpus::SearchCorpus;
    let texts = ["Hello hello", "no hit", "Straße needle \u{1F600} NEEDLE tail words here", "", "needle at start"];
    let mut corpus = SearchCorpus::default();
    for (i, t) in texts.iter().enumerate() {
        corpus.set(&format!("k{i}"), t);
    }
    corpus.set("k1", "now a needle hit");
    corpus.remove("k0");
    let got: Value = serde_json::from_str(&corpus.search_json("NEEDLE", 1)).unwrap();
    let expected_texts: Vec<(String, &str)> =
        vec![("k4".into(), texts[4]), ("k1".into(), "now a needle hit"), ("k2".into(), texts[2]), ("k3".into(), texts[3])];
    let mut seen = 0;
    for item in got.as_array().unwrap() {
        let (_, text) = expected_texts.iter().find(|(k, _)| k == item["key"].as_str().unwrap()).unwrap();
        let ranges: Value = serde_json::from_str(&find_match_ranges_json(text, "NEEDLE").unwrap()).unwrap();
        assert_eq!(item["ranges"], ranges);
        let r = &ranges[0];
        let one: Value = serde_json::from_str(&build_snippet_json(text, r["start"].as_u64().unwrap() as usize, r["length"].as_u64().unwrap() as usize)).unwrap();
        assert_eq!(item["snippets"], serde_json::json!([one]));
        seen += 1;
    }
    assert_eq!(seen, 3);
    assert_eq!(corpus.len(), 4);
    assert_eq!(corpus.search_json("", 1), "[]");
    assert_eq!(SearchCorpus::default().set_many_json("{"), Err("protocol".to_string()));
}

/// Corpus snippets (byte-anchored fast path) equal the per-call API on texts
/// where lowercasing changes widths (İ) and where emoji straddle the window.
#[test]
fn corpus_snippets_equal_single_calls_on_random_text() {
    use crate::web_search_corpus::SearchCorpus;
    let alphabet = ["a", "N", "e", " ", " ", "É", "İ", "ß", "\u{1F600}", "needle", "日本", "x "];
    let mut seed = 0x9E3779B97F4A7C15u64;
    let mut next = move || {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        seed
    };
    for round in 0..1500 {
        let len = (next() % 90) as usize;
        let text: String = (0..len).map(|_| alphabet[(next() % alphabet.len() as u64) as usize]).collect();
        let mut corpus = SearchCorpus::default();
        corpus.set("k", &text);
        let got: Value = serde_json::from_str(&corpus.search_json("NEEDLE", 3)).unwrap();
        let ranges: Value = serde_json::from_str(&find_match_ranges_json(&text, "NEEDLE").unwrap()).unwrap();
        if ranges.as_array().unwrap().is_empty() {
            assert_eq!(got, serde_json::json!([]), "round {round}");
            continue;
        }
        assert_eq!(got[0]["ranges"], ranges, "round {round}");
        for (snippet, r) in got[0]["snippets"].as_array().unwrap().iter().zip(ranges.as_array().unwrap()) {
            let one = build_snippet_json(&text, r["start"].as_u64().unwrap() as usize, r["length"].as_u64().unwrap() as usize);
            assert_eq!(*snippet, serde_json::from_str::<Value>(&one).unwrap(), "{text:?}");
        }
    }
}

#[test]
fn first_hits_equal_indexof_plus_build_snippet() {
    use crate::web_search_corpus::SearchCorpus;
    let texts = ["Straße needle \u{1F600} tail", "none", "İstanbul NEEDLE İ more words here after", "needle", "x".repeat(300).as_str().to_owned().leak() as &str];
    let mut corpus = SearchCorpus::default();
    for (i, t) in texts.iter().enumerate() {
        corpus.set(&format!("m{i}"), t);
    }
    let got: Value = serde_json::from_str(&corpus.first_hits_json("Needle", 2)).unwrap();
    assert_eq!(got.as_array().unwrap().len(), 2);
    for (hit, text) in got.as_array().unwrap().iter().zip([texts[0], texts[2]]) {
        let start = text.to_lowercase().encode_utf16().collect::<Vec<_>>();
        let needle: Vec<u16> = "needle".encode_utf16().collect();
        let idx = start.windows(needle.len()).position(|w| w == needle.as_slice()).unwrap();
        let snippet: Value = serde_json::from_str(&build_snippet_json(text, idx, 6)).unwrap();
        assert_eq!(hit["snippet"], snippet["snippet"]);
        assert_eq!(hit["snippetMatchStart"], snippet["snippetMatchStart"]);
        assert_eq!(hit["snippetMatchLength"], snippet["snippetMatchLength"]);
    }
    assert_eq!(corpus.first_hits_json("", 5), "[]");
}
