//! Stored timeline of a `videos.generate` video for the Apple shell (spec
//! `videos-generate.timeline.below-the-video`). The core
//! (`client::video_timeline`) validates, sorts and defaults the content; Swift
//! only draws the records and keeps the pure geometry (ruler, playhead).
use openmates_sdk::client::video_timeline::{
    VideoAudioEntry, VideoAudioKind, VideoMadeBy, VideoPart, VideoPartKind, VideoTimeline,
    VideoTrack, VideoTrackKind, resolve_timeline,
};

/// Who made the video.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VideoMadeByRecord {
    /// One generative model call.
    Generative,
    /// Composed from scenes, clips and sound.
    Composed,
}

/// Kind of a timeline track.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VideoTrackKindRecord {
    /// Picture track.
    Visual,
    /// Text overlay track.
    Text,
    /// Sound track.
    Audio,
}

/// Kind of a part on a track.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VideoPartKindRecord {
    /// Generated scene.
    Scene,
    /// Footage clip.
    Clip,
    /// Text card.
    Text,
    /// Still image.
    Image,
}

/// Kind of a generated sound entry.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VideoAudioKindRecord {
    /// Narration line.
    Speech,
    /// Sound effect.
    Sound,
    /// Music bed.
    Music,
}

/// One part of a track.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VideoPartRecord {
    /// Stable part id.
    pub id: String,
    /// Display label.
    pub label: String,
    /// First frame.
    pub from: u32,
    /// Length in frames.
    pub duration_in_frames: u32,
    /// Part kind.
    pub kind: VideoPartKindRecord,
}

/// One track with its parts in time order.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VideoTrackRecord {
    /// Stable track id.
    pub id: String,
    /// Display name.
    pub name: String,
    /// Track kind.
    pub kind: VideoTrackKindRecord,
    /// Parts sorted by start.
    pub parts: Vec<VideoPartRecord>,
}

/// One generated sound on the timeline.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VideoAudioEntryRecord {
    /// Stable entry id.
    pub id: String,
    /// Entry kind.
    pub kind: VideoAudioKindRecord,
    /// Display label.
    pub label: String,
    /// First frame.
    pub from: u32,
    /// Length in frames.
    pub duration_in_frames: u32,
    /// Narration line of a speech entry.
    pub text: Option<String>,
}

/// Normalised timeline of a video.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VideoTimelineRecord {
    /// Frames per second.
    pub fps: u32,
    /// Total length in frames.
    pub duration_in_frames: u32,
    /// Picture width, 0 when unknown.
    pub width: u32,
    /// Picture height, 0 when unknown.
    pub height: u32,
    /// Who made the video.
    pub made_by: VideoMadeByRecord,
    /// Non-empty tracks.
    pub tracks: Vec<VideoTrackRecord>,
    /// Generated sound sorted by start.
    pub audio: Vec<VideoAudioEntryRecord>,
}

impl From<VideoPart> for VideoPartRecord {
    fn from(part: VideoPart) -> Self {
        Self {
            id: part.id,
            label: part.label,
            from: part.from,
            duration_in_frames: part.duration_in_frames,
            kind: match part.kind {
                VideoPartKind::Scene => VideoPartKindRecord::Scene,
                VideoPartKind::Clip => VideoPartKindRecord::Clip,
                VideoPartKind::Text => VideoPartKindRecord::Text,
                VideoPartKind::Image => VideoPartKindRecord::Image,
            },
        }
    }
}

impl From<VideoTrack> for VideoTrackRecord {
    fn from(track: VideoTrack) -> Self {
        Self {
            id: track.id,
            name: track.name,
            kind: match track.kind {
                VideoTrackKind::Visual => VideoTrackKindRecord::Visual,
                VideoTrackKind::Text => VideoTrackKindRecord::Text,
                VideoTrackKind::Audio => VideoTrackKindRecord::Audio,
            },
            parts: track.parts.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<VideoAudioEntry> for VideoAudioEntryRecord {
    fn from(entry: VideoAudioEntry) -> Self {
        Self {
            id: entry.id,
            kind: match entry.kind {
                VideoAudioKind::Speech => VideoAudioKindRecord::Speech,
                VideoAudioKind::Sound => VideoAudioKindRecord::Sound,
                VideoAudioKind::Music => VideoAudioKindRecord::Music,
            },
            label: entry.label,
            from: entry.from,
            duration_in_frames: entry.duration_in_frames,
            text: entry.text,
        }
    }
}

impl From<VideoTimeline> for VideoTimelineRecord {
    fn from(timeline: VideoTimeline) -> Self {
        Self {
            fps: timeline.fps,
            duration_in_frames: timeline.duration_in_frames,
            width: timeline.width,
            height: timeline.height,
            made_by: match timeline.made_by {
                VideoMadeBy::Generative => VideoMadeByRecord::Generative,
                VideoMadeBy::Composed => VideoMadeByRecord::Composed,
            },
            tracks: timeline.tracks.into_iter().map(Into::into).collect(),
            audio: timeline.audio.into_iter().map(Into::into).collect(),
        }
    }
}

/// The timeline to show under a `videos.generate` video: the stored one, else a
/// one-clip timeline from the stored `duration_seconds` or `loaded_seconds`,
/// else `None`. `content_json` is the decoded embed content as a JSON object;
/// unparsable content counts as no content.
#[uniffi::export]
pub fn video_timeline(
    content_json: String,
    loaded_seconds: f64,
    clip_label: String,
) -> Option<VideoTimelineRecord> {
    let content = serde_json::from_str(&content_json).ok()?;
    resolve_timeline(&content, loaded_seconds, &clip_label).map(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_stored_timeline_and_fallback() {
        let stored = r#"{"timeline":{"tracks":[{"id":"t","parts":[{"id":"p","from":0,"duration_in_frames":30}]}]}}"#;
        let record = video_timeline(stored.into(), 0.0, "Clip".into()).expect("stored");
        assert_eq!(record.tracks[0].parts[0].label, "p");
        let fallback = video_timeline(r#"{"duration_seconds":8}"#.into(), 0.0, "Clip".into());
        assert_eq!(fallback.expect("fallback").duration_in_frames, 240);
        assert!(video_timeline("not json".into(), 5.0, "Clip".into()).is_none());
    }
}
