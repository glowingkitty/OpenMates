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
            const canvas = document.createElement('canvas');
            canvas.width = finalWidth;
            canvas.height = finalHeight;
            const ctx = canvas.getContext('2d');
            
            if (!ctx) {
                URL.revokeObjectURL(objectUrl);
                reject(new Error('Could not get canvas context'));
                return;
            }

            // Use better quality settings
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            
            // For PNG with transparency, don't fill background
            if (!blob.type.includes('png')) {
                ctx.fillStyle = '#FFFFFF';
                ctx.fillRect(0, 0, finalWidth, finalHeight);
            }
            
            // Draw cropped and optionally resized image
            ctx.drawImage(
                img,
                offsetX, offsetY, cropWidth, cropHeight, // Source crop
                0, 0, finalWidth, finalHeight // Destination size
            );

            // Determine output format based on input
            const outputType = blob.type.includes('png') ? 'image/png' : 'image/jpeg';
            const quality = outputType === 'image/png' ? undefined : 0.85;

            // Convert to blob
            canvas.toBlob(
                (previewBlob) => {
                    if (!previewBlob) {
                        URL.revokeObjectURL(objectUrl);
                        reject(new Error('Could not create preview blob'));
                        return;
                    }

                    // Create a new object URL for the preview
                    const previewUrl = URL.createObjectURL(previewBlob);

                    resolve({
                        previewBlob,
                        previewUrl,
                        originalUrl: objectUrl // Use the original object URL
                    });
                },
                outputType,
                quality
            );
        };

        img.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            reject(new Error('Failed to load image'));
        };

        img.src = objectUrl;
    });
} 