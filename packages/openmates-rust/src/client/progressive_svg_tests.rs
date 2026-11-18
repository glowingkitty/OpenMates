use super::{build_progressive_svg as build, progressive_svg};

#[test]
fn none_before_a_complete_svg_open_tag() {
    assert_eq!(build(""), None);
    assert_eq!(build("<sv"), None);
    assert_eq!(build("<svg viewBox=\"0 0 10"), None);
}

#[test]
fn closes_the_root_when_only_the_open_tag_arrived() {
    assert_eq!(
        build("<svg viewBox=\"0 0 10 10\">").as_deref(),
        Some("<svg viewBox=\"0 0 10 10\"></svg>")
    );
}

#[test]
fn drops_a_dangling_partial_tag() {
    assert_eq!(
        build("<svg><rect width=\"1\"/><circ").as_deref(),
        Some("<svg><rect width=\"1\"/></svg>")
    );
}

#[test]
fn drops_an_attribute_cut_mid_string_even_with_gt() {
    assert_eq!(
        build("<svg><path d=\"M0 0 L1 1\"/><text x=\"1\" y=\"a>b").as_deref(),
        Some("<svg><path d=\"M0 0 L1 1\"/></svg>")
    );
}

#[test]
fn closes_unclosed_nested_groups_in_order() {
    assert_eq!(
        build("<svg><g id=\"a\"><g id=\"b\"><rect/>").as_deref(),
        Some("<svg><g id=\"a\"><g id=\"b\"><rect/></g></g></svg>")
    );
}

#[test]
fn drops_trailing_partial_text_and_entity() {
    assert_eq!(
        build("<svg><text>Tom &am").as_deref(),
        Some("<svg><text></text></svg>")
    );
}

#[test]
fn ignores_an_unfinished_comment_and_cdata() {
    assert_eq!(
        build("<svg><rect/><!-- note <g>").as_deref(),
        Some("<svg><rect/></svg>")
    );
    assert_eq!(
        build("<svg><rect/><![CDATA[ x").as_deref(),
        Some("<svg><rect/></svg>")
    );
}

#[test]
fn keeps_a_complete_comment_and_does_not_close_self_closing_tags() {
    assert_eq!(
        build("<svg><!-- a > b --><g><use href=\"#x\"/>").as_deref(),
        Some("<svg><!-- a > b --><g><use href=\"#x\"/></g></svg>")
    );
}

#[test]
fn ignores_an_unfinished_style_but_keeps_a_finished_one() {
    assert_eq!(
        build("<svg><rect/><style>.a{fill:red").as_deref(),
        Some("<svg><rect/></svg>")
    );
    assert_eq!(
        build("<svg><style>.a>b{fill:red}</style><g>").as_deref(),
        Some("<svg><style>.a>b{fill:red}</style><g></g></svg>")
    );
}

#[test]
fn a_complete_document_is_unchanged() {
    let doc = "<?xml version=\"1.0\"?><svg><g/></svg>\n";
    assert_eq!(build(doc).as_deref(), Some(doc));
    assert_eq!(build("<svg/>").as_deref(), Some("<svg/>"));
}

#[test]
fn non_ascii_text_is_cut_on_char_boundaries() {
    assert_eq!(
        build("<svg><text>Grüße</text><text>日本").as_deref(),
        Some("<svg><text>Grüße</text><text></text></svg>")
    );
}

#[test]
fn complete_flag_returns_the_source() {
    assert_eq!(
        progressive_svg("<svg><g>", true).as_deref(),
        Some("<svg><g>")
    );
    assert_eq!(progressive_svg("  ", true), None);
    assert_eq!(
        progressive_svg("<svg><g>", false).as_deref(),
        Some("<svg><g></g></svg>")
    );
}
