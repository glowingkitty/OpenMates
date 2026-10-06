// Production ImageIO preprocessing exercised with synthetic corner pixels.
// No private photos or network transport are used.
import XCTest
import Foundation
import ImageIO
import CoreGraphics
@testable import OpenMates

final class ImageUploadPrivacyTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.surface.semantic-parity
    func testAllEXIFOrientationsBakeIntoPixelsBeforeMetadataRemoval() throws {
        let expected = [
            1: ["red", "green", "blue", "yellow"],
            2: ["green", "red", "yellow", "blue"],
            3: ["yellow", "blue", "green", "red"],
            4: ["blue", "yellow", "red", "green"],
            5: ["red", "blue", "green", "yellow"],
            6: ["blue", "red", "yellow", "green"],
            7: ["yellow", "green", "blue", "red"],
            8: ["green", "yellow", "red", "blue"]
        ]
        for orientation in 1...8 {
            let input = try fixture(orientation: orientation)
            let output = try NativeImageRaster.prepareUpload(data: input, filename: "photos/original.png", contentType: "image/png")
            XCTAssertEqual(output.filename, "photos/original.png")
            XCTAssertEqual(output.contentType, "image/png")
            let source = try XCTUnwrap(CGImageSourceCreateWithData(output.data as CFData, nil))
            let pixels = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
            XCTAssertEqual(pixels.width, orientation < 5 ? 4 : 2)
            XCTAssertEqual(pixels.height, orientation < 5 ? 2 : 4)
            XCTAssertEqual(try corners(pixels), expected[orientation], "EXIF orientation \(orientation)")
            // Existing uploaded photos also display upright before re-upload.
            let display = try XCTUnwrap(NativeImageRaster.uprightImage(from: input))
            XCTAssertEqual(try corners(display), expected[orientation])
            let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
            XCTAssertTrue(properties[kCGImagePropertyOrientation] == nil || properties[kCGImagePropertyOrientation] as? Int == 1)
            XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
            XCTAssertNil(properties[kCGImagePropertyIPTCDictionary])
            let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] ?? [:]
            XCTAssertNil(exif[kCGImagePropertyExifLensModel])
            let tiff = properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any] ?? [:]
            XCTAssertNil(tiff[kCGImagePropertyTIFFMake])
            XCTAssertNil(tiff[kCGImagePropertyTIFFModel])
            XCTAssertNil(CGImageSourceCopyMetadataAtIndex(source, 0, nil).flatMap { CGImageMetadataCopyStringValueWithPath($0, nil, "dc:description" as CFString) })
            XCTAssertNil(output.data.range(of: Data("PRIVATE-SYNTHETIC-CAMERA".utf8)))
            XCTAssertNil(output.data.range(of: Data("PRIVATE-SYNTHETIC-XMP".utf8)))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testImagePayloadFailsClosedAndOtherFileBytesAndPathsRemainExact() throws {
        XCTAssertThrowsError(try NativeImageRaster.prepareUpload(data: Data("bad image".utf8), filename: "photo.jpg", contentType: "image/jpeg"))
        let bytes = Data("fixture document bytes".utf8)
        let output = try NativeImageRaster.prepareUpload(data: bytes, filename: "workflow/source/input.txt", contentType: "text/plain")
        XCTAssertEqual(output.data, bytes)
        XCTAssertEqual(output.filename, "workflow/source/input.txt")
        XCTAssertEqual(output.contentType, "text/plain")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testSanitizedMultipartBytesRetainOriginalFilenameAndExcludeSourceMetadata() throws {
        let source = try fixture(orientation: 6)
        let prepared = try NativeImageRaster.prepareUpload(data: source, filename: "workflow/photos/original.png", contentType: "image/png")
        let body = try APIClient.makeUploadBody(data: prepared.data, filename: prepared.filename,
            contentType: prepared.contentType, chatID: "synthetic-chat", boundary: "synthetic-boundary")
        XCTAssertNotNil(body.range(of: Data("filename=\"workflow/photos/original.png\"".utf8)))
        XCTAssertNotNil(body.range(of: prepared.data))
        XCTAssertNil(body.range(of: Data("PRIVATE-SYNTHETIC-CAMERA".utf8)))
        XCTAssertNil(body.range(of: Data("PRIVATE-SYNTHETIC-XMP".utf8)))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.surface.semantic-parity
    func testJPEGOrientationAndEmbeddedMetadataRoundTrip() throws {
        for orientation in 1...8 {
            try verifyLossyRoundTrip(type: "public.jpeg", mime: "image/jpeg", extension: "jpg", orientation: orientation)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send,chats.surface.semantic-parity
    func testHEICOrientationAndEmbeddedMetadataRoundTripWhenEncoderAvailable() throws {
        guard (CGImageDestinationCopyTypeIdentifiers() as? [String])?.contains("public.heic") == true else {
            throw XCTSkip("HEIC ImageIO encoder unavailable on this test runtime")
        }
        for orientation in 1...8 {
            try verifyLossyRoundTrip(type: "public.heic", mime: "image/heic", extension: "heic", orientation: orientation)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testAnimatedGIFKeepsFramesLoopAndDelayWhileRemovingEmbeddedComment() throws {
        let output = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(output, "com.compuserve.gif" as CFString, 2, nil))
        CGImageDestinationSetProperties(destination, [kCGImagePropertyGIFDictionary: [kCGImagePropertyGIFLoopCount: 3]] as CFDictionary)
        for (color, delay) in [([UInt8(255),0,0,255], 0.12), ([UInt8(0),0,255,255], 0.34)] {
            let image = try pixels(Array(repeating: color, count: 8 * 4).flatMap { $0 }, width: 8, height: 4)
            CGImageDestinationAddImage(destination, image, [kCGImagePropertyGIFDictionary:
                [kCGImagePropertyGIFDelayTime: delay, kCGImagePropertyGIFUnclampedDelayTime: delay]] as CFDictionary)
        }
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        // A real GIF comment extension, inserted before the trailer.
        var input = output as Data
        XCTAssertEqual(input.last, 0x3B)
        let comment = Data("PRIVATE-SYNTHETIC-CAMERA".utf8)
        input.insert(contentsOf: [0x21, 0xFE, UInt8(comment.count)] + comment + [0], at: input.count - 1)
        XCTAssertNotNil(input.range(of: comment))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(input as CFData, nil))
        XCTAssertEqual(CGImageSourceGetCount(source), 2)
        let prepared = try NativeImageRaster.prepareUpload(data: input, filename: "workflow/images/animated.gif", contentType: "image/gif")
        XCTAssertEqual(prepared.filename, "workflow/images/animated.gif")
        XCTAssertEqual(prepared.contentType, "image/gif")
        XCTAssertNil(prepared.data.range(of: comment))
        let result = try XCTUnwrap(CGImageSourceCreateWithData(prepared.data as CFData, nil))
        XCTAssertEqual(CGImageSourceGetCount(result), 2)
        let global = try XCTUnwrap(CGImageSourceCopyProperties(result, nil) as? [CFString: Any])
        XCTAssertEqual((global[kCGImagePropertyGIFDictionary] as? [CFString: Any])?[kCGImagePropertyGIFLoopCount] as? Int, 3)
        for index in 0..<2 {
            let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(result, index, nil))
            XCTAssertEqual(image.width, 8)
            XCTAssertEqual(image.height, 4)
            XCTAssertEqual(try corners(image), Array(repeating: index == 0 ? "red" : "blue", count: 4))
            let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(result, index, nil) as? [CFString: Any])
            let timing = try XCTUnwrap(properties[kCGImagePropertyGIFDictionary] as? [CFString: Any])
            XCTAssertEqual(try XCTUnwrap(timing[kCGImagePropertyGIFDelayTime] as? Double), index == 0 ? 0.12 : 0.34, accuracy: 0.011)
            XCTAssertEqual(try XCTUnwrap(timing[kCGImagePropertyGIFUnclampedDelayTime] as? Double), index == 0 ? 0.12 : 0.34, accuracy: 0.011)
            XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
            XCTAssertNil(properties[kCGImagePropertyIPTCDictionary])
        }
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testMultiframeTIFFFailsClosedRatherThanDroppingFrames() throws {
        let output = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(output, "public.tiff" as CFString, 2, nil))
        for color in [[UInt8(255),0,0,255], [UInt8(0),0,255,255]] {
            let image = try pixels(Array(repeating: color, count: 8 * 4).flatMap { $0 }, width: 8, height: 4)
            CGImageDestinationAddImage(destination, image, nil)
        }
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(output, nil))
        XCTAssertEqual(CGImageSourceGetCount(source), 2)
        do {
            _ = try NativeImageRaster.prepareUpload(data: output as Data, filename: "workflow/scans/original.tiff", contentType: "image/tiff")
            XCTFail("Multiframe TIFF must be rejected")
        } catch NativeImageRaster.ProcessingError.unsupportedImage {
            // Required fail-closed outcome.
        }
    }

    private func verifyLossyRoundTrip(type: String, mime: String, extension suffix: String, orientation: Int) throws {
        let expected = [1: ["red", "green", "blue", "yellow"], 2: ["green", "red", "yellow", "blue"],
            3: ["yellow", "blue", "green", "red"], 4: ["blue", "yellow", "red", "green"],
            5: ["red", "blue", "green", "yellow"], 6: ["blue", "red", "yellow", "green"],
            7: ["yellow", "green", "blue", "red"], 8: ["green", "yellow", "red", "blue"]]
        let input = try fixture(orientation: orientation, type: type, width: 64, height: 32)
        let filename = "workflow/photos/original.\(suffix)"
        let prepared = try NativeImageRaster.prepareUpload(data: input, filename: filename, contentType: mime)
        XCTAssertEqual(prepared.filename, filename)
        XCTAssertEqual(prepared.contentType, mime)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(prepared.data as CFData, nil))
        XCTAssertEqual(CGImageSourceGetType(source) as String?, type)
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertEqual(image.width, orientation < 5 ? 64 : 32)
        XCTAssertEqual(image.height, orientation < 5 ? 32 : 64)
        // corners() allows channel deltas of up to 55 for JPEG/HEIC compression.
        XCTAssertEqual(try corners(image), expected[orientation])
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertTrue(properties[kCGImagePropertyOrientation] == nil || properties[kCGImagePropertyOrientation] as? Int == 1)
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        XCTAssertNil(properties[kCGImagePropertyIPTCDictionary])
        XCTAssertNil((properties[kCGImagePropertyExifDictionary] as? [CFString: Any])?[kCGImagePropertyExifLensModel])
        XCTAssertNil((properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any])?[kCGImagePropertyTIFFMake])
        XCTAssertNil((properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any])?[kCGImagePropertyTIFFModel])
        XCTAssertNil(CGImageSourceCopyMetadataAtIndex(source, 0, nil).flatMap { CGImageMetadataCopyStringValueWithPath($0, nil, "dc:description" as CFString) })
        XCTAssertNil(prepared.data.range(of: Data("PRIVATE-SYNTHETIC-CAMERA".utf8)))
        XCTAssertNil(prepared.data.range(of: Data("PRIVATE-SYNTHETIC-XMP".utf8)))
    }

    private func pixels(_ bytes: [UInt8], width: Int, height: Int) throws -> CGImage {
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        return try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
    }

    private func fixture(orientation: Int, type: String = "public.png", width: Int = 4, height: Int = 2) throws -> Data {
        let colors: [[UInt8]] = [[255,0,0,255], [0,255,0,255], [0,0,255,255], [255,255,0,255]]
        var bytes: [UInt8] = []
        for y in 0..<height {
            for x in 0..<width { bytes += colors[(y < height / 2 ? 0 : 2) + (x < width / 2 ? 0 : 1)] }
        }
        let image = try pixels(bytes, width: width, height: height)
        let output = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(output, type as CFString, 1, nil))
        let metadata = try XCTUnwrap(CGImageMetadataCreateMutable())
        XCTAssertTrue(CGImageMetadataRegisterNamespaceForPrefix(metadata, "http://purl.org/dc/elements/1.1/" as CFString, "dc" as CFString, nil))
        XCTAssertTrue(CGImageMetadataSetValueWithPath(metadata, nil, "dc:description" as CFString, "PRIVATE-SYNTHETIC-XMP" as CFString))
        CGImageDestinationAddImageAndMetadata(destination, image, metadata, [
            kCGImagePropertyOrientation: orientation,
            kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 51.0, kCGImagePropertyGPSLongitude: 13.0],
            kCGImagePropertyExifDictionary: [kCGImagePropertyExifLensModel: "PRIVATE-SYNTHETIC-CAMERA"],
            kCGImagePropertyTIFFDictionary: [kCGImagePropertyTIFFMake: "PRIVATE-SYNTHETIC-CAMERA", kCGImagePropertyTIFFModel: "fixture"],
            kCGImagePropertyIPTCDictionary: [kCGImagePropertyIPTCCaptionAbstract: "PRIVATE-SYNTHETIC-CAMERA"]
        ] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let source = try XCTUnwrap(CGImageSourceCreateWithData(output, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual(properties[kCGImagePropertyOrientation] as? Int, orientation, "Fixture must contain actual EXIF orientation")
        XCTAssertNotNil(properties[kCGImagePropertyGPSDictionary], "Fixture must contain metadata before removal")
        XCTAssertNotNil((properties[kCGImagePropertyExifDictionary] as? [CFString: Any])?[kCGImagePropertyExifLensModel])
        XCTAssertNotNil((properties[kCGImagePropertyTIFFDictionary] as? [CFString: Any])?[kCGImagePropertyTIFFMake])
        XCTAssertNotNil(properties[kCGImagePropertyIPTCDictionary])
        XCTAssertNotNil(CGImageSourceCopyMetadataAtIndex(source, 0, nil).flatMap { CGImageMetadataCopyStringValueWithPath($0, nil, "dc:description" as CFString) })
        return output as Data
    }

    private func corners(_ image: CGImage) throws -> [String] {
        var bytes = [UInt8](repeating: 0, count: image.width * image.height * 4)
        let ok = bytes.withUnsafeMutableBytes { buffer -> Bool in
            guard let context = CGContext(data: buffer.baseAddress, width: image.width, height: image.height,
                bitsPerComponent: 8, bytesPerRow: image.width * 4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return false }
            context.interpolationQuality = .none
            context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
            return true
        }
        XCTAssertTrue(ok)
        return [(0,0), (image.width-1,0), (0,image.height-1), (image.width-1,image.height-1)].map { x,y in
            let index = (y * image.width + x) * 4
            let r = bytes[index], g = bytes[index+1], b = bytes[index+2]
            if r > 200 && g < 50 && b < 50 { return "red" }
            if r < 50 && g > 200 && b < 50 { return "green" }
            if r < 50 && g < 50 && b > 200 { return "blue" }
            if r > 200 && g > 200 && b < 50 { return "yellow" }
            return "unexpected \(r),\(g),\(b)"
        }
    }
}
