#!/usr/bin/env swift
// Compare a deployed web embed screenshot with an Apple simulator screenshot.
// Produces a side-by-side composite, diff heatmap, and JSON metrics.
//
// Usage:
//   swift scripts/apple_embed_visual_compare.swift \
//     --web /tmp/web.png --ios /tmp/ios.png --out /tmp/embed-compare \
//     --name web-search --web-crop 0,0,300,640 --ios-crop 38,296,300,640

import AppKit
import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

struct Options {
    var webPath: String?
    var iosPath: String?
    var outputDirectory: String?
    var name = "embed-compare"
    var webCrop: CGRect?
    var iosCrop: CGRect?
}

func parseCrop(_ value: String) -> CGRect? {
    let parts = value.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
    guard parts.count == 4 else { return nil }
    return CGRect(x: parts[0], y: parts[1], width: parts[2], height: parts[3])
}

struct PixelBuffer {
    let width: Int
    let height: Int
    let bytes: [UInt8]
}

func parseOptions() -> Options {
    var options = Options()
    var index = 1
    let args = CommandLine.arguments
    while index < args.count {
        let arg = args[index]
        func nextValue() -> String? {
            let next = index + 1
            guard next < args.count else { return nil }
            index += 1
            return args[next]
        }
        switch arg {
        case "--web":
            options.webPath = nextValue()
        case "--ios":
            options.iosPath = nextValue()
        case "--out":
            options.outputDirectory = nextValue()
        case "--name":
            options.name = nextValue() ?? options.name
        case "--crop":
            if let value = nextValue() {
                let crop = parseCrop(value)
                options.webCrop = crop
                options.iosCrop = crop
            }
        case "--web-crop":
            if let value = nextValue() {
                options.webCrop = parseCrop(value)
            }
        case "--ios-crop":
            if let value = nextValue() {
                options.iosCrop = parseCrop(value)
            }
        case "--help", "-h":
            print("Usage: swift scripts/apple_embed_visual_compare.swift --web WEB.png --ios IOS.png --out DIR [--name NAME] [--crop x,y,w,h] [--web-crop x,y,w,h] [--ios-crop x,y,w,h]")
            exit(0)
        default:
            break
        }
        index += 1
    }
    return options
}

func fail(_ message: String) -> Never {
    fputs("error: \(message)\n", stderr)
    exit(1)
}

func loadImage(path: String, crop: CGRect?) -> NSImage {
    guard let image = NSImage(contentsOfFile: path) else {
        fail("Could not load image at \(path)")
    }
    guard let crop else { return image }
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        fail("Could not decode image at \(path)")
    }
    let integralCrop = crop.integral
    guard let cropped = cgImage.cropping(to: integralCrop) else {
        fail("Crop \(crop) is outside image bounds for \(path)")
    }
    return NSImage(cgImage: cropped, size: integralCrop.size)
}

func renderBuffer(image: NSImage, width: Int, height: Int) -> PixelBuffer {
    var bytes = [UInt8](repeating: 0, count: width * height * 4)
    guard let context = CGContext(
        data: &bytes,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: width * 4,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        fail("Could not create bitmap context")
    }

    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
    image.draw(in: CGRect(x: 0, y: 0, width: width, height: height))
    NSGraphicsContext.restoreGraphicsState()
    return PixelBuffer(width: width, height: height, bytes: bytes)
}

func imageFromBuffer(_ buffer: PixelBuffer) -> NSImage {
    let mutableBytes = buffer.bytes
    guard let provider = CGDataProvider(data: Data(mutableBytes) as CFData),
          let cgImage = CGImage(
            width: buffer.width,
            height: buffer.height,
            bitsPerComponent: 8,
            bitsPerPixel: 32,
            bytesPerRow: buffer.width * 4,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
          ) else {
        fail("Could not create image from buffer")
    }
    return NSImage(cgImage: cgImage, size: NSSize(width: buffer.width, height: buffer.height))
}

