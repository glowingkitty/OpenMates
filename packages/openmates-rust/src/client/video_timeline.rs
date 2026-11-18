//! Stored timeline of a `videos.generate` video (spec
//! `videos-generate.timeline.below-the-video`): validation, ordering and
//! defaulting of the `timeline` field of decoded embed content, plus the
//! one-clip fallback for videos without a stored timeline. Mirrors the web
//! `normalizeTimeline` / `synthesizeTimeline` in
//! `frontend/packages/ui/src/components/embeds/videos/videoTimelineModel.ts`.
//! Pure functions over `serde_json::Value`; shells only draw the result.
use serde_json::Value;

/// Frame rate used when the stored timeline has none.
pub const DEFAULT_FPS: u32 = 30;

/// Who made the video.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VideoMadeBy {
    /// One generative model call (also the default without `made_by`).
    Generative,
    /// Composed from scenes, clips and generated sound.
    Composed,
}

/// Kind of a timeline track.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VideoTrackKind {
    /// Picture track (default for unknown kinds).
    Visual,
    /// Text overlay track.
    Text,
    /// Sound track.
    Audio,
}

/// Kind of a part on a track.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VideoPartKind {
    /// Generated scene (default for unknown kinds).
    Scene,
    /// Footage clip.
    Clip,
    /// Text card.
    Text,
    /// Still image.
    Image,
}

/// Kind of a generated sound entry.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VideoAudioKind {
    /// Narration line.
    Speech,
    /// Sound effect.
    Sound,
    /// Music bed.
    Music,
}

/// One part of a track.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VideoPart {
    /// Stable part id.
    pub id: String,
    /// Display label (the id when none is stored).
    pub label: String,
    /// First frame on the video's timeline.
    pub from: u32,
    /// Length in frames, at least 1.
    pub duration_in_frames: u32,
    /// Part kind.
    pub kind: VideoPartKind,
}

/// One track with its parts in time order (never empty).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VideoTrack {
    /// Stable track id.
    pub id: String,
    /// Display name (the id when none is stored).
    pub name: String,
    /// Track kind.
    pub kind: VideoTrackKind,
    /// Parts sorted by `from`.
    pub parts: Vec<VideoPart>,
}

/// One generated sound on the timeline.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VideoAudioEntry {
    /// Stable entry id.
    pub id: String,
    /// Entry kind.
    pub kind: VideoAudioKind,
    /// Display label (the id when none is stored).
    pub label: String,
    /// First frame.
    pub from: u32,
    /// Length in frames, at least 1.
    pub duration_in_frames: u32,
    /// Narration line of a speech entry.
    pub text: Option<String>,
}

/// Normalised timeline of a video.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VideoTimeline {
    /// Frames per second.
    pub fps: u32,
    /// Total length in frames (at least the end of every part and sound).
    pub duration_in_frames: u32,
    /// Picture width, 0 when unknown.
    pub width: u32,
    /// Picture height, 0 when unknown.
    pub height: u32,
    /// Who made the video.
    pub made_by: VideoMadeBy,
    /// Non-empty tracks in stored order.
    pub tracks: Vec<VideoTrack>,
    /// Generated sound sorted by `from`.
    pub audio: Vec<VideoAudioEntry>,
}

fn round_u32(n: f64) -> u32 {
    n.round().min(f64::from(u32::MAX)) as u32
}

fn positive_int(value: Option<&Value>) -> Option<u32> {
    let n = value?.as_f64()?;
    (n.is_finite() && n > 0.0).then(|| round_u32(n))
}

fn non_negative_int(value: Option<&Value>) -> Option<u32> {
    let n = value?.as_f64()?;
    (n.is_finite() && n >= 0.0).then(|| round_u32(n))
}

fn string(value: Option<&Value>) -> Option<&str> {
    value?.as_str()
}

fn non_empty(value: Option<&Value>) -> Option<&str> {
    string(value).filter(|s| !s.is_empty())
}

fn normalize_part(raw: &Value) -> Option<VideoPart> {
    let id = string(raw.get("id"))?;
    let from = non_negative_int(raw.get("from"))?;
    let duration_in_frames = positive_int(raw.get("duration_in_frames"))?;
    let kind = match string(raw.get("kind")) {
        Some("clip") => VideoPartKind::Clip,
        Some("text") => VideoPartKind::Text,
        Some("image") => VideoPartKind::Image,
        _ => VideoPartKind::Scene,
    };
    Some(VideoPart {
        id: id.to_owned(),
        label: non_empty(raw.get("label")).unwrap_or(id).to_owned(),
        from,
        duration_in_frames,
        kind,
    })
}

