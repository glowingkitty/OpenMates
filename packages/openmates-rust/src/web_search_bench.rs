//! Native timing of the search ports on the same inputs as the TypeScript
//! timing test (searchPiiVectors.test.ts). Runs only with OPENMATES_SEARCH_BENCH=1 in
//! release mode (the SDK unit gate forbids ignored tests, so it is gated by env instead).
use crate::web_search_json::*;
use std::hint::black_box;
use std::time::Instant;

fn long() -> String {
    "The quick brown fox jumps over the lazy dog. ".repeat(8)
        + "Needle in a haystack with \u{1F600} emoji and Straße, İstanbul. "
        + &"tail words follow here ".repeat(6)
}

fn ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

#[test]
fn web_search_bench_native() {
    if std::env::var_os("OPENMATES_SEARCH_BENCH").is_none() {
        return;
    }
    let long = long();
    let text = long.repeat(200);
    let t0 = Instant::now();
    for _ in 0..200 {
        black_box(find_match_ranges_json(black_box(&text), "needle").unwrap());
    }
    let match_ms = ms(t0);
    let t1 = Instant::now();
    for _ in 0..20000 {
        black_box(build_snippet_json(black_box(&long), 400, 6));
    }
    let snippet_ms = ms(t1);
    let items: Vec<String> = (0..2000)
        .map(|i| format!(r#"{{"id":"{i}","item_value":[["embed_id","e{i}"],["title","Design item {i}"],["location","Berlin"]],"updated_at":{i}}}"#))
        .collect();
    let entries = format!(r#"[["app",[["g",[{}]]]]]"#, items.join(","));
    let t2 = Instant::now();
    for _ in 0..20 {
        black_box(search_saved_embed_memories_json(black_box(&entries), "design", 6).unwrap());
    }
    let memories_ms = ms(t2);
    let mut corpus = crate::web_search_corpus::SearchCorpus::default();
    for i in 0..500 {
        let head = if i % 3 == 0 { format!("ascii filler text number {i} ") } else { format!("Gespräch Nr. {i} \u{1F600} ") };
        corpus.set(&format!("m{i}"), &(head.repeat(12) + "needle " + &"more words after the hit ".repeat(6)));
    }
    let t3 = Instant::now();
    for _ in 0..20 {
        black_box(corpus.search_json(black_box("needle"), 1));
    }
    let corpus_ms = ms(t3);
    println!("RUST_CORPUS_MS {corpus_ms:.2}");
    println!("RUST_TIMINGS_MS match={match_ms:.2} snippet={snippet_ms:.2} memories={memories_ms:.2}");
}
