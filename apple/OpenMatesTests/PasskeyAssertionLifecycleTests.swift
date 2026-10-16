import XCTest
@testable import OpenMates

@MainActor final class PasskeyAssertionLifecycleTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testManualRequestDrainsAutomaticCancellationBeforeStarting() async {
        let lifecycle = PasskeyAssertionLifecycle()
        let automatic = Controller()
        let manual = Controller()
        let first = Task {
            do { _ = try await lifecycle.perform { automatic }; XCTFail("Cancelled automatic request succeeded") }
            catch is CancellationError {} catch { XCTFail("Unexpected cancellation error") }
        }
        await waitUntil { automatic.started }
        let second = Task {
            do { _ = try await lifecycle.perform { manual } }
            catch { XCTFail("Manual request failed") }
        }
        await waitUntil { automatic.cancelCount == 1 }
        XCTAssertFalse(manual.started, "OS cancellation acknowledgement must precede the manual request")
        automatic.complete(.failure(PasskeyError.cancelled))
        await waitUntil { manual.started }
        manual.complete(.success(result()))
        await first.value
        await second.value
        XCTAssertEqual(automatic.cancelCount, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence,auth.session.isolation
    func testViewTaskCancellationRejectsLateSuccessAndDuplicateCallbacks() async {
        let lifecycle = PasskeyAssertionLifecycle()
        let controller = Controller()
        let operation = Task {
            do { _ = try await lifecycle.perform { controller }; XCTFail("A removed view cannot accept a credential") }
            catch is CancellationError {} catch { XCTFail("Unexpected cancellation error") }
        }
        await waitUntil { controller.started }
        operation.cancel()
        await waitUntil { controller.cancelCount == 1 }
        controller.complete(.success(result()))
        controller.complete(.failure(PasskeyError.cancelled))
        await operation.value
        XCTAssertEqual(controller.cancelCount, 1)
        let replacement = Controller()
        let next = Task { _ = try? await lifecycle.perform { replacement } }
        await waitUntil { replacement.started }
        replacement.complete(.success(result()))
        await next.value
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testAlreadyCancelledTaskNeverStartsController() async {
        let lifecycle = PasskeyAssertionLifecycle()
        let controller = Controller()
        let operation = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            do { _ = try await lifecycle.perform { controller }; XCTFail("Cancelled task succeeded") }
            catch is CancellationError {} catch { XCTFail("Unexpected cancellation error") }
        }
        await operation.value
        XCTAssertFalse(controller.started)
        XCTAssertEqual(controller.cancelCount, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testCancellationBeforeControllerStartSettlesDrainAndRejectsRun() async {
        let controller = Controller()
        let operation = PasskeyAssertionOperation(controller: controller)
        operation.cancel()
        operation.cancel()
        var drained = false
        let drain = Task { await operation.waitUntilFinished(); drained = true }
        await waitUntil { drained }
        guard drained else { drain.cancel(); return }
        await drain.value
        do { _ = try await operation.run(); XCTFail("Pre-start cancellation accepted a credential") }
        catch is CancellationError {} catch { XCTFail("Wrong cancellation error") }
        XCTAssertFalse(controller.started)
        XCTAssertEqual(controller.cancelCount, 0, "An unstarted OS controller needs no cancellation callback")
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testCancellationDuringControllerCreationAllowsSuccessorToStart() async {
        let lifecycle = PasskeyAssertionLifecycle()
        let controller = Controller()
        let first = Task {
            do {
                _ = try await lifecycle.perform {
                    withUnsafeCurrentTask { $0?.cancel() }
                    return controller
                }
                XCTFail("Cancelled creator started an OS request")
            } catch is CancellationError {} catch { XCTFail("Wrong cancellation error") }
        }
        await first.value
        XCTAssertFalse(controller.started)
        let successor = Controller()
        let next = Task { _ = try? await lifecycle.perform { successor } }
        await waitUntil { successor.started }
        successor.complete(.success(result()))
        await next.value
    }

    // contract-test: supporting surface=gui.apple assertions=auth.login.method-convergence
    func testNormalFailureResumesOnceAndAllowsRetry() async {
        let lifecycle = PasskeyAssertionLifecycle()
        let controller = Controller()
        let operation = Task {
            do { _ = try await lifecycle.perform { controller }; XCTFail("Rejected assertion succeeded") }
            catch PasskeyError.assertionFailed {} catch { XCTFail("Wrong assertion error") }
        }
        await waitUntil { controller.started }
        controller.complete(.failure(PasskeyError.assertionFailed))
        controller.complete(.success(result()))
        await operation.value
        let retry = Controller()
        let next = Task { _ = try? await lifecycle.perform { retry } }
        await waitUntil { retry.started }
        retry.complete(.success(result()))
        await next.value
        XCTAssertEqual(controller.cancelCount, 0)
    }

    private func waitUntil(_ condition: () -> Bool, file: StaticString = #filePath, line: UInt = #line) async {
        let deadline = ContinuousClock.now + .seconds(2)
        while !condition(), ContinuousClock.now < deadline { await Task.yield() }
        XCTAssertTrue(condition(), "Lifecycle transition did not finish", file: file, line: line)
    }

    private func result() -> PasskeyAssertionResult {
        PasskeyAssertionResult(credentialId: "fixture-credential", prfSignature: Data([1]),
            verifyRequest: .init(credentialId: "fixture-credential",
                assertionResponse: .init(authenticatorData: "", clientDataJSON: "", signature: "", userHandle: nil),
                clientDataJSON: "", authenticatorData: "", sessionId: "fixture-session", stayLoggedIn: false,
                hashedEmail: nil, emailEncryptionKey: nil))
    }

    private final class Controller: PasskeyAssertionController {
        var started = false
        var cancelCount = 0
        private var completion: (@MainActor (Result<PasskeyAssertionResult, Error>) -> Void)?
        func start(completion: @escaping @MainActor (Result<PasskeyAssertionResult, Error>) -> Void) {
            started = true
            self.completion = completion
        }
        func cancel() { cancelCount += 1 }
        // Deliberately retain the callback to prove duplicate delegate delivery is harmless.
        func complete(_ result: Result<PasskeyAssertionResult, Error>) { completion?(result) }
    }
}