fn normalize_audio(raw: Option<&Value>) -> Vec<VideoAudioEntry> {
    let Some(items) = raw.and_then(Value::as_array) else {
        return Vec::new();
    };
    let mut entries: Vec<VideoAudioEntry> = items
        .iter()
        .filter_map(|item| {
            let id = string(item.get("id"))?;
            let kind = match string(item.get("kind"))? {
                "speech" => VideoAudioKind::Speech,
                "sound" => VideoAudioKind::Sound,
                "music" => VideoAudioKind::Music,
                _ => return None,
            };
            let from = non_negative_int(item.get("from"))?;
            let duration_in_frames = positive_int(
                item.get("durationInFrames")
                    .or_else(|| item.get("duration_in_frames")),
            )?;
            Some(VideoAudioEntry {
                id: id.to_owned(),
                kind,
                label: non_empty(item.get("label")).unwrap_or(id).to_owned(),
                from,
                duration_in_frames,
                text: non_empty(item.get("text")).map(str::to_owned),
            })
        })
        .collect();
    entries.sort_by_key(|entry| entry.from);
    entries
}

/// The stored timeline of decoded embed content, or `None` when there is none
/// (older videos) or no track keeps a valid part. Invalid parts and sounds are
/// dropped, parts and sounds are sorted by start, and the length grows to the
/// end of the last part or sound.
pub fn normalize_timeline(content: &Value) -> Option<VideoTimeline> {
    let raw = content.get("timeline").filter(|v| v.is_object())?;
    let raw_tracks = raw.get("tracks")?.as_array()?;
    let fps = positive_int(raw.get("fps")).unwrap_or(DEFAULT_FPS);
    let mut tracks = Vec::new();
    for track in raw_tracks {
        let Some(id) = string(track.get("id")) else {
            continue;
        };
        let kind = match string(track.get("kind")) {
            Some("text") => VideoTrackKind::Text,
            Some("audio") => VideoTrackKind::Audio,
            _ => VideoTrackKind::Visual,
        };
        let mut parts: Vec<VideoPart> = track
            .get("parts")
            .and_then(Value::as_array)
            .map(|parts| parts.iter().filter_map(normalize_part).collect())
            .unwrap_or_default();
        parts.sort_by_key(|part| part.from);
        if !parts.is_empty() {
            tracks.push(VideoTrack {
                id: id.to_owned(),
                name: string(track.get("name")).unwrap_or(id).to_owned(),
                kind,
                parts,
            });
        }
    }
    if tracks.is_empty() {
        return None;
    }
    let audio = normalize_audio(raw.get("audio"));
    let end = tracks
        .iter()
        .flat_map(|t| {
            t.parts
                .iter()
                .map(|p| p.from.saturating_add(p.duration_in_frames))
        })
        .chain(
            audio
                .iter()
                .map(|a| a.from.saturating_add(a.duration_in_frames)),
        )
        .max()
        .unwrap_or(0);
    Some(VideoTimeline {
        fps,
        duration_in_frames: positive_int(raw.get("duration_in_frames"))
            .unwrap_or(0)
            .max(end),
        width: positive_int(raw.get("width"))
            .or_else(|| positive_int(content.get("width")))
            .unwrap_or(0),
        height: positive_int(raw.get("height"))
            .or_else(|| positive_int(content.get("height")))
            .unwrap_or(0),
        made_by: if string(content.get("made_by")) == Some("composed") {
            VideoMadeBy::Composed
        } else {
            VideoMadeBy::Generative
        },
        tracks,
        audio,
    })
}

/// One-clip timeline of an older video without a stored timeline.
pub fn synthesize_timeline(
    duration_seconds: f64,
    label: &str,
    width: u32,
    height: u32,
) -> VideoTimeline {
    let frames = round_u32((duration_seconds * f64::from(DEFAULT_FPS)).max(0.0)).max(1);
    VideoTimeline {
        fps: DEFAULT_FPS,
        duration_in_frames: frames,
        width,
        height,
        made_by: VideoMadeBy::Generative,
        tracks: vec![VideoTrack {
            id: "video".to_owned(),
            name: label.to_owned(),
            kind: VideoTrackKind::Visual,
            parts: vec![VideoPart {
                id: "clip-1".to_owned(),
                label: label.to_owned(),
                from: 0,
                duration_in_frames: frames,
                kind: VideoPartKind::Clip,
            }],
        }],
        audio: Vec::new(),
    }
}

/// The timeline to show: the stored one, else a one-clip timeline from the
/// stored `duration_seconds` (or `loaded_seconds` when none is stored), else
/// `None` while no length is known.
pub fn resolve_timeline(
    content: &Value,
    loaded_seconds: f64,
    clip_label: &str,
) -> Option<VideoTimeline> {
    if let Some(stored) = normalize_timeline(content) {
        return Some(stored);
    }
    let stored_seconds = content
        .get("duration_seconds")
        .and_then(Value::as_f64)
        .filter(|s| s.is_finite() && *s > 0.0);
    let seconds = stored_seconds.unwrap_or(loaded_seconds);
    if !(seconds.is_finite() && seconds > 0.0) {
        return None;
    }
    Some(synthesize_timeline(
        seconds,
        clip_label,
        positive_int(content.get("width")).unwrap_or(0),
        positive_int(content.get("height")).unwrap_or(0),
    ))
}

#[cfg(test)]
#[path = "video_timeline_tests.rs"]
mod tests;
