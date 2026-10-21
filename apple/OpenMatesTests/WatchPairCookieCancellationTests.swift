// Hermetic URLSession response-cookie regression. No live API or credentials.
import XCTest
@testable import OpenMates

@MainActor
final class WatchPairCookieCancellationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testCancelledReceiverCannotInstallResponseCookieInInjectedJar() async throws {
        try await exercise(cancel: true)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.pairing.private-session
    func testCurrentReceiverManuallyInstallsResponseCookieInInjectedJar() async throws {
        try await exercise(cancel: false)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testHermeticTransportActuallyExercisesAutomaticResponseCookieAcceptance() async throws {
        // This control must pass before the opt-out regression can establish the
        // Foundation boundary. A protocol implementation that never accepts any
        // response cookies would otherwise produce misleading negative evidence.
        let profile = ServerProfile.custom(domain: "pair-cookie-fixture.example")
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieAcceptPolicy = .always
        configuration.protocolClasses = [WatchPairCookieURLProtocol.self]
        let jar = try XCTUnwrap(configuration.httpCookieStorage)
        let headers = expectation(description: "Automatic-cookie control response headers")
        let fixture = WatchPairCookieURLProtocol.Fixture(headersDelivered: headers)
        WatchPairCookieURLProtocol.setFixture(fixture)
        let transport = URLSession(configuration: configuration)
        defer { transport.invalidateAndCancel(); WatchPairCookieURLProtocol.setFixture(nil) }
        let request = Task { try await transport.data(from: profile.apiBaseURL.appendingPathComponent("control")) }
        await fulfillment(of: [headers], timeout: 3)
        fixture.finish()
        _ = try await request.value
        XCTAssertEqual(jar.cookies(for: profile.apiBaseURL)?.first(where: { $0.name == "auth_refresh_token" })?.value,
            "successor-fixture", "If this control fails, the hermetic protocol cannot prove Foundation automatic cookie acceptance")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back,apple-watch.guest.account-isolation
    func testUncancelledObsoleteWatchReceiverCannotPublishActualResponseCookieOrOwnershipHook() async throws {
        let previous = ServerConfiguration.current
        let profile = ServerProfile.custom(domain: "pair-cookie-fixture.example")
        ServerConfiguration.current = profile.endpointConfiguration
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieAcceptPolicy = .always
        configuration.protocolClasses = [WatchPairCookieURLProtocol.self]
        let jar = try XCTUnwrap(configuration.httpCookieStorage)
        let original = try XCTUnwrap(HTTPCookie(properties: [.domain: try XCTUnwrap(profile.apiBaseURL.host),
            .path: "/", .name: "auth_refresh_token", .value: "existing-owner-fixture"]))
        jar.setCookie(original)
        let headers = expectation(description: "Obsolete receiver Set-Cookie headers delivered")
        let fixture = WatchPairCookieURLProtocol.Fixture(headersDelivered: headers)
        WatchPairCookieURLProtocol.setFixture(fixture)
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel(); WatchPairCookieURLProtocol.setFixture(nil)
            ServerConfiguration.current = previous
        }
        let api = APIClient(session: transport, cookieStorage: jar)
        var current = true
        var publicationObserved = false
        let authority = WatchPairReceiverAuthority.Context(isCurrent: { current },
            cookiesDidPublish: { publicationObserved = true }, verifiedDidPersist: {})
        let receiver = Task { @MainActor in
            try await WatchPairReceiverAuthority.$current.withValue(authority) {
                let _: Data = try await api.request(.post, path: "/v1/auth/pair/v2/complete/FIX346",
                    serverProfile: profile, body: ["grant_secret": "synthetic-only"])
            }
        }
        await fulfillment(of: [headers], timeout: 3)
        current = false
        fixture.finish()
        try await receiver.value
        XCTAssertFalse(receiver.isCancelled, "The stale-authority fence must work without task cancellation")
        XCTAssertEqual(jar.cookies(for: profile.apiBaseURL)?.first { $0.name == "auth_refresh_token" }?.value,
            "existing-owner-fixture")
        XCTAssertFalse(publicationObserved, "An obsolete production response may not claim cookie ownership")
    }

    private func exercise(cancel: Bool) async throws {
        let previous = ServerConfiguration.current
        let profile = ServerProfile.custom(domain: "pair-cookie-fixture.example")
        ServerConfiguration.current = profile.endpointConfiguration
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieAcceptPolicy = .always
        configuration.protocolClasses = [WatchPairCookieURLProtocol.self]
        let jar = try XCTUnwrap(configuration.httpCookieStorage)
        let original = try XCTUnwrap(HTTPCookie(properties: [.domain: try XCTUnwrap(profile.apiBaseURL.host),
            .path: "/", .name: "auth_refresh_token", .value: "original-fixture"]))
        jar.setCookie(original)
        let headersDelivered = expectation(description: "Actual Set-Cookie response headers delivered")
        let fixture = WatchPairCookieURLProtocol.Fixture(headersDelivered: headersDelivered)
        WatchPairCookieURLProtocol.setFixture(fixture)
        let transport = URLSession(configuration: configuration)
        defer {
            transport.invalidateAndCancel()
            WatchPairCookieURLProtocol.setFixture(nil)
            ServerConfiguration.current = previous
        }
        let api = APIClient(session: transport, cookieStorage: jar)
        let request = Task {
            let _: Data = try await api.request(.post, path: "/v1/auth/pair/v2/complete/FIX346",
                serverProfile: profile, body: ["grant_secret": "synthetic-only"])
        }
        await fulfillment(of: [headersDelivered], timeout: 3)
        XCTAssertEqual(jar.cookies(for: profile.apiBaseURL)?.first(where: { $0.name == "auth_refresh_token" })?.value,
            "original-fixture", "URLSession may not automatically publish pair response cookies before authority checks")
        XCTAssertEqual(fixture.request?.httpShouldHandleCookies, false)
        XCTAssertEqual(fixture.request?.value(forHTTPHeaderField: "Cookie"), "auth_refresh_token=original-fixture")
        if cancel { request.cancel() }
        fixture.finish()
        if cancel {
            do { try await request.value; XCTFail("Cancelled receiver must not succeed") } catch {}
        } else { try await request.value }
        XCTAssertEqual(jar.cookies(for: profile.apiBaseURL)?.first(where: { $0.name == "auth_refresh_token" })?.value,
            cancel ? "original-fixture" : "successor-fixture")
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.pairing.explicit-entry-back
    func testCancellationAtPublicationBoundaryPreservesActualCookieJar() async throws {
        let profile = ServerProfile.current()
        let jar = try XCTUnwrap(URLSessionConfiguration.ephemeral.httpCookieStorage)
        let url = profile.apiBaseURL.appendingPathComponent("v1/auth/pair/v2/complete/FIX346")
        let response = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Set-Cookie": "auth_refresh_token=late-fixture; Path=/; Secure; HttpOnly"]))
        let gate = WatchPairCookiePublicationGate()
        let reached = expectation(description: "Publication ready")
        let task = Task { @MainActor in
            await gate.hold(reached)
            APIClient.publishPairCompletionCookies(response, request: URLRequest(url: url), profile: profile, cookieStorage: jar)
        }
        await fulfillment(of: [reached], timeout: 3)
        task.cancel(); gate.release(); await task.value
        XCTAssertFalse((jar.cookies(for: profile.apiBaseURL) ?? []).contains { $0.name == "auth_refresh_token" })
    }
}

@MainActor
private final class WatchPairCookiePublicationGate {
    private var continuation: CheckedContinuation<Void, Never>?
    func hold(_ reached: XCTestExpectation) async {
        await withCheckedContinuation { self.continuation = $0; reached.fulfill() }
    }
    func release() { continuation?.resume(); continuation = nil }
}

private final class WatchPairCookieURLProtocol: URLProtocol, @unchecked Sendable {
    final class Fixture: @unchecked Sendable {
        private let lock = NSLock()
        let headersDelivered: XCTestExpectation
        private var active: WatchPairCookieURLProtocol?
        private var captured: URLRequest?
        var request: URLRequest? { lock.lock(); defer { lock.unlock() }; return captured }
        init(headersDelivered: XCTestExpectation) { self.headersDelivered = headersDelivered }
        func attach(_ transport: WatchPairCookieURLProtocol) {
            lock.lock(); active = transport; captured = transport.request; lock.unlock()
        }
        func finish() {
            lock.lock(); let transport = active; active = nil; lock.unlock()
            transport?.finish()
        }
    }
    private static let lock = NSLock()
    private nonisolated(unsafe) static var fixture: Fixture?
    private let stateLock = NSLock()
    private var stopped = false
    static func setFixture(_ fixture: Fixture?) { lock.lock(); self.fixture = fixture; lock.unlock() }
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host?.contains("pair-cookie-fixture") == true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let fixture = Self.fixture; Self.lock.unlock()
        guard let fixture, let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json", "Set-Cookie": "auth_refresh_token=successor-fixture; Path=/; Secure; HttpOnly"]) else {
            client?.urlProtocol(self, didFailWithError: URLError(.cancelled)); return
        }
        fixture.attach(self)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        fixture.headersDelivered.fulfill()
    }
    func finish() {
        stateLock.lock()
        guard !stopped else { stateLock.unlock(); return }
        stopped = true; stateLock.unlock()
        client?.urlProtocol(self, didLoad: Data("{}".utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { stateLock.lock(); stopped = true; stateLock.unlock() }
}
