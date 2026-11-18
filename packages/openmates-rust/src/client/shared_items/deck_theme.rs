//! Deck theme (fonts and six colour tokens) and the deck kind (deck or template).
//! Shared client core; mirrors the "Themes and templates" section of
//! `docs/architecture/apps/slides-format.md` and the Python normaliser
//! (`backend/shared/python_utils/slides_markup.py`). Spec: `slides.templates.*`.

use super::deck_values::{SAFE_FONTS, escape_attr};
use serde::{Deserialize, Serialize};

/// Whether a slides document is a presentation or a reusable template.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DeckKind {
    /// A presentation (the default; never written to the markup).
    #[default]
    Deck,
    /// A template: same grammar, `kind="template"` on the root.
    Template,
}

/// Fonts and colours a deck or template overrides; renderers fall back to Plain per
/// missing value. Serialised as one self-closing `<theme .../>` line.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeckTheme {
    /// Heading font (canonical safe font name).
    #[serde(default)]
    pub heading: Option<String>,
    /// Body font (canonical safe font name).
    #[serde(default)]
    pub body: Option<String>,
    /// Page background colour (`#hex`, lower case).
    #[serde(default)]
    pub background: Option<String>,
    /// Default text colour.
    #[serde(default)]
    pub foreground: Option<String>,
    /// Primary accent colour.
    #[serde(default)]
    pub accent: Option<String>,
    /// Secondary accent colour (markup attribute `accent-2`).
    #[serde(default)]
    pub accent_2: Option<String>,
    /// Muted text colour.
    #[serde(default)]
    pub muted: Option<String>,
    /// Card/panel surface colour.
    #[serde(default)]
    pub surface: Option<String>,
}

/// Markup attribute names in their serialised order.
pub(crate) const THEME_ATTRIBUTES: [&str; 8] = [
    "heading",
    "body",
    "background",
    "foreground",
    "accent",
    "accent-2",
    "muted",
    "surface",
];

impl DeckTheme {
    fn slots(&self) -> [&Option<String>; 8] {
        [
            &self.heading,
            &self.body,
            &self.background,
            &self.foreground,
            &self.accent,
            &self.accent_2,
            &self.muted,
            &self.surface,
        ]
    }

    /// `(markup attribute, value)` pairs that are set, in serialised order.
    pub(crate) fn entries(&self) -> Vec<(&'static str, &str)> {
        THEME_ATTRIBUTES
            .iter()
            .zip(self.slots())
            .filter_map(|(name, value)| value.as_deref().map(|value| (*name, value)))
            .collect()
    }

    /// Builds a theme from `(attribute, value)` pairs that are already valid.
    pub(crate) fn from_entries<'a>(pairs: impl IntoIterator<Item = (&'a str, String)>) -> Self {
        let mut theme = Self::default();
        for (name, value) in pairs {
            let slot = match name {
                "heading" => &mut theme.heading,
                "body" => &mut theme.body,
                "background" => &mut theme.background,
                "foreground" => &mut theme.foreground,
                "accent" => &mut theme.accent,
                "accent-2" => &mut theme.accent_2,
                "muted" => &mut theme.muted,
                "surface" => &mut theme.surface,
                _ => continue,
            };
            *slot = Some(value);
        }
        theme
    }

    /// The theme with every value cleaned like the normaliser (fonts to canonical
    /// spelling, hex to lower case); invalid values are dropped. `None` when nothing
    /// valid remains.
    pub(crate) fn cleaned(&self) -> Option<Self> {
        let cleaned = Self::from_entries(
            self.entries()
                .into_iter()
                .filter_map(|(name, raw)| clean_theme_value(name, raw).map(|value| (name, value))),
        );
        (!cleaned.entries().is_empty()).then_some(cleaned)
    }

    /// True when every set value is already in canonical form and at least one is set.
    pub(crate) fn is_canonical(&self) -> bool {
        !self.entries().is_empty()
            && self
                .entries()
                .into_iter()
                .all(|(name, raw)| clean_theme_value(name, raw).as_deref() == Some(raw))
    }

    /// The `  <theme .../>` line including the newline.
    pub(crate) fn line(&self) -> String {
        let mut out = String::from("  <theme");
        for (name, value) in self.entries() {
            out.push_str(&format!(" {name}=\"{}\"", escape_attr(value)));
        }
        out.push_str("/>\n");
        out
    }
}

/// One theme value after the normaliser's cleaning: `heading`/`body` map to the
/// canonical safe font spelling (case-insensitive), colours to lower-case `#hex` with 3
/// or 6 digits.
pub(crate) fn clean_theme_value(name: &str, raw: &str) -> Option<String> {
    let value = raw.trim();
    if name == "heading" || name == "body" {
        let lower = value.to_lowercase();
        return SAFE_FONTS
            .iter()
            .find(|font| font.to_lowercase() == lower)
            .map(|font| (*font).to_string());
    }
    let hex = value.strip_prefix('#')?;
    (matches!(hex.len(), 3 | 6) && hex.bytes().all(|b| b.is_ascii_hexdigit()))
        .then(|| value.to_lowercase())
}
