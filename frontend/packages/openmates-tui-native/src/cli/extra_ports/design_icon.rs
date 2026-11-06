//! `openmates apps design export-icon` (npm handleDesignIconExport +
//! designIcons.ts). The SVG is fetched through the session binary transport
//! or, under an explicit `--api-key`, the shared SDK `design().export_icon`
//! facade; PNG output is rasterized locally with resvg in both cases.
use super::super::{CliError, CliOutput, Invocation, handlers, terminal_text};
use super::failed;
use crate::client::Client;
use regex::Regex;
use serde_json::json;
use std::path::Path;

pub(super) const COMMAND: &str = "apps design export-icon";
const ACCEPT: &str = "image/svg+xml,application/octet-stream";
const DEFAULT_PNG_SIZE: u32 = 256;
const MAX_PNG_SIZE: u32 = 4096;
const FLAGS: &[&str] = &[
    "output",
    "format",
    "color",
    "prefix",
    "name",
    "svg-path",
    "icon",
    "size",
    "width",
    "height",
    "palette",
    "allow-palette-recolor",
];
const USAGE: &str = "Missing --output flag.\n\nUsage:\n  openmates apps design export-icon lucide:home --output home.svg [--color '#111827']\n  openmates apps design export-icon --prefix lucide --name home --format png --size 64 --output home.png\n";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub(super) enum Format {
    Svg,
    Png,
}
impl Format {
    fn label(self) -> &'static str {
        match self {
            Self::Svg => "svg",
            Self::Png => "png",
        }
    }
    fn content_type(self) -> &'static str {
        match self {
            Self::Svg => "image/svg+xml",
            Self::Png => "image/png",
        }
    }
}

fn regex(source: &str) -> Result<Regex, CliError> {
    Regex::new(source).map_err(|_| CliError::Client(crate::error::Error::Protocol))
}
fn segment_valid(value: &str) -> Result<bool, CliError> {
    Ok(regex(r"(?i)^[a-z0-9][a-z0-9._-]*$")?.is_match(value))
}

/// npm `resolveDesignIconSvgPath`.
pub(super) fn svg_path(
    svg_path: Option<&str>,
    prefix: Option<&str>,
    name: Option<&str>,
) -> Result<String, CliError> {
    if let Some(path) = svg_path {
        let trimmed = path.trim();
        let pattern = regex(
            r"(?i)^/v1/apps/design/icons/iconify/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*\.svg$",
        )?;
        if !pattern.is_match(trimmed) {
            return Err(failed(
                "svgPath must be an OpenMates Design Iconify SVG path",
            ));
        }
        return Ok(trimmed.to_owned());
    }
    let (prefix, name) = (
        prefix.map(str::trim).filter(|v| !v.is_empty()),
        name.map(str::trim).filter(|v| !v.is_empty()),
    );
    let (Some(prefix), Some(name)) = (prefix, name) else {
        return Err(failed("Provide either svgPath or both prefix and name"));
    };
    if !segment_valid(prefix)? || !segment_valid(name)? {
        return Err(failed(
            "Icon prefix and name may contain only letters, numbers, dots, underscores, and dashes",
        ));
    }
    Ok(format!("/v1/apps/design/icons/iconify/{prefix}/{name}.svg"))
}

