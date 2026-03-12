/**
 * Resizes an image blob so its largest dimension does not exceed maxDimension pixels,
 * preserving the original aspect ratio. If the image is already within the limit it is
 * returned as-is (re-encoded at quality 0.85 for JPEG to normalise file size).
 *
 * This is used to cap camera captures and file-picker images before they are uploaded
 * to the server, improving upload speed and reducing storage usage while keeping
 * enough resolution for AI analysis.
 *
 * Default is 1280px: sufficient for AI vision analysis and roughly 3–5× smaller than
 * typical phone camera photos compared to the previous 2048px limit, significantly
 * reducing upload time, ClamAV scan time, SightEngine API transfer, and S3 upload size.
 *
 * SVG files are passed through as-is — they are rasterized server-side by cairosvg.
 * Client-side canvas operations on SVGs are unreliable: SVGs without explicit width/height
 * attributes render at 0×0 on the canvas, causing toBlob() to return null.  The server
 * handles SVG→WEBP conversion correctly, so we skip client-side resizing for SVGs.
 *
 * @param blob         Original image blob (JPEG, PNG, WebP, HEIC, SVG, etc.)
 * @param maxDimension Maximum allowed width OR height in pixels (default 1280)
 * @returns Promise resolving to the resized blob and an object URL for immediate display
 */
export async function resizeForUpload(
  blob: Blob,
  maxDimension: number = 1280,
): Promise<{ resizedBlob: Blob; resizedUrl: string }> {
  // SVGs are rasterized server-side — skip client-side canvas operations.
  // The server uses cairosvg to convert SVG → PNG → WEBP, which handles
  // dimension-less SVGs (viewBox-only, common from Figma) correctly.
  if (blob.type === "image/svg+xml") {
    console.debug(
      "[imageHelpers] SVG detected — skipping client-side resize (server handles SVG→WEBP via cairosvg)",
    );
    const svgUrl = URL.createObjectURL(blob);
    return { resizedBlob: blob, resizedUrl: svgUrl };
  }

  const img = new Image();
  const objectUrl = URL.createObjectURL(blob);

  return new Promise((resolve, reject) => {
    img.onload = () => {
      const { width, height } = img;
      const largest = Math.max(width, height);

      // Determine output MIME type — keep PNG for transparency, JPEG for everything else
      const outputType = blob.type.includes("png") ? "image/png" : "image/jpeg";
      // q=0.85 matches the preview thumbnail quality; visually excellent at 1280px,
      // produces ~30% smaller files vs 0.92 with no perceptible quality difference.
      const quality = outputType === "image/jpeg" ? 0.85 : undefined;

      // If already within the 2K limit, just re-encode and return
      let targetWidth = width;
      let targetHeight = height;

      if (largest > maxDimension) {
        const scale = maxDimension / largest;
        targetWidth = Math.round(width * scale);
        targetHeight = Math.round(height * scale);
        console.debug(
          `[imageHelpers] Resizing image for upload: ${width}×${height} → ${targetWidth}×${targetHeight} (max ${maxDimension}px)`,
        );
      } else {
        console.debug(
          `[imageHelpers] Image within ${maxDimension}px limit (${width}×${height}), re-encoding at q=0.85`,
        );
      }

      const canvas = document.createElement("canvas");
      canvas.width = targetWidth;
      canvas.height = targetHeight;
      const ctx = canvas.getContext("2d");

      if (!ctx) {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Could not get canvas context"));
        return;
      }

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

      // White background for JPEG (no transparency support)
      if (outputType === "image/jpeg") {
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, targetWidth, targetHeight);
      }

      ctx.drawImage(img, 0, 0, targetWidth, targetHeight);
      URL.revokeObjectURL(objectUrl);

      canvas.toBlob(
        (resizedBlob) => {
          if (!resizedBlob) {
            reject(new Error("Could not create resized blob"));
            return;
          }
          const resizedUrl = URL.createObjectURL(resizedBlob);
          resolve({ resizedBlob, resizedUrl });
        },
        outputType,
        quality,
      );
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load image for upload resize"));
    };

    img.src = objectUrl;
  });
}

