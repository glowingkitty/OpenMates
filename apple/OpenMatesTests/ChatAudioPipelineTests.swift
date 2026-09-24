// Deterministic coverage for the authenticated Apple recording finalization pipeline.
// Network and microphone I/O are replaced at the pipeline seam so these tests can
// prove concurrency, fallback counts, metadata completeness, and deferred-send identity.

import XCTest
@testable import OpenMates

@MainActor
final class ChatAudioPipelineTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send,chats.message.identity-idempotent
    func testRecordingDeferredSendRetainsEmbedAndIdentityAcrossReconnect() async throws {
        let nodeID = "composer:embed:recording-reconnect"
        let document = ComposerDocumentV1(version: 1, nodes: [
            .embed(
                id: nodeID,
                embedType: "recording",
                canonicalSource: "",
                referenceOnly: true,
                display: .init(title: "recording.m4a", mediaKind: "audio")
            ).updatingStatus(AppleComposerEmbedLifecycleState.uploading.rawValue)
        ])
        let queued = ComposerSendSnapshot(
            requestId: "request-reconnect",
            messageId: "message-reconnect",
            destinationId: "chat-reconnect",
            documentRevision: 11,
            document: document,
            blockers: [.init(nodeId: nodeID, generation: 1)]
        )
        let recording = ComposerPendingEmbed.from(
            upload: Self.uploadFixture(embedId: "server-recording-reconnect"),
            localData: nil,
            transcription: nil,
            duration: 2.4
        )
        let frozen = try XCTUnwrap(ComposerDeferredEmbedSnapshot(
            document: document,
            resolvedEmbeds: [nodeID: recording]
        ))
        XCTAssertNil(ComposerDeferredEmbedSnapshot(document: document, resolvedEmbeds: [:]))

        let coordinator = ComposerPendingSendCoordinator()
        let dispatches = AudioPipelineDispatchRecorder()
        let enqueued = await coordinator.enqueue(queued)
        XCTAssertTrue(enqueued)
        await coordinator.updateNode(nodeId: nodeID, generation: 1, state: .finished)
        await coordinator.resumeReady { _ in throw AudioPipelineTransportError.disconnected }
        let failedStatus = await coordinator.status(requestId: queued.requestId)
        XCTAssertEqual(failedStatus, .failed)

        // A later composer change must not replace the uploaded recording attached
        // to this exact message. Reconnect retries the same queue entry once.
        let replacement = ComposerPendingEmbed.from(
            upload: Self.uploadFixture(embedId: "server-recording-later"),
            localData: nil,
            transcription: nil,
            duration: 1.0
        )
        let changedComposer = ComposerDeferredEmbedSnapshot(
            document: document,
            resolvedEmbeds: [nodeID: replacement]
        )
        XCTAssertNotEqual(frozen.embeds.first?.id, changedComposer?.embeds.first?.id)
        let frozenEmbedID = frozen.embeds.first?.id
        let retried = await coordinator.retryFailed(requestId: queued.requestId)
        XCTAssertTrue(retried)
        await coordinator.resumeReady { snapshot in
            await dispatches.append(messageID: snapshot.messageId, embedID: frozenEmbedID)
        }
        await coordinator.resumeReady { snapshot in
            await dispatches.append(messageID: snapshot.messageId, embedID: frozenEmbedID)
        }
        let sent = await dispatches.values()
        XCTAssertEqual(sent, [
            .init(messageID: "message-reconnect", embedID: "server-recording-reconnect")
        ])
        let completedStatus = await coordinator.status(requestId: queued.requestId)
        XCTAssertEqual(completedStatus, .completed)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.inline-entity-interaction,message-input.recording.lifecycle
    func testSentRecordingTypeSurvivesInlineGrouping() {
        let recording = EmbedRecord(
            id: "sent-recording", type: "audio-recording", status: .finished,
            data: .raw(["filename": AnyCodable("recording.m4a")]),
            parentEmbedId: nil, appId: "audio", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        let groups = EmbedGrouper.groupForInlineDisplay([recording])
        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups.first?.type, .recording)
        XCTAssertEqual(groups.first?.embeds.first?.id, recording.id)
        let image = EmbedRecord(
            id: "sent-image", type: "images-image", status: .finished,
            data: .raw(["filename": AnyCodable("photo.jpg")]),
            parentEmbedId: nil, appId: "images", skillId: nil,
            embedIds: nil, createdAt: nil
        )
        XCTAssertEqual(EmbedGrouper.groupForInlineDisplay([image]).first?.type, .image)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle
    func testLiveTranscriptViewportPreservesStreamTextAndAdvancesToNewestRenderedLine() {
        let streamUpdates = [
            "Earlier transcript line",
            "Earlier transcript line\nNewest transcript line"
        ]
        let presentedUpdates = streamUpdates.compactMap {
            RecordingLiveTranscriptViewportMetrics.normalizedTranscript($0)
        }

        XCTAssertEqual(presentedUpdates, streamUpdates)
        XCTAssertEqual(
            presentedUpdates.last,
            "Earlier transcript line\nNewest transcript line",
            "The display viewport must not discard earlier text needed by final recording metadata"
        )
        XCTAssertEqual(
            RecordingLiveTranscriptViewportMetrics.bottomOffset(contentHeight: 44, viewportHeight: 22),
            22,
            "A two-line update must shift by one line so the newest rendered line stays visible"
        )
        XCTAssertEqual(
            RecordingLiveTranscriptViewportMetrics.bottomOffset(contentHeight: 66, viewportHeight: 22),
            44,
            "Later stream updates must continue advancing the bounded viewport"
        )

    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testRealtimeFinishWithoutTerminalEventSettlesForBatchFallback() async {
        let session = AudioRecordingRealtimeSession(finishTimeout: .milliseconds(20))
        session.finish()

        let result = await session.awaitResult()

        XCTAssertNil(result)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testRealtimeFinishKeepsVisibleTranscriptWhenTerminalEventIsMissing() async throws {
        let session = AudioRecordingRealtimeSession(finishTimeout: .milliseconds(20))
        await session.receiveForTesting(.transcript("Schedule a review"))
        await session.receiveForTesting(.transcript("Schedule a review tomorrow"))
        session.finish()

        let settled = await session.awaitResult()
        let result = try XCTUnwrap(settled)

        XCTAssertEqual(result.transcript, "Schedule a review tomorrow")
        XCTAssertEqual(result.transcriptOriginal, "Schedule a review tomorrow")
        XCTAssertFalse(result.useCorrected)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send,chats.message.identity-idempotent
    func testRealtimeUploadOverlapsCorrectionSkipsBatchAndUnblocksSameMessageIdentity() async throws {
        let correctionGate = AudioPipelineGate()
        let starts = AudioPipelineStartRecorder()
        let batchCalls = AudioPipelineCounter()
        let dispatches = AudioPipelineDispatchRecorder()
        let upload = Self.uploadFixture(embedId: "server-recording-1")
        let waveform = try XCTUnwrap(AudioRecordingWaveform(
            normalizedLevels: [0, 0.25, 0.5, 0.75, 1],
            duration: 2.4
        ))

        let pipelineTask = Task { @MainActor in
            await AudioRecordingUploadPipeline.run(
                waveform: waveform,
                realtimeResult: {
                    await starts.record("correction")
                    await correctionGate.wait()
                    return AudioRecordingRealtimeResult(
                        title: "Project review",
                        transcript: "Schedule the project review Thursday afternoon.",
                        transcriptOriginal: "Schedule project review Thursday afternoon.",
                        transcriptCorrected: "Schedule the project review Thursday afternoon.",
                        useCorrected: true,
                        model: AudioRealtimeTranscriptionClient.model,
                        correctionModel: "gemini-3.5-flash"
                    )
                },
                upload: {
                    await starts.record("upload")
                    return upload
                },
                batchTranscription: { _ in
                    await batchCalls.increment()
                    return nil
                }
            )
        }

        await starts.waitFor(keys: ["upload", "correction"])
        let localNodeID = "composer:embed:recording-1"
        let messageID = "message-recording-1"
        let lifecycle = ComposerEmbedLifecycle()
        let lifecycleRecord = lifecycle.register(nodeId: localNodeID, state: .uploading)
        let coordinator = ComposerPendingSendCoordinator()
        let snapshot = ComposerSendSnapshot(
            requestId: "request-recording-1",
            messageId: messageID,
            destinationId: "chat-1",
            documentRevision: 9,
            document: ComposerDocumentV1(
                version: 1,
                nodes: [
                    .embed(
                        id: localNodeID,
                        embedType: "recording",
                        canonicalSource: "",
                        referenceOnly: true,
                        display: .init(title: "recording.m4a", mediaKind: "audio")
                    ).updatingStatus(AppleComposerEmbedLifecycleState.uploading.rawValue)
                ]
            ),
            blockers: [.init(nodeId: localNodeID, generation: lifecycleRecord.generation)]
        )
        let enqueued = await coordinator.enqueue(snapshot)
        XCTAssertTrue(enqueued)
        await coordinator.updateNode(
            nodeId: localNodeID,
            generation: lifecycleRecord.generation,
            state: .uploading
        )
        await coordinator.resumeReady { dispatched in
            await dispatches.append(messageID: dispatched.messageId, embedID: nil)
        }
        let dispatchCountWhilePending = await dispatches.values().count
        XCTAssertEqual(dispatchCountWhilePending, 0, "Immediate Send must remain deferred while correction is pending")

        await correctionGate.open()
        let completedPipeline = await pipelineTask.value
        let pipeline = try XCTUnwrap(completedPipeline)
        let realtimeBatchCalls = await batchCalls.value()
        XCTAssertEqual(realtimeBatchCalls, 0, "Successful realtime transcription must make zero batch calls")

        let embed = ComposerPendingEmbed.from(
            upload: pipeline.upload,
            localData: Data([0x01]),
            transcription: pipeline.transcription,
            duration: 2.4
        )
        guard case .applied(let finished) = lifecycle.transition(
            nodeId: localNodeID,
            generation: lifecycleRecord.generation,
            to: .finished,
            durableEmbedId: embed.id
        ) else {
            return XCTFail("Expected the original recording node to resolve")
        }
        await coordinator.updateNode(
            nodeId: localNodeID,
            generation: finished.generation,
            state: .finished
        )
        await coordinator.resumeReady { dispatched in
            await dispatches.append(messageID: dispatched.messageId, embedID: embed.id)
        }

        let dispatchedValues = await dispatches.values()
        XCTAssertEqual(dispatchedValues, [
            .init(messageID: messageID, embedID: "server-recording-1")
        ])
        XCTAssertEqual(finished.nodeId, localNodeID)
        XCTAssertEqual(embed.id, upload.embedId)
        XCTAssertEqual(embed.textPreview, "Project review")

        let content = try Self.contentObject(embed)
        XCTAssertEqual(content["title"] as? String, "Project review")
        XCTAssertEqual(content["transcript"] as? String, "Schedule the project review Thursday afternoon.")
        XCTAssertEqual(content["transcript_original"] as? String, "Schedule project review Thursday afternoon.")
        XCTAssertEqual(content["transcript_corrected"] as? String, "Schedule the project review Thursday afternoon.")
        XCTAssertEqual(content["use_corrected"] as? Bool, true)
        XCTAssertEqual(content["model"] as? String, AudioRealtimeTranscriptionClient.model)
        XCTAssertEqual(content["correction_model"] as? String, "gemini-3.5-flash")
        let persistedWaveform = try XCTUnwrap(content["waveform"] as? [String: Any])
        XCTAssertEqual(persistedWaveform["version"] as? Int, 1)
        XCTAssertEqual(persistedWaveform["kind"] as? String, "rms-envelope")
        XCTAssertEqual((persistedWaveform["samples"] as? [Int])?.count, 128)
        XCTAssertEqual(persistedWaveform["duration_seconds"] as? Double, 2.4)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testRealtimeCorrectionFailureUsesRawTranscriptWithoutBatch() async throws {
        let batchCalls = AudioPipelineCounter()
        let completedPipeline = await AudioRecordingUploadPipeline.run(
            waveform: nil,
            realtimeResult: {
                AudioRecordingRealtimeResult(
                    title: nil,
                    transcript: "Raw transcript survives correction failure.",
                    transcriptOriginal: "Raw transcript survives correction failure.",
                    transcriptCorrected: nil,
                    useCorrected: false,
                    model: AudioRealtimeTranscriptionClient.model,
                    correctionModel: nil
                )
            },
            upload: { Self.uploadFixture(embedId: "server-recording-raw") },
            batchTranscription: { _ in
                await batchCalls.increment()
                return nil
            }
        )
        let result = try XCTUnwrap(completedPipeline)

        let correctionFailureBatchCalls = await batchCalls.value()
        XCTAssertEqual(correctionFailureBatchCalls, 0)
        XCTAssertEqual(result.transcription.transcript, "Raw transcript survives correction failure.")
        XCTAssertEqual(result.transcription.transcriptOriginal, "Raw transcript survives correction failure.")
        XCTAssertNil(result.transcription.transcriptCorrected)
        XCTAssertEqual(result.transcription.useCorrected, false)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.embeds.gated-send
    func testRealtimeFailureCallsBatchExactlyOnceAndKeepsCompleteBatchMetadata() async throws {
        let batchCalls = AudioPipelineCounter()
        let batchWaveform = try XCTUnwrap(AudioRecordingWaveform(samples: [10, 30, 50], duration: 3))
        let completedPipeline = await AudioRecordingUploadPipeline.run(
            waveform: nil,
            realtimeResult: { nil },
            upload: { Self.uploadFixture(embedId: "server-recording-fallback") },
            batchTranscription: { _ in
                await batchCalls.increment()
                return TranscriptionMetadata(
                    title: "Recovered recording",
                    transcript: "Recovered by batch transcription.",
                    transcriptOriginal: "Recovered by batch transcription.",
                    transcriptCorrected: nil,
                    useCorrected: false,
                    model: "voxtral-mini-transcribe-2507",
                    correctionModel: nil,
                    waveform: batchWaveform
                )
            }
        )
        let result = try XCTUnwrap(completedPipeline)

        let fallbackBatchCalls = await batchCalls.value()
        XCTAssertEqual(fallbackBatchCalls, 1)
        XCTAssertEqual(result.upload.embedId, "server-recording-fallback")
        XCTAssertEqual(result.transcription.title, "Recovered recording")
        XCTAssertEqual(result.transcription.waveform, batchWaveform)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testStalledTranscriptionKeepsUploadedAudioPlayable() async throws {
        let waveform = try XCTUnwrap(AudioRecordingWaveform(samples: [10, 30], duration: 3))
        let result = await AudioRecordingUploadPipeline.run(
            waveform: waveform,
            realtimeResult: { nil },
            upload: { Self.uploadFixture(embedId: "server-recording-without-transcript") },
            batchTranscription: { _ in
                try? await Task.sleep(for: .seconds(5))
                return nil
            },
            batchTimeout: .milliseconds(20)
        )

        let retained = try XCTUnwrap(result)
        XCTAssertEqual(retained.upload.embedId, "server-recording-without-transcript")
        XCTAssertNil(retained.transcription.transcript)
        XCTAssertEqual(retained.transcription.waveform, waveform)
    }

    private static func uploadFixture(embedId: String) -> UploadFileResponse {
        UploadFileResponse(
            embedId: embedId,
            filename: "recording.m4a",
            contentType: "audio/mp4",
            contentHash: "hash-recording",
            files: [
                "original": UploadedFileVariant(
                    s3Key: "recordings/recording.m4a",
                    sizeBytes: 512,
                    width: nil,
                    height: nil,
                    format: "m4a"
                )
            ],
            s3BaseUrl: "https://example.invalid/audio",
            aesKey: "test-aes-key",
            aesNonce: "test-aes-nonce",
            vaultWrappedAesKey: "test-wrapped-key",
            pageCount: nil,
            deduplicated: false
        )
    }

    private static func contentObject(_ embed: ComposerPendingEmbed) throws -> [String: Any] {
        let content = try XCTUnwrap(embed.content)
        let data = try XCTUnwrap(content.data(using: .utf8))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}

private enum AudioPipelineTransportError: Error {
    case disconnected
}

private actor AudioPipelineGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        let pending = waiters
        waiters.removeAll()
        pending.forEach { $0.resume() }
    }
}

private actor AudioPipelineStartRecorder {
    private var keys = Set<String>()
    private var waiters: [(Set<String>, CheckedContinuation<Void, Never>)] = []

    func record(_ key: String) {
        keys.insert(key)
        let ready = waiters.filter { keys.isSuperset(of: $0.0) }
        waiters.removeAll { keys.isSuperset(of: $0.0) }
        ready.forEach { $0.1.resume() }
    }

    func waitFor(keys expected: Set<String>) async {
        if keys.isSuperset(of: expected) { return }
        await withCheckedContinuation { waiters.append((expected, $0)) }
    }
}

private actor AudioPipelineCounter {
    private var count = 0
    func increment() { count += 1 }
    func value() -> Int { count }
}

private struct AudioPipelineDispatch: Equatable {
    let messageID: String
    let embedID: String?
}

private actor AudioPipelineDispatchRecorder {
    private var dispatched: [AudioPipelineDispatch] = []
    func append(messageID: String, embedID: String?) {
        dispatched.append(.init(messageID: messageID, embedID: embedID))
    }
    func values() -> [AudioPipelineDispatch] { dispatched }
}