func savePNG(_ image: NSImage, path: String) {
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil),
          let destination = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        fail("Could not prepare PNG output at \(path)")
    }
    CGImageDestinationAddImage(destination, cgImage, nil)
    guard CGImageDestinationFinalize(destination) else {
        fail("Could not write PNG at \(path)")
    }
}

func sideBySide(web: NSImage, ios: NSImage, width: Int, height: Int) -> NSImage {
    let gap = 24
    let labelHeight = 34
    let size = NSSize(width: width * 2 + gap, height: height + labelHeight)
    let image = NSImage(size: size)
    image.lockFocus()
    NSColor(calibratedWhite: 0.95, alpha: 1).setFill()
    NSRect(origin: .zero, size: size).fill()
    web.draw(in: NSRect(x: 0, y: 0, width: width, height: height))
    ios.draw(in: NSRect(x: width + gap, y: 0, width: width, height: height))
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 14, weight: .semibold),
        .foregroundColor: NSColor.black
    ]
    NSString(string: "Web baseline").draw(at: NSPoint(x: 8, y: height + 8), withAttributes: attrs)
    NSString(string: "Apple simulator").draw(at: NSPoint(x: width + gap + 8, y: height + 8), withAttributes: attrs)
    image.unlockFocus()
    return image
}

let options = parseOptions()
guard let webPath = options.webPath,
      let iosPath = options.iosPath,
      let outputDirectory = options.outputDirectory else {
    fail("Missing required --web, --ios, or --out argument. Use --help for usage.")
}

try FileManager.default.createDirectory(atPath: outputDirectory, withIntermediateDirectories: true)

let webImage = loadImage(path: webPath, crop: options.webCrop)
let iosImage = loadImage(path: iosPath, crop: options.iosCrop)
let webSize = webImage.size
let width = max(1, Int(webSize.width.rounded()))
let height = max(1, Int(webSize.height.rounded()))
let webBuffer = renderBuffer(image: webImage, width: width, height: height)
let iosBuffer = renderBuffer(image: iosImage, width: width, height: height)

var diffBytes = [UInt8](repeating: 0, count: width * height * 4)
var totalDelta: Double = 0
var changedPixels = 0
let pixelCount = width * height

for pixel in 0..<pixelCount {
    let offset = pixel * 4
    let dr = abs(Int(webBuffer.bytes[offset]) - Int(iosBuffer.bytes[offset]))
    let dg = abs(Int(webBuffer.bytes[offset + 1]) - Int(iosBuffer.bytes[offset + 1]))
    let db = abs(Int(webBuffer.bytes[offset + 2]) - Int(iosBuffer.bytes[offset + 2]))
    let delta = max(dr, dg, db)
    totalDelta += Double(dr + dg + db) / (255.0 * 3.0)
    if delta > 12 { changedPixels += 1 }
    diffBytes[offset] = UInt8(min(255, delta * 3))
    diffBytes[offset + 1] = 0
    diffBytes[offset + 2] = UInt8(max(0, 180 - delta))
    diffBytes[offset + 3] = 255
}

let mismatchPercent = Double(changedPixels) / Double(pixelCount) * 100.0
let averageDeltaPercent = totalDelta / Double(pixelCount) * 100.0
let diffImage = imageFromBuffer(PixelBuffer(width: width, height: height, bytes: diffBytes))
let composite = sideBySide(web: webImage, ios: iosImage, width: width, height: height)

let base = "\(outputDirectory)/\(options.name)"
savePNG(composite, path: "\(base)-side-by-side.png")
savePNG(diffImage, path: "\(base)-diff.png")

let json = """
{
  "name": "\(options.name)",
  "width": \(width),
  "height": \(height),
  "mismatchPercent": \(String(format: "%.4f", mismatchPercent)),
  "averageDeltaPercent": \(String(format: "%.4f", averageDeltaPercent)),
  "sideBySide": "\(base)-side-by-side.png",
  "diff": "\(base)-diff.png"
}
"""
try json.write(toFile: "\(base)-metrics.json", atomically: true, encoding: .utf8)
print(json)