/// npm `normalizeDesignIconColor`.
pub(super) fn normalize_color(color: Option<&str>) -> Result<Option<String>, CliError> {
    let Some(color) = color else { return Ok(None) };
    let trimmed = color.trim();
    if !regex(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")?
        .is_match(trimmed)
    {
        return Err(failed("Icon color must be a hex color such as #111827"));
    }
    Ok(Some(trimmed.to_owned()))
}

/// npm `applyDesignIconColor`.
pub(super) fn apply_color(svg: &str, color: Option<&str>) -> Result<String, CliError> {
    let Some(color) = color else {
        return Ok(svg.to_owned());
    };
    let current = regex(r"\bcurrentColor\b")?.replace_all(svg, regex::NoExpand(color));
    let open = regex(r"(?i)<svg\b([^>]*)>")?;
    let Some(found) = open.captures(&current) else {
        return Ok(current.into_owned());
    };
    let (whole, attrs) = (found.get(0).map(|m| m.range()), found[1].to_owned());
    let replacement = if regex(r"\scolor\s*=")?.is_match(&attrs) {
        regex(r#"(?i)\scolor\s*=\s*(['"])[^'"]*['"]"#)?
            .replace(
                found[0].as_ref(),
                regex::NoExpand(&format!(" color=\"{color}\"")),
            )
            .into_owned()
    } else {
        format!("<svg{attrs} color=\"{color}\">")
    };
    let range = whole.ok_or(CliError::Client(crate::error::Error::Protocol))?;
    Ok(format!(
        "{}{replacement}{}",
        &current[..range.start],
        &current[range.end..]
    ))
}

fn resolve_format(format: Option<Format>, output: &str) -> Format {
    format.unwrap_or_else(|| {
        match Path::new(output)
            .extension()
            .and_then(|e| e.to_str())
            .map(str::to_ascii_lowercase)
            .as_deref()
        {
            Some("png") => Format::Png,
            _ => Format::Svg,
        }
    })
}

fn parse_format(value: Option<&str>) -> Result<Option<Format>, CliError> {
    match value {
        None => Ok(None),
        Some("svg") => Ok(Some(Format::Svg)),
        Some("png") => Ok(Some(Format::Png)),
        Some(_) => Err(failed("--format must be svg or png")),
    }
}

/// npm `parsePositiveIntegerFlag`.
fn positive(i: &Invocation, key: &str) -> Result<Option<u32>, CliError> {
    let Some(value) = i.text(key) else {
        return Ok(None);
    };
    match value.parse::<i64>() {
        Ok(n) if n > 0 && n.to_string() == value => Ok(Some(n.min(i64::from(u32::MAX)) as u32)),
        _ => Err(failed(format!("--{key} must be a positive integer"))),
    }
}

fn png_dimension(value: Option<u32>, label: &str) -> Result<Option<u32>, CliError> {
    match value {
        Some(v) if v > MAX_PNG_SIZE => Err(failed(format!(
            "PNG {label} must be an integer from 1 to {MAX_PNG_SIZE}"
        ))),
        other => Ok(other),
    }
}

/// npm `renderDesignIconPng` (resvg fit-to width/height, width wins).
pub(super) fn render_png(
    svg: &str,
    size: Option<u32>,
    width: Option<u32>,
    height: Option<u32>,
) -> Result<Vec<u8>, CliError> {
    let width = png_dimension(width, "width")?;
    let height = png_dimension(height, "height")?;
    let size = png_dimension(size, "size")?.unwrap_or(DEFAULT_PNG_SIZE);
    let tree = resvg::usvg::Tree::from_str(svg, &resvg::usvg::Options::default())
        .map_err(|error| failed(error.to_string()))?;
    let original = tree.size();
    let (scale, target_w, target_h) = if let Some(w) = width {
        let s = w as f32 / original.width();
        (s, w, (original.height() * s).ceil().max(1.0) as u32)
    } else if let Some(h) = height {
        let s = h as f32 / original.height();
        ((s), (original.width() * s).ceil().max(1.0) as u32, h)
    } else {
        let s = size as f32 / original.width();
        (s, size, (original.height() * s).ceil().max(1.0) as u32)
    };
    let mut pixmap = resvg::tiny_skia::Pixmap::new(target_w, target_h)
        .ok_or_else(|| failed("Could not allocate the PNG canvas"))?;
    resvg::render(
        &tree,
        resvg::tiny_skia::Transform::from_scale(scale, scale),
        &mut pixmap.as_mut(),
    );
    pixmap
        .encode_png()
        .map_err(|error| failed(error.to_string()))
}

/// npm `parseDesignIconReference`.
fn reference(i: &Invocation) -> Result<(Option<String>, Option<String>, Option<String>), CliError> {
    let trimmed = |key: &str| i.text(key).map(str::trim).filter(|v| !v.is_empty());
    if let Some(path) = trimmed("svg-path") {
        return Ok((Some(path.to_owned()), None, None));
    }
    let icon = trimmed("icon").or_else(|| i.positionals.first().map(String::as_str));
    if let Some(icon) = icon.filter(|v| !v.is_empty()) {
        let parts = icon.split(':').collect::<Vec<_>>();
        if parts.len() != 2 || parts[0].is_empty() || parts[1].is_empty() {
            return Err(failed(
                "Icon reference must use prefix:name, such as lucide:home",
            ));
        }
        return Ok((None, Some(parts[0].to_owned()), Some(parts[1].to_owned())));
    }
    Ok((
        None,
        trimmed("prefix").map(str::to_owned),
        trimmed("name").map(str::to_owned),
    ))
}

fn write_export(path: &str, data: &[u8]) -> Result<(), CliError> {
    if let Some(parent) = Path::new(path)
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent).map_err(|_| crate::error::Error::Io)?;
    }
    std::fs::write(path, data).map_err(|_| crate::error::Error::Io)?;
    Ok(())
}

