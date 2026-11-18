//! Progressive SVG for the Apple shell: repairs SVG source that is still
//! streaming into a renderable document. The core
//! (`client::progressive_svg`, port of web `progressiveSvg.ts`) owns the
//! logic; this module only marshals. Pure function, no `ViewModelCore` state.

/// The SVG document to draw for `source`, or `None` to keep the last good
/// frame (no complete root `<svg>` open tag yet, or blank complete source).
/// `complete` is false while the code embed streams.
#[uniffi::export]
pub fn progressive_svg(source: String, complete: bool) -> Option<String> {
    openmates_sdk::client::progressive_svg::progressive_svg(&source, complete)
}

#[cfg(test)]
mod tests {
    //! The binding forwards to the core repair.
    use super::progressive_svg;

    #[test]
    fn streams_a_partial_document_and_passes_a_complete_one() {
        assert_eq!(
            progressive_svg("<svg><g><rect".into(), false).as_deref(),
            Some("<svg><g></g></svg>")
        );
        assert_eq!(
            progressive_svg("<svg/>".into(), true).as_deref(),
            Some("<svg/>")
        );
    }
}
