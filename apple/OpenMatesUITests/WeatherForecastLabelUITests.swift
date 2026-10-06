// Forecast footer regression coverage through the production embed preview.
// Fixture weather values are synthetic and are never presented as live weather.
import XCTest

@MainActor
final class WeatherForecastLabelUITests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testForecastFooterUsesReadableLocalizedSkillName() {
        for (language, locale, expected) in [("en", "en_US", "Get forecast")] {
            let app = XCUIApplication()
            app.launchArguments = [
                "--dev-preview", "embeds", "--dev-preview-app", "weather",
                "--embed-registry-key", "app:weather:forecast", "--embed-surface", "preview",
                "-AppleLanguages", "(\(language))", "-AppleLocale", locale
            ]
            app.launch()
            let forecast = app.descendants(matching: .any)["weather-forecast-preview"]
            XCTAssertTrue(forecast.waitForExistence(timeout: 8))
            let title = app.staticTexts["embed-basic-info-title"].firstMatch
            XCTAssertTrue(title.waitForExistence(timeout: 5))
            XCTAssertEqual(title.label, expected)
            XCTAssertFalse(title.label.contains("app_skills."))
            XCTAssertFalse(title.label.contains("apps.weather."))
            XCTAssertGreaterThan(title.frame.width, 0)
            XCTAssertGreaterThan(title.frame.height, 0)
            XCTAssertTrue(app.windows.firstMatch.frame.intersects(title.frame))
            let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            screenshot.name = "Forecast localized footer \(language)"
            screenshot.lifetime = .keepAlways
            add(screenshot)
            app.terminate()
        }
    }
}
