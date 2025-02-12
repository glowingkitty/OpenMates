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

            // Calculate dimensions for center crop
            let cropWidth = img.width;
            let cropHeight = img.height;
            let offsetX = 0;
            let offsetY = 0;

            const imageRatio = img.width / img.height;

            if (imageRatio > TARGET_RATIO) {
                // Image is wider than target ratio - crop width
                cropWidth = img.height * TARGET_RATIO;
                offsetX = (img.width - cropWidth) / 2;
            } else {
                // Image is taller than target ratio - crop height
                cropHeight = img.width / TARGET_RATIO;
                offsetY = (img.height - cropHeight) / 2;
            }

            // Create canvas for cropped and resized image
            const canvas = document.createElement('canvas');
            canvas.width = TARGET_WIDTH * 2; // Double size for high DPI
            canvas.height = TARGET_HEIGHT * 2;
            const ctx = canvas.getContext('2d');
            
            if (!ctx) {
                URL.revokeObjectURL(objectUrl);
                reject(new Error('Could not get canvas context'));
                return;
            }

            // Use better quality settings
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            
            // Draw cropped and resized image
            ctx.drawImage(
                img,
                offsetX, offsetY, cropWidth, cropHeight, // Source crop
                0, 0, TARGET_WIDTH * 2, TARGET_HEIGHT * 2 // Destination size
            );

            // Convert to blob
            canvas.toBlob(
                (previewBlob) => {
                    if (!previewBlob) {
                        URL.revokeObjectURL(objectUrl);
                        reject(new Error('Could not create preview blob'));
                        return;
                    }
                    resolve({
                        previewBlob,
                        previewUrl: canvas.toDataURL('image/jpeg', 0.85),
                        originalUrl: objectUrl // Keep original URL for full view
                    });
                },
                'image/jpeg',
                0.85
            );
        };

        img.onerror = () => {
            URL.revokeObjectURL(objectUrl);
            reject(new Error('Failed to load image'));
        };

        img.src = objectUrl;
    });
} 