/// Where the sanitized Iconify SVG comes from; the two credentials never mix.
pub(super) enum SvgSource<'a> {
    Session(&'a mut Client),
    ApiKey(&'a openmates_sdk::sdk::OpenMates),
}

pub(super) async fn execute(i: &Invocation, source: SvgSource<'_>) -> Result<CliOutput, CliError> {
    handlers::flags(i, FLAGS)?;
    let Some(output) = i.text("output").map(str::trim).filter(|v| !v.is_empty()) else {
        return Err(failed(USAGE.trim_end()));
    };
    let format = parse_format(i.text("format"))?;
    let (size, width, height) = (
        positive(i, "size")?,
        positive(i, "width")?,
        positive(i, "height")?,
    );
    let (path, prefix, name) = reference(i)?;
    let exported = export(
        source,
        output,
        format,
        i.text("color"),
        i.text("palette") == Some("true"),
        i.text("allow-palette-recolor") == Some("true"),
        (size, width, height),
        (path.as_deref(), prefix.as_deref(), name.as_deref()),
    )
    .await
    .map_err(|error| match error {
        CliError::Contract { message, .. } => CliError::Contract {
            code: "command_failed",
            message: format!("\x1b[31m✗ Design icon export failed:\x1b[0m {message}"),
        },
        other => other,
    })?;
    if i.boolean("json") {
        return CliOutput::json(&json!({"success":true,"format":exported.format.label(),
            "content_type":exported.format.content_type(),"output_path":output,
            "svg_path":exported.svg_path,"bytes":exported.bytes}));
    }
    Ok(CliOutput::text(format!(
        "Exported {} icon to {}",
        exported.format.label().to_uppercase(),
        terminal_text(output)
    )))
}

struct Exported {
    format: Format,
    svg_path: String,
    bytes: usize,
}

#[allow(clippy::too_many_arguments)]
async fn export(
    source: SvgSource<'_>,
    output: &str,
    format: Option<Format>,
    color: Option<&str>,
    palette: bool,
    allow_recolor: bool,
    (size, width, height): (Option<u32>, Option<u32>, Option<u32>),
    (path, prefix, name): (Option<&str>, Option<&str>, Option<&str>),
) -> Result<Exported, CliError> {
    let svg_path = svg_path(path, prefix, name)?;
    let format = resolve_format(format, output);
    let color = normalize_color(color)?;
    if color.is_some() && palette && !allow_recolor {
        return Err(failed(
            "Palette icons cannot be recolored unless allowPaletteRecolor is true",
        ));
    }
    let svg = match source {
        SvgSource::Session(client) => {
            let response = client.get_binary(&svg_path, ACCEPT).await?;
            if !response.ok() {
                return Err(failed(format!(
                    "Raw resource request failed with HTTP {}",
                    response.status
                )));
            }
            let svg = String::from_utf8_lossy(&response.data).into_owned();
            apply_color(&svg, color.as_deref())?
        }
        // The SDK facade fetches the same OpenMates route and recolors with the
        // shared npm-parity algorithm; PNG stays a local CLI rasterization.
        SvgSource::ApiKey(sdk) => {
            sdk.design()
                .export_icon(openmates_sdk::sdk_design::IconExportOptions {
                    svg_path: Some(svg_path.clone()),
                    format: Some(openmates_sdk::sdk_design::IconFormat::Svg),
                    color: color.clone(),
                    palette,
                    allow_palette_recolor: allow_recolor,
                    ..Default::default()
                })
                .await?
                .svg
        }
    };
    let data = match format {
        Format::Svg => svg.into_bytes(),
        Format::Png => render_png(&svg, size, width, height)?,
    };
    write_export(output, &data)?;
    Ok(Exported {
        format,
        svg_path,
        bytes: data.len(),
    })
}

#[cfg(test)]
#[path = "design_icon_tests.rs"]
mod tests;
