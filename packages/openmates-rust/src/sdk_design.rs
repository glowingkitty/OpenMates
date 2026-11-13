//! API-key Design icon export (npm `client.design.exportIcon`). Only OpenMates
//! sanitized Iconify routes are fetched; Iconify is never contacted directly.
//! PNG rasterization needs a renderer the portable core does not embed, so a PNG
//! request is a typed Unavailable error rather than a silent SVG substitution.
use crate::{Error, OpenMates, Result};
use regex::Regex;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IconFormat {
    Svg,
    Png,
}
#[derive(Clone, Default)]
pub struct IconExportOptions {
    pub svg_path: Option<String>,
    pub prefix: Option<String>,
    pub name: Option<String>,
    pub format: Option<IconFormat>,
    pub color: Option<String>,
    pub palette: bool,
    pub allow_palette_recolor: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IconExport {
    pub format: IconFormat,
    pub content_type: &'static str,
    pub svg: String,
    pub svg_path: String,
    pub data: Vec<u8>,
}

fn segment() -> Regex {
    Regex::new(r"^(?i)[a-z0-9][a-z0-9._-]*$").expect("static expression")
}
fn path_pattern() -> Regex {
    Regex::new(
        r"^(?i)/v1/apps/design/icons/iconify/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*\.svg$",
    )
    .expect("static expression")
}

pub fn resolve_icon_svg_path(options: &IconExportOptions) -> Result<String> {
    if let Some(path) = &options.svg_path {
        let trimmed = path.trim();
        if !path_pattern().is_match(trimmed) {
            return Err(Error::Invalid(
                "svgPath must be an OpenMates Design Iconify SVG path",
            ));
        }
        return Ok(trimmed.to_owned());
    }
    let prefix = options.prefix.as_deref().map(str::trim).unwrap_or("");
    let name = options.name.as_deref().map(str::trim).unwrap_or("");
    if prefix.is_empty() || name.is_empty() {
        return Err(Error::Invalid(
            "Provide either svgPath or both prefix and name",
        ));
    }
    let pattern = segment();
    if !pattern.is_match(prefix) || !pattern.is_match(name) {
        return Err(Error::Invalid(
            "Icon prefix and name may contain only letters, numbers, dots, underscores, and dashes",
        ));
    }
    Ok(format!("/v1/apps/design/icons/iconify/{prefix}/{name}.svg"))
}

pub fn normalize_icon_color(color: Option<&str>) -> Result<Option<String>> {
    let Some(color) = color else { return Ok(None) };
    let trimmed = color.trim();
    let hex = Regex::new(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
        .expect("static expression");
    if !hex.is_match(trimmed) {
        return Err(Error::Invalid(
            "Icon color must be a hex color such as #111827",
        ));
    }
    Ok(Some(trimmed.to_owned()))
}

pub fn apply_icon_color(svg: &str, color: Option<&str>) -> String {
    let Some(color) = color else {
        return svg.to_owned();
    };
    let current = Regex::new(r"\bcurrentColor\b").expect("static expression");
    let recolored = current
        .replace_all(svg, regex::NoExpand(color))
        .into_owned();
    let open = Regex::new(r"(?i)<svg\b([^>]*)>").expect("static expression");
    let Some(found) = open.captures(&recolored) else {
        return recolored;
    };
    let whole = found.get(0).expect("whole match");
    let attrs = &found[1];
    let existing =
        Regex::new(r#"(?i)\scolor\s*=\s*(?:"[^"]*"|'[^']*')"#).expect("static expression");
    let replaced = if Regex::new(r"\scolor\s*=")
        .expect("static expression")
        .is_match(attrs)
    {
        existing
            .replace(
                whole.as_str(),
                regex::NoExpand(&format!(" color=\"{color}\"")),
            )
            .into_owned()
    } else {
        format!("<svg{attrs} color=\"{color}\">")
    };
    format!(
        "{}{}{}",
        &recolored[..whole.start()],
        replaced,
        &recolored[whole.end()..]
    )
}

pub struct Design<'a> {
    client: &'a OpenMates,
}
impl<'a> Design<'a> {
    pub(crate) fn new(client: &'a OpenMates) -> Self {
        Self { client }
    }
    pub async fn export_icon(&self, options: IconExportOptions) -> Result<IconExport> {
        let svg_path = resolve_icon_svg_path(&options)?;
        let format = options.format.unwrap_or(IconFormat::Svg);
        let color = normalize_icon_color(options.color.as_deref())?;
        if color.is_some() && options.palette && !options.allow_palette_recolor {
            return Err(Error::Invalid(
                "Palette icons cannot be recolored unless allowPaletteRecolor is true",
            ));
        }
        if format == IconFormat::Png {
            return Err(Error::Unavailable {
                code: "design_png_unavailable",
                reason: "PNG rendering is not available in the Rust SDK core; export SVG.",
            });
        }
        let raw = self.client.get_raw(&svg_path).await?;
        let svg = apply_icon_color(&String::from_utf8_lossy(&raw.data), color.as_deref());
        Ok(IconExport {
            format,
            content_type: "image/svg+xml",
            data: svg.clone().into_bytes(),
            svg,
            svg_path,
        })
    }
}
impl OpenMates {
    pub fn design(&self) -> Design<'_> {
        Design::new(self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ClientOptions, SdkCredentials, SdkOptions};
    fn opts(prefix: &str, name: &str) -> IconExportOptions {
        IconExportOptions {
            prefix: Some(prefix.into()),
            name: Some(name.into()),
            ..Default::default()
        }
    }
    #[test]
    fn path_resolution_matches_npm() {
        assert_eq!(
            resolve_icon_svg_path(&opts("lucide", "a-b.c")).unwrap(),
            "/v1/apps/design/icons/iconify/lucide/a-b.c.svg"
        );
        assert!(resolve_icon_svg_path(&opts("../x", "y")).is_err());
        assert!(resolve_icon_svg_path(&IconExportOptions::default()).is_err());
        let ok = IconExportOptions {
            svg_path: Some(" /v1/apps/design/icons/iconify/mdi/home.svg ".into()),
            ..Default::default()
        };
        assert_eq!(
            resolve_icon_svg_path(&ok).unwrap(),
            "/v1/apps/design/icons/iconify/mdi/home.svg"
        );
        let bad = IconExportOptions {
            svg_path: Some("/v1/apps/design/icons/iconify/mdi/../home.svg".into()),
            ..Default::default()
        };
        assert!(resolve_icon_svg_path(&bad).is_err());
    }
    #[test]
    fn color_validation_and_application() {
        assert_eq!(
            normalize_icon_color(Some(" #abc ")).unwrap().as_deref(),
            Some("#abc")
        );
        assert!(normalize_icon_color(Some("red")).is_err());
        assert_eq!(
            apply_icon_color(
                "<svg a=\"1\"><path fill=\"currentColor\"/></svg>",
                Some("#111")
            ),
            "<svg a=\"1\" color=\"#111\"><path fill=\"#111\"/></svg>"
        );
        assert_eq!(
            apply_icon_color("<svg color=\"#000\">", Some("#fff")),
            "<svg color=\"#fff\">"
        );
        assert_eq!(apply_icon_color("<svg>", None), "<svg>");
    }
    #[tokio::test]
    async fn validation_precedes_transport_and_png_is_typed_unavailable() {
        let anon = OpenMates::new(SdkOptions {
            api_url: "http://127.0.0.1:1".into(),
            credentials: SdkCredentials::Anonymous {
                anonymous_id: "synthetic-design-anon".into(),
            },
            device_id: "synthetic-design-device".into(),
            client_options: ClientOptions::default(),
        })
        .unwrap();
        assert!(matches!(
            anon.design()
                .export_icon(IconExportOptions::default())
                .await,
            Err(Error::Invalid(_))
        ));
        let mut png = opts("lucide", "home");
        png.format = Some(IconFormat::Png);
        assert!(matches!(
            anon.design().export_icon(png).await,
            Err(Error::Unavailable { .. })
        ));
        let mut palette = opts("lucide", "home");
        palette.color = Some("#fff".into());
        palette.palette = true;
        assert!(matches!(
            anon.design().export_icon(palette).await,
            Err(Error::Invalid(_))
        ));
        assert_eq!(
            anon.design().export_icon(opts("lucide", "home")).await,
            Err(Error::Authentication)
        );
    }
}
