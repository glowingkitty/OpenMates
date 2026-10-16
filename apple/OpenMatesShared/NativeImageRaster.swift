// Client-side raster upload preparation shared by main apps and Share Extensions.
// Web source: frontend/packages/ui/src/services/uploadService.ts
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.embeds.gated-send
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity
import Foundation
import ImageIO
import CoreGraphics

/// ImageIO decodes EXIF orientation into pixels before source metadata is
/// discarded. Shared by upload sanitization and existing encrypted previews.
/// Specification: specifications/features/message-input/specification.yml
/// Assertions: message-input.embeds.gated-send
/// Specification: specifications/features/chats/specification.yml
/// Assertions: chats.surface.semantic-parity
struct NativeImageRaster {
    struct UploadPayload {
        let data: Data
        let filename: String
        let contentType: String
    }

    enum ProcessingError: Error { case invalidImage, unsupportedImage, encodingFailed }

    static func uprightImage(from data: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        return uprightImage(source: source, index: 0)
    }

    private static func uprightImage(source: CGImageSource, index: Int) -> CGImage? {
        guard let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              width > 0, height > 0 else { return nil }
        // Use the original pixel extent: this normalizes orientation without
        // resizing the source or changing the preview container.
        return CGImageSourceCreateThumbnailAtIndex(source, index, [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(width, height),
            kCGImageSourceShouldCacheImmediately: true
        ] as CFDictionary)
    }

    static func prepareUpload(data: Data, filename: String, contentType: String) throws -> UploadPayload {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let type = CGImageSourceGetType(source) as String? else {
            // Other document/audio formats retain their existing bytes. Their
            // metadata stripping is a separate, unfinished privacy task.
            // A misleading MIME type must not send undecodable image bytes raw.
            let imageExtensions: Set<String> = ["jpg", "jpeg", "png", "gif", "heic", "heif", "bmp", "webp",
                "tif", "tiff", "svg", "avif", "dng", "ico"]
            guard !contentType.lowercased().hasPrefix("image/"),
                  !imageExtensions.contains((filename as NSString).pathExtension.lowercased()) else {
                throw ProcessingError.invalidImage
            }
            return UploadPayload(data: data, filename: filename, contentType: contentType)
        }
        let mimeTypes = ["public.jpeg": "image/jpeg", "public.png": "image/png",
            "public.tiff": "image/tiff", "com.compuserve.gif": "image/gif",
            "public.heic": "image/heic", "public.heif": "image/heif",
            "com.microsoft.bmp": "image/bmp", "org.webmproject.webp": "image/webp"]
        guard let mimeType = mimeTypes[type] else { throw ProcessingError.unsupportedImage }
        let frameCount = CGImageSourceGetCount(source)
        guard frameCount > 0 else { throw ProcessingError.invalidImage }
        // GIF animation gets only its timing/loop properties. Unsupported
        // multi-frame containers fail closed rather than silently losing frames.
        guard frameCount == 1 || type == "com.compuserve.gif" else { throw ProcessingError.unsupportedImage }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, type as CFString, frameCount, nil) else {
            throw ProcessingError.unsupportedImage
        }
        if type == "com.compuserve.gif",
           let properties = CGImageSourceCopyProperties(source, nil) as? [CFString: Any],
           let gif = properties[kCGImagePropertyGIFDictionary] as? [CFString: Any],
           let loopCount = gif[kCGImagePropertyGIFLoopCount] {
            CGImageDestinationSetProperties(destination, [kCGImagePropertyGIFDictionary:
                [kCGImagePropertyGIFLoopCount: loopCount]] as CFDictionary)
        }
        for index in 0..<frameCount {
            guard let pixels = uprightImage(source: source, index: index) else { throw ProcessingError.invalidImage }
            var properties: [CFString: Any] = [kCGImagePropertyOrientation: 1]
            if type == "public.jpeg" { properties[kCGImageDestinationLossyCompressionQuality] = 0.95 }
            if type == "com.compuserve.gif",
               let sourceProperties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
               let gif = sourceProperties[kCGImagePropertyGIFDictionary] as? [CFString: Any] {
                var timing: [CFString: Any] = [:]
                for key in [kCGImagePropertyGIFDelayTime, kCGImagePropertyGIFUnclampedDelayTime] {
                    timing[key] = gif[key]
                }
                properties[kCGImagePropertyGIFDictionary] = timing
            }
            // Encode decoded pixels; never copy source EXIF/GPS/TIFF camera,
            // XMP, IPTC, comments or image metadata into the destination.
            CGImageDestinationAddImage(destination, pixels, properties as CFDictionary)
        }
        guard CGImageDestinationFinalize(destination) else { throw ProcessingError.encodingFailed }
        return UploadPayload(data: output as Data, filename: filename, contentType: mimeType)
    }
}
