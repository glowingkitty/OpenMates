/**
 * Resizes an image blob so its largest dimension does not exceed maxDimension pixels,
 * preserving the original aspect ratio. If the image is already within the limit it is
 * returned as-is (re-encoded at quality 0.92 for JPEG to normalise file size).
 *
 * This is used to cap camera captures and file-picker images before they are uploaded
 * to the server, improving upload speed and reducing storage usage while keeping
 * enough resolution for AI analysis.
 *
 * @param blob         Original image blob (JPEG, PNG, WebP, HEIC, etc.)
 * @param maxDimension Maximum allowed width OR height in pixels (default 2048 = 2K)
 * @returns Promise resolving to the resized blob and an object URL for immediate display
 */
export async function resizeForUpload(
  blob: Blob,
  maxDimension: number = 2048,
): Promise<{ resizedBlob: Blob; resizedUrl: string }> {
  const img = new Image();
  const objectUrl = URL.createObjectURL(blob);

  return new Promise((resolve, reject) => {
    img.onload = () => {
      const { width, height } = img;
      const largest = Math.max(width, height);

      // Determine output MIME type — keep PNG for transparency, JPEG for everything else
      const outputType = blob.type.includes("png") ? "image/png" : "image/jpeg";
      const quality = outputType === "image/jpeg" ? 0.92 : undefined;

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
          `[imageHelpers] Image already within ${maxDimension}px limit (${width}×${height}), re-encoding only`,
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
 * Resizes and crops an image blob to fit preview dimensions while maintaining center focus
 * @param blob Original image blob
 * @returns Promise with resized image blob, data URL, and original blob URL for full view
 */
export async function resizeImage(blob: Blob): Promise<{
  previewBlob: Blob;
  previewUrl: string;
  originalUrl: string;
}> {
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
