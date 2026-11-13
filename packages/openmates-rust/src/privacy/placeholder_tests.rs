//! Equivalence of the placeholder scanners with the regex patterns they replaced.
use super::{find, is_generated, is_token};
use regex::Regex;

fn corpus() -> Vec<String> {
    let mut texts: Vec<String> = [
        "",
        "[",
        "]",
        "[]",
        "[a]",
        "[A1_]",
        "[1a]",
        "[_a]",
        "[a-b]",
        "[[a]]",
        "[a][b]",
        "x[ab]y[cd",
        "[ab",
        "ab]",
        "[a b]",
        "[ä]",
        "ä[ab]ö",
        "[OM_PII_0123456789ABCDEF0123456789ABCDEF]",
        "[OM_PII_0123456789abcdef0123456789ABCDEF]",
        "[OM_PII_0123456789ABCDEF0123456789ABCDE]",
        "[OM_PII_0123456789ABCDEF0123456789ABCDEF0]",
        "[EMAIL_1_ab] and [PHONE_22_x]",
        "[a]\n",
        "\n[a]",
        "[a\n]",
        "[[[[x]",
        "🙂[x]🙂[y_1]",
        "[a]]",
        "[[a]",
    ]
    .iter()
    .map(|text| text.to_string())
    .collect();
    // Deterministic pseudo-random strings over the grammar's alphabet.
    let alphabet = [
        '[', ']', 'a', 'Z', '0', '9', '_', ' ', '-', 'é', '\n', 'O', 'M', 'P', 'I', 'F',
    ];
    let mut state: u64 = 0x9E37_79B9_7F4A_7C15;
    for _ in 0..4000 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        let length = (state % 24) as usize;
        texts.push(
            (0..length)
                .map(|index| {
                    alphabet[((state >> (index % 60)) as usize + index * 7) % alphabet.len()]
                })
                .collect(),
        );
    }
    texts
}

#[test]
fn scanners_match_the_former_patterns() {
    let find_pattern = Regex::new(r"\[[A-Za-z][A-Za-z0-9_]*\]").unwrap();
    let token_pattern = Regex::new(r"^\[[A-Za-z][A-Za-z0-9_]*\]$").unwrap();
    let generated_pattern = Regex::new(r"^\[OM_PII_[A-F0-9]{32}\]$").unwrap();
    for text in corpus() {
        let expected: Vec<(usize, usize)> = find_pattern
            .find_iter(&text)
            .map(|m| (m.start(), m.end()))
            .collect();
        assert_eq!(find(&text).collect::<Vec<_>>(), expected, "find {text:?}");
        assert_eq!(
            is_token(&text),
            token_pattern.is_match(&text),
            "is_token {text:?}"
        );
        assert_eq!(
            is_generated(&text),
            generated_pattern.is_match(&text),
            "is_generated {text:?}"
        );
    }
}