/**
 * Resizes and crops an image blob to fit preview dimensions while maintaining center focus.
 *
 * For SVGs: attempts canvas rasterization for the thumbnail.  If the SVG has no intrinsic
 * dimensions (common for Figma/Inkscape exports), the canvas produces a 0×0 result and
 * toBlob() returns null — in that case we fall back to using the raw SVG blob URL for
 * both preview and original (the browser renders SVG natively in an <img> tag, so it
 * will still display correctly in the embed card).
 *
 * @param blob Original image blob
 * @returns Promise with resized image blob, data URL, and original blob URL for full view
 */
export async function resizeImage(blob: Blob): Promise<{
  previewBlob: Blob;
  previewUrl: string;
  originalUrl: string;
}> {
  // For SVG, try canvas rasterization but fall back gracefully.
  // We need to handle the case where the SVG has no intrinsic size — the
  // img.naturalWidth/naturalHeight will be 0, making the canvas 0×0.
  // We detect this case and use a fallback SVG-native blob URL instead.
  if (blob.type === "image/svg+xml") {
    return _resizeSvgImage(blob);
  }

  const img = new Image();
  const objectUrl = URL.createObjectURL(blob);

  return new Promise((resolve, reject) => {
    img.onload = () => {
      // Target dimensions for the preview container
      const TARGET_WIDTH = 300;
      const TARGET_HEIGHT = 200;
      const TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT;
      const PREVIEW_WIDTH = TARGET_WIDTH * 2; // 600px for high DPI
      const PREVIEW_HEIGHT = TARGET_HEIGHT * 2; // 400px for high DPI

      // Calculate dimensions for center crop
      let cropWidth = img.width;
      let cropHeight = img.height;
      let offsetX = 0;
      let offsetY = 0;
      let finalWidth = img.width;
      let finalHeight = img.height;

      const imageRatio = img.width / img.height;

      // First determine crop dimensions
      if (imageRatio > TARGET_RATIO) {
        // Image is wider than target ratio - crop width
        cropWidth = img.height * TARGET_RATIO;
        offsetX = (img.width - cropWidth) / 2;
        cropHeight = img.height;
      } else {
        // Image is taller than target ratio - crop height
        cropWidth = img.width;
        cropHeight = img.width / TARGET_RATIO;
        offsetY = (img.height - cropHeight) / 2;
      }

      // Then determine if we need to scale down
      if (cropWidth > PREVIEW_WIDTH || cropHeight > PREVIEW_HEIGHT) {
        // Scale down to preview size
        finalWidth = PREVIEW_WIDTH;
        finalHeight = PREVIEW_HEIGHT;
      } else {
        // Keep original dimensions after crop
        finalWidth = cropWidth;
        finalHeight = cropHeight;
      }

      // Create canvas for cropped and optionally resized image
      const canvas = document.createElement("canvas");
      canvas.width = finalWidth;
      canvas.height = finalHeight;
      const ctx = canvas.getContext("2d");

      if (!ctx) {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Could not get canvas context"));
        return;
      }

      // Use better quality settings
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

      // For PNG with transparency, don't fill background
      if (!blob.type.includes("png")) {
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, finalWidth, finalHeight);
      }

      // Draw cropped and optionally resized image
      ctx.drawImage(
        img,
        offsetX,
        offsetY,
        cropWidth,
        cropHeight, // Source crop
        0,
        0,
        finalWidth,
        finalHeight, // Destination size
      );

      // Determine output format based on input
      const outputType = blob.type.includes("png") ? "image/png" : "image/jpeg";
      const quality = outputType === "image/png" ? undefined : 0.85;

      // Convert to blob
      canvas.toBlob(
        (previewBlob) => {
          if (!previewBlob) {
            URL.revokeObjectURL(objectUrl);
            reject(new Error("Could not create preview blob"));
            return;
          }

          // Create a new object URL for the preview
          const previewUrl = URL.createObjectURL(previewBlob);

          resolve({
            previewBlob,
            previewUrl,
            originalUrl: objectUrl, // Use the original object URL
          });
        },
        outputType,
        quality,
      );
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load image"));
    };

    img.src = objectUrl;
  });
}

