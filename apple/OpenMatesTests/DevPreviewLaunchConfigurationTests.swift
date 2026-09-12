// Pure configuration checks for debug-only isolated component previews.
// Keep malformed requests inside the preview error surface, never normal auth.
// Verify URL/argument/environment equivalence and bounded, typed synthetic props.
// These tests do not launch an app, restore an account, or access a network.
// Registry metadata is a reference mapping, not proof of rendered parity.

import XCTest
@testable import OpenMates

#if DEBUG
final class DevPreviewLaunchConfigurationTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testAbsentPreviewRequestDoesNotChangeProductStartup() throws {
        XCTAssertNil(DevPreviewLaunchConfiguration.parse(environment: ["LANG": "en_US"]))
        XCTAssertNil(DevPreviewLaunchConfiguration.parse(arguments: ["OpenMates", "--ui-test-prefer-password-login"]))
        XCTAssertNil(DevPreviewLaunchConfiguration.parse(url: try XCTUnwrap(URL(string: "openmates://chat/synthetic-chat"))))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testURLArgumentsAndEnvironmentHaveSameConfigurationIdentity() throws {
        let props = #"{"markdown":"Synthetic 🪐 message","compact":false,"count":3,"tags":["a","b"]}"#
        let environment = [
            "DEV_PREVIEW": "composer", "DEV_PREVIEW_VARIANT": "filled",
            "DEV_PREVIEW_THEME": "dark", "DEV_PREVIEW_WIDTH": "390",
            "DEV_PREVIEW_HEIGHT": "844", "DEV_PREVIEW_PROPS": props
        ]
        let fromEnvironment = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: environment))
        let fromArguments = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(arguments: [
            "OpenMates", "--dev-preview", "component", "--dev-preview-component", "composer",
            "--dev-preview-variant", "filled", "--dev-preview-theme", "dark",
            "--dev-preview-width", "390", "--dev-preview-height", "844", "--dev-preview-props", props
        ]))
        let url = try previewURL(path: "enter_message/MessageInput", query: [
            "variant": "filled", "theme": "dark", "width": "390", "height": "844", "props": props, "chrome": "0"
        ])
        let fromURL = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(url: url))
        XCTAssertNil(fromEnvironment.error)
        XCTAssertEqual(fromEnvironment.component, .composer)
        XCTAssertEqual(fromEnvironment, fromArguments)
        XCTAssertEqual(fromArguments, fromURL)
        XCTAssertEqual(Set([fromEnvironment, fromArguments, fromURL]).count, 1)
        XCTAssertEqual(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW_URL": url.absoluteString]), fromURL)
        XCTAssertEqual(DevPreviewLaunchConfiguration.parse(arguments: ["--dev-preview-url", url.absoluteString]), fromURL)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLegacyLaunchesRemainCompatibleAndRoutesMatchExactly() throws {
        let surfaces: [DevPreviewLaunchConfiguration.Surface] = [
            .chatOpening, .chatOpeningRecording, .chatShare, .embedShare,
            .quickCapture, .composerEmbeds, .composerDraftEdit, .embeds
        ]
        for surface in surfaces {
            let expected = DevPreviewLaunchConfiguration(surface: surface, appSlug: .web)
            XCTAssertEqual(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW": surface.rawValue]), expected)
            XCTAssertEqual(DevPreviewLaunchConfiguration.parse(arguments: ["--dev-preview", surface.rawValue]), expected)
            XCTAssertEqual(DevPreviewLaunchConfiguration.parse(url: try XCTUnwrap(URL(string: "openmates://dev/preview/\(surface.rawValue)"))), expected)
            XCTAssertEqual(DevPreviewLaunchConfiguration.parse(url: try previewURL(path: surface.rawValue)), expected)
        }
        let gallery = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(url: try previewURL(path: "embeds/code")))
        XCTAssertEqual(gallery.surface, .embeds)
        XCTAssertEqual(gallery.appSlug, .code)
        for route in ["chat-opening-extra", "chat-opening/extra", "embeds/code/extra", "composer/", "component/composer/extra"] {
            XCTAssertNotNil(DevPreviewLaunchConfiguration.parse(url: try previewURL(path: route))?.error, route)
        }
        for raw in [
            "openmates://dev/preview/composer/",
            "openmates://dev/preview/composer/?theme=dark",
            "openmates://dev/preview/composer%2F",
            "https://app.dev.openmates.org/dev/preview/enter_message/MessageInput/"
        ] {
            let configuration = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(url: try XCTUnwrap(URL(string: raw))))
            XCTAssertNotNil(configuration.error, raw)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testUntrustedOriginsAndAmbiguousURLValuesStayInPreviewErrorState() throws {
        let rejected = [
            "https://example.com/dev/preview/composer",
            "https://app.openmates.org/dev/preview/composer",
            "http://app.dev.openmates.org/dev/preview/composer",
            "https://app.dev.openmates.org:444/dev/preview/composer",
            "https://user:password@app.dev.openmates.org/dev/preview/composer",
            "https://app.dev.openmates.org/dev/preview/composer#fragment",
            "openmates://dev:443/preview/composer",
            "openmates://wrong-host/preview/composer",
            "openmates://dev/preview/composer?theme=light&theme=dark",
            "openmates://dev/preview/composer?theme",
            "openmates://dev/preview/composer?unknown=1",
            "openmates://dev/preview/composer?chrome=1",
            "openmates://dev/preview/embeds/code?app=web"
        ]
        for raw in rejected {
            let parsed = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(url: try XCTUnwrap(URL(string: raw))))
            XCTAssertNotNil(parsed.error, raw)
        }
        for origin in ["http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173"] {
            XCTAssertNil(DevPreviewLaunchConfiguration.parse(url: try XCTUnwrap(URL(string: "\(origin)/dev/preview/composer")))?.error)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMalformedRequestedInputsNeverFallThroughToNormalStartup() throws {
        let arguments = [
            ["--dev-preview"], ["--dev-preview", ""], ["--dev-preview", "unknown"],
            ["--dev-preview", "composer", "--dev-preview-theme"],
            ["--dev-preview", "composer", "--dev-preview", "message"],
            ["--dev-preview-unknown", "x"], ["--dev-preview-url", "not-a-preview"],
            ["--dev-preview-url", "openmates://dev/preview/composer", "--dev-preview-theme", "dark"]
        ]
        for values in arguments {
            let parsed = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(arguments: values))
            XCTAssertNotNil(parsed.error)
        }
        let environments = [
            ["DEV_PREVIEW": ""], ["DEV_PREVIEW": "unknown"], ["DEV_PREVIEW_THEME": "dark"],
            ["DEV_PREVIEW": "composer", "DEV_PREVIEW_UNRECOGNIZED": "x"],
            ["DEV_PREVIEW_URL": "not-a-preview"],
            ["DEV_PREVIEW_URL": "openmates://dev/preview/composer", "DEV_PREVIEW": "composer"],
            ["DEV_PREVIEW_URL": "openmates://dev/preview/composer", "DEV_PREVIEW_UNRECOGNIZED": "x"]
        ]
        for values in environments {
            let parsed = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: values))
            XCTAssertNotNil(parsed.error)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPropsAndViewportValidationAreBoundedAndTyped() throws {
        let nested = String(repeating: #"{"nested":"#, count: 10) + "0" + String(repeating: "}", count: 10)
        let oversizedArray = "{\"items\":[" + Array(repeating: "0", count: 201).joined(separator: ",") + "]}"
        let badProps = ["[]", "null", "true", "{broken", nested, oversizedArray,
                        "{\"text\":\"" + String(repeating: "🪐", count: 2_501) + "\"}"]
        for props in badProps {
            XCTAssertNotNil(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW": "composer", "DEV_PREVIEW_PROPS": props])?.error)
        }
        for width in ["239", "2561", "390.5", "nan", "-1", ""] {
            XCTAssertNotNil(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW": "composer", "DEV_PREVIEW_WIDTH": width])?.error)
        }
        for option in [["DEV_PREVIEW_THEME": "unknown"], ["DEV_PREVIEW_VARIANT": "unknown"], ["DEV_PREVIEW_APP": "unknown"]] {
            XCTAssertNotNil(DevPreviewLaunchConfiguration.parse(environment: option.merging(["DEV_PREVIEW": "composer"]) { first, _ in first })?.error)
        }
        struct Fixture: Decodable, Equatable { let title: String; let count: Int; let enabled: Bool }
        let configuration = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: [
            "DEV_PREVIEW": "composer", "DEV_PREVIEW_PROPS": #"{"title":"Synthetic","count":3,"enabled":false}"#
        ]))
        XCTAssertEqual(try configuration.decodeProps(Fixture.self), Fixture(title: "Synthetic", count: 3, enabled: false))
        XCTAssertEqual(configuration.props["count"]?.int, 3)
        XCTAssertNil(configuration.props["enabled"]?.int)
        XCTAssertNil(configuration.props["count"]?.bool)
        XCTAssertNil(DevPreviewJSONValue.number(1.5).int)
        XCTAssertNil(DevPreviewJSONValue.number(1e100).int)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testVariantThemeViewportAndPropsChangeIdentityAndHistoryWelcomeRoutesAreImplemented() throws {
        let original = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW": "composer"]))
        for change in [["DEV_PREVIEW_THEME": "dark"], ["DEV_PREVIEW_WIDTH": "390"], ["DEV_PREVIEW_VARIANT": "filled"], ["DEV_PREVIEW_PROPS": #"{"markdown":"changed"}"#]] {
            let changed = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: change.merging(["DEV_PREVIEW": "composer"]) { first, _ in first }))
            XCTAssertNil(changed.error)
            XCTAssertEqual(Set([original, changed]).count, 2)
        }
        for component in [DevPreviewComponent.history, .welcome] {
            let configuration = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: ["DEV_PREVIEW": component.rawValue]))
            XCTAssertEqual(configuration.component, component)
            XCTAssertEqual(component.descriptor.hostSupport, .componentHost)
            XCTAssertNil(configuration.error)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=auth.surface.first-party-boundary
    func testAuthHostsAcceptOnlyImplementedStagesAndResetForDistinctVariants() throws {
        for component in [DevPreviewComponent.login, .signup] {
            XCTAssertEqual(component.descriptor.hostSupport, .componentHost)
            for variant in component.descriptor.variants {
                let configured = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: [
                    "DEV_PREVIEW": component.rawValue, "DEV_PREVIEW_VARIANT": variant
                ]))
                XCTAssertNil(configured.error)
                XCTAssertEqual(configured.component, component)
                XCTAssertEqual(configured.variant, variant)
            }
        }
        for unsupported in ["recovery-key", "complete"] {
            XCTAssertNotNil(DevPreviewLaunchConfiguration.parse(environment: [
                "DEV_PREVIEW": "signup", "DEV_PREVIEW_VARIANT": unsupported
            ])?.error)
        }
        let password = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: [
            "DEV_PREVIEW": "login", "DEV_PREVIEW_VARIANT": "password"
        ]))
        let otp = try XCTUnwrap(DevPreviewLaunchConfiguration.parse(environment: [
            "DEV_PREVIEW": "login", "DEV_PREVIEW_VARIANT": "otp"
        ]))
        XCTAssertNotEqual(password, otp)
    }

    private func previewURL(path: String, query: [String: String] = [:]) throws -> URL {
        var components = URLComponents()
        components.scheme = "https"
        components.host = "app.dev.openmates.org"
        components.path = "/dev/preview/" + path
        components.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        return try XCTUnwrap(components.url)
    }
}
#endif
