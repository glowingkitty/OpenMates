// Read-only video timeline below the opened videos.generate video.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/videos/VideoTimeline.svelte
//          frontend/packages/ui/src/components/embeds/videos/VideoGenerateEmbedFullscreen.svelte
// CSS:     VideoTimeline.svelte <style>: .ruler, .bar(.main), .part, .playhead, .track-name
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, GradientTokens.generated.swift
// ────────────────────────────────────────────────────────────────────
// Specification: specifications/features/app-skills/videos-generate/specification.yml
// Assertions: videos-generate.timeline.below-the-video
//
// Not included (they send follow-up messages): edit mode and extend buttons.

import SwiftUI

/// Timeline of parts on a ruler with a playhead; a tap or drag on a bar reports a seek time.
struct VideoTimelineView: View {
    let timeline: VideoTimelineModel
    var currentTime: Double = 0
    var compact: Bool = false
    var onSeek: ((Double) -> Void)? = nil

    private let labelWidth: CGFloat = 72

    var body: some View {
        let showNames = timeline.showsTrackNames(compact: compact)
        VStack(alignment: .leading, spacing: .spacing2) {
            if !compact { ruler(showNames: showNames) }
            ForEach(Array(timeline.tracks.enumerated()), id: \.element.id) { index, track in
                row(name: showNames ? track.name : nil, showNames: showNames, height: barHeight(main: index == 0)) { width in
                    ForEach(track.parts) { part in
                        partBlock(part, track: track.kind, total: width)
                    }
                }
            }
            ForEach(compact ? [] : timeline.audioRows) { audioRow in
                row(name: AppStrings.videoTimelineAudioTrack(audioRow.kind.rowId), showNames: showNames, height: barHeight(main: false)) { width in
                    ForEach(audioRow.entries) { entry in
                        audioBlock(entry, total: width)
                    }
                }
            }
        }
        .overlay(alignment: .topLeading) { playhead(showNames: showNames) }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(AppStrings.videoTimeline)
        .accessibilityIdentifier("video-timeline")
    }

    private func barHeight(main: Bool) -> CGFloat { compact ? 20 : (main ? 44 : 36) }

    private func ruler(showNames: Bool) -> some View {
        HStack(spacing: 0) {
            if showNames { Color.clear.frame(width: labelWidth, height: 18) }
            GeometryReader { proxy in
                ZStack(alignment: .topLeading) {
                    ForEach(timeline.rulerMarks, id: \.self) { second in
                        Text("\(second)s")
                            .font(.omXxs)
                            .foregroundStyle(Color.fontTertiary)
                            .position(x: proxy.size.width * timeline.fraction(ofFrame: UInt32(clamping: second * timeline.fps)), y: 9)
                    }
                }
            }
            .frame(height: 18)
            .overlay(alignment: .bottom) { Rectangle().fill(Color.grey30).frame(height: 1) }
        }
    }

    private func row<Content: View>(
        name: String?, showNames: Bool, height: CGFloat,
        @ViewBuilder parts: @escaping (CGFloat) -> Content
    ) -> some View {
        HStack(spacing: 0) {
            if showNames {
                Text(name ?? "")
                    .font(.omXxs).fontWeight(.medium)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(1)
                    .frame(width: labelWidth, alignment: .leading)
            }
            GeometryReader { proxy in
                ZStack(alignment: .topLeading) {
                    Color.grey10
                    parts(proxy.size.width)
                }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { value in
                    guard let onSeek, proxy.size.width > 0 else { return }
                    onSeek(timeline.seekTime(ratio: Double(value.location.x / proxy.size.width)))
                })
            }
            .frame(height: height)
        }
    }

    private func partBlock(_ part: VideoTimelinePart, track: VideoTrackKind, total: CGFloat) -> some View {
        let width = timeline.fraction(ofFrame: part.durationInFrames)
        let range = timeline.rangeLabels(from: part.from, durationInFrames: part.durationInFrames)
        return block(
            label: part.label,
            length: VideoTimelineModel.formatSeconds(Double(part.durationInFrames) / Double(timeline.fps)),
            widthFraction: width, leading: timeline.fraction(ofFrame: part.from), total: total,
            filled: track == .visual, strong: false
        )
        .accessibilityLabel(AppStrings.videoTimelinePartAria(label: part.label, start: range.start, end: range.end))
        .accessibilityIdentifier("video-timeline-part")
    }

    private func audioBlock(_ entry: VideoTimelineAudioEntry, total: CGFloat) -> some View {
        let range = timeline.rangeLabels(from: entry.from, durationInFrames: entry.durationInFrames)
        return block(
            label: entry.label, length: nil,
            widthFraction: timeline.fraction(ofFrame: entry.durationInFrames),
            leading: timeline.fraction(ofFrame: entry.from), total: total,
            filled: false, strong: entry.kind == .music
        )
        .accessibilityLabel(AppStrings.videoTimelinePartAria(label: entry.text ?? entry.label, start: range.start, end: range.end))
        .accessibilityIdentifier("video-timeline-audio")
    }

    private func block(label: String, length: String?, widthFraction: Double, leading: Double,
                       total: CGFloat, filled: Bool, strong: Bool) -> some View {
        HStack(spacing: .spacing2) {
            if VideoTimelineModel.showsLabel(widthFraction: widthFraction, compact: compact) {
                Text(label).lineLimit(1).fontWeight(.semibold)
            }
            Spacer(minLength: 0)
            if let length, VideoTimelineModel.showsLength(widthFraction: widthFraction, compact: compact) {
                Text(length).lineLimit(1).opacity(0.85)
            }
        }
        .font(.omXxs)
        .foregroundStyle(filled ? Color.fontButton : Color.fontPrimary)
        .padding(.horizontal, compact ? .spacing2 : .spacing3)
        .frame(width: max(2, total * CGFloat(widthFraction)), alignment: .leading)
        .frame(maxHeight: .infinity)
        .background {
            if filled { LinearGradient.appVideos } else { strong ? Color.grey40 : Color.grey30 }
        }
        .clipShape(RoundedRectangle(cornerRadius: .radius2))
        .padding(.vertical, compact ? 1 : 2)
        .offset(x: total * CGFloat(leading))
    }

    private func playhead(showNames: Bool) -> some View {
        GeometryReader { proxy in
            let left = showNames ? labelWidth : 0
            let width = max(0, proxy.size.width - left)
            Rectangle()
                .fill(Color.fontPrimary)
                .frame(width: 2)
                .overlay(alignment: .top) { Circle().fill(Color.fontPrimary).frame(width: 10, height: 10).offset(y: -3) }
                .offset(x: left + width * CGFloat(timeline.playheadFraction(currentTime: currentTime)) - 1)
                .accessibilityIdentifier("video-timeline-playhead")
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

/// Timeline section for the opened videos.generate video: stored timeline, else a one-clip timeline.
struct VideoGenerateTimelineSection: View {
    let data: [String: AnyCodable]?
    var loadedSeconds: Double = 0
    var currentTime: Double = 0
    var onSeek: ((Double) -> Void)? = nil

    var body: some View {
        if let timeline = VideoTimelineModel.resolve(
            content: data ?? [:], loadedSeconds: loadedSeconds, clipLabel: AppStrings.videoTimelineClip
        ) {
            VideoTimelineView(timeline: timeline, currentTime: currentTime, onSeek: onSeek)
        }
    }
}
