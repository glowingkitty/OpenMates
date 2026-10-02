// MathPlot's web function-plot viewport, tick and supported-expression guards.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import XCTest
@testable import OpenMates

final class MathPlotGeometryParityTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWebViewportKeepsHorizontalDomainAndInsetSquareUnits() {
        let geometry = MathPlotGeometry(size: CGSize(width: 370, height: 446))
        XCTAssertEqual(geometry.bounds, CGRect(x: 40, y: 20, width: 310, height: 406))
        XCTAssertEqual(geometry.xRange.lowerBound, -6, accuracy: 0.001)
        XCTAssertEqual(geometry.xRange.upperBound, 6, accuracy: 0.001)
        XCTAssertEqual(geometry.yRange.upperBound, 406 * 6 / 310, accuracy: 0.001)
        XCTAssertEqual(MathPlotGeometry.ticks(in: geometry.xRange), Array(-6...6).map(Double.init))
        XCTAssertEqual(MathPlotGeometry.ticks(in: geometry.yRange), [-6, -4, -2, 0, 2, 4, 6])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPanAndZoomMoveDomainAndResponsiveHeightRetainsWideMinimum() {
        let initial = MathPlotGeometry(size: CGSize(width: 370, height: 446))
        let moved = MathPlotGeometry(size: CGSize(width: 370, height: 446), zoom: 2,
                                     offset: CGSize(width: initial.unit * 2, height: initial.unit))
        XCTAssertEqual(moved.xRange.lowerBound, -4, accuracy: 0.001)
        XCTAssertEqual(moved.xRange.upperBound, 2, accuracy: 0.001)
        XCTAssertEqual(MathPlotGeometry.graphHeight(viewportHeight: 874, formulaCount: 3), 449)
        XCTAssertEqual(MathPlotGeometry.graphHeight(viewportHeight: 402, formulaCount: 3), 200)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFullViewportHeightProducesWebVerticalDomainAndTwoUnitTicks() {
        let height = MathPlotGeometry.graphHeight(viewportHeight: 874, formulaCount: 3)
        let geometry = MathPlotGeometry(size: CGSize(width: 370, height: height))
        XCTAssertGreaterThan(geometry.yRange.upperBound, 7.8)
        XCTAssertLessThan(geometry.yRange.upperBound, 8)
        XCTAssertEqual(MathPlotGeometry.ticks(in: geometry.yRange), [-6, -4, -2, 0, 2, 4, 6])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testLargeDiagonalPanKeepsVisibleLinearCurveSamples() throws {
        let geometry = MathPlotGeometry(size: CGSize(width: 370, height: 240),
                                        offset: CGSize(width: -1200, height: 1200))
        let expression = MathPlotExpression("y = x")
        let visiblePoint = try XCTUnwrap(geometry.sample(expression, at: 215))
        XCTAssertEqual(visiblePoint.x, 215, accuracy: 0.001)
        XCTAssertEqual(visiblePoint.y, 100, accuracy: 0.001)
        XCTAssertTrue(geometry.bounds.contains(visiblePoint))
        // This visible point was incorrectly culled against the panned origin.
        XCTAssertGreaterThan(abs(visiblePoint.y - geometry.origin.y), geometry.bounds.height * 4)
        let visibleSamples = stride(from: geometry.bounds.minX, through: geometry.bounds.maxX, by: 1)
            .compactMap { geometry.sample(expression, at: $0) }
            .filter { geometry.bounds.contains($0) }
        XCTAssertGreaterThan(visibleSamples.count, 190)
        XCTAssertNil(geometry.sample(MathPlotExpression("10000"), at: geometry.bounds.midX),
                     "Offscreen samples must still have a bounded culling margin")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPublicTrigonometricFixtureAndUnsupportedExpressionSignal() {
        XCTAssertEqual(MathPlotExpression("f(x) = sin(x)").value(at: .pi / 2)!, 1, accuracy: 0.001)
        XCTAssertEqual(MathPlotExpression("f(x) = cos(x)").value(at: 0), 1)
        XCTAssertEqual(MathPlotExpression("f(x) = tan(x)").value(at: 0), 0)
        XCTAssertEqual(MathPlotExpression("y = x^2").value(at: -2), 4)
        XCTAssertEqual(MathPlotExpression("3.5").value(at: -2), 3.5)
        XCTAssertFalse(MathPlotExpression("f(x) = sqrt(x)").isSupported)
        XCTAssertNil(MathPlotExpression("f(x) = sqrt(x)").value(at: 1))
    }
}