/**
 * Generate a preview thumbnail for an SVG file.
 *
 * Strategy:
 *  1. Load SVG into an <img> element to get natural dimensions.
 *  2. If the SVG has intrinsic dimensions (naturalWidth > 0), draw it on a canvas
 *     and produce a JPEG thumbnail (compact, suitable for chat embed card).
 *  3. If dimensions are 0 (dimension-less SVG — common from Figma), fall back to
 *     using the raw SVG blob URL directly.  The browser renders SVG natively in
 *     <img> tags so it will still display correctly; we just don't crop/resize it.
 *
 * The original URL always points to the raw SVG blob so the fullscreen view shows
 * the crisp vector version.
 */
async function _resizeSvgImage(blob: Blob): Promise<{
  previewBlob: Blob;
  previewUrl: string;
  originalUrl: string;
}> {
  const SVG_FALLBACK_SIZE = 1024; // Used when SVG has no intrinsic dimensions
  const TARGET_WIDTH = 300;
  const TARGET_HEIGHT = 200;
  const PREVIEW_WIDTH = TARGET_WIDTH * 2; // 600px for high DPI
  const PREVIEW_HEIGHT = TARGET_HEIGHT * 2; // 400px for high DPI
  const TARGET_RATIO = TARGET_WIDTH / TARGET_HEIGHT;

  const objectUrl = URL.createObjectURL(blob);

  return new Promise((resolve, reject) => {
    const img = new Image();

    img.onload = () => {
      // Determine effective dimensions — SVGs without width/height attrs have 0
      const effectiveWidth =
        img.naturalWidth > 0 ? img.naturalWidth : SVG_FALLBACK_SIZE;
      const effectiveHeight =
        img.naturalHeight > 0 ? img.naturalHeight : SVG_FALLBACK_SIZE;

      if (img.naturalWidth === 0 || img.naturalHeight === 0) {
        // Dimension-less SVG — use raw blob URL for both preview and original.
        // The browser renders SVG natively in <img>, so the embed card will
        // display it correctly even without a rasterized thumbnail.
        console.debug(
          "[imageHelpers] SVG has no intrinsic dimensions — using raw SVG blob URL for preview",
        );
        resolve({
          previewBlob: blob,
          previewUrl: objectUrl,
          originalUrl: objectUrl,
        });
        return;
      }

      // SVG has intrinsic dimensions — rasterize to a JPEG thumbnail
      const imageRatio = effectiveWidth / effectiveHeight;

      let cropWidth = effectiveWidth;
      let cropHeight = effectiveHeight;
      let offsetX = 0;
      let offsetY = 0;

      if (imageRatio > TARGET_RATIO) {
        cropWidth = effectiveHeight * TARGET_RATIO;
        offsetX = (effectiveWidth - cropWidth) / 2;
        cropHeight = effectiveHeight;
      } else {
        cropWidth = effectiveWidth;
        cropHeight = effectiveWidth / TARGET_RATIO;
        offsetY = (effectiveHeight - cropHeight) / 2;
      }

      const finalWidth = cropWidth > PREVIEW_WIDTH ? PREVIEW_WIDTH : cropWidth;
      const finalHeight =
        cropHeight > PREVIEW_HEIGHT ? PREVIEW_HEIGHT : cropHeight;

      const canvas = document.createElement("canvas");
      canvas.width = finalWidth;
      canvas.height = finalHeight;
      const ctx = canvas.getContext("2d");

      if (!ctx) {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("Could not get canvas context for SVG preview"));
        return;
      }

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      // White background for JPEG (SVG may have transparency)
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(0, 0, finalWidth, finalHeight);

      ctx.drawImage(
        img,
        offsetX,
        offsetY,
        cropWidth,
        cropHeight,
        0,
        0,
        finalWidth,
        finalHeight,
      );

      canvas.toBlob(
        (previewBlob) => {
          if (!previewBlob) {
            // Canvas toBlob failed — fall back to raw SVG blob URL
            console.warn(
              "[imageHelpers] SVG canvas toBlob failed — using raw SVG blob URL for preview",
            );
            resolve({
              previewBlob: blob,
              previewUrl: objectUrl,
              originalUrl: objectUrl,
            });
            return;
          }

          const previewUrl = URL.createObjectURL(previewBlob);
          resolve({
            previewBlob,
            previewUrl,
            originalUrl: objectUrl, // Always return the raw SVG for fullscreen
          });
        },
        "image/jpeg",
        0.85,
      );
    };

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error("Failed to load SVG for preview generation"));
    };

    img.src = objectUrl;
  });
}
