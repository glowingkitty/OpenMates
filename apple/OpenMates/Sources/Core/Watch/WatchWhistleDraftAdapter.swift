// The recording-draft boundary is local-only, with no server fallback.
// Specification: specifications/features/apple-watch/specification.yml
// Assertions: apple-watch.chats.local-transcription
#if os(watchOS)
extension WhistleRecordingDraftTranscriber: WatchRecordingDraftTranscribing {}
#endif
