/**
 * Resizes an image blob to specified dimensions while maintaining aspect ratio
 * @param blob Original image blob
 * @param maxWidth Maximum width of resized image
 * @param maxHeight Maximum height of resized image
 * @returns Promise with resized image blob and data URL
 */
export async function resizeImage(blob: Blob): Promise<{ previewBlob: Blob; previewUrl: string }> {
    // Create an image element to load the blob
    const img = new Image();
    const objectUrl = URL.createObjectURL(blob);

    return new Promise((resolve, reject) => {
        img.onload = () => {
            // Clean up object URL
            URL.revokeObjectURL(objectUrl);

            // Calculate new dimensions maintaining aspect ratio
            const MAX_WIDTH = 600;
            const MAX_HEIGHT = 400;
            let width = img.width;
            let height = img.height;
            
            if (width > MAX_WIDTH) {
                height = Math.round((height * MAX_WIDTH) / width);
                width = MAX_WIDTH;
            }
            if (height > MAX_HEIGHT) {
                width = Math.round((width * MAX_HEIGHT) / height);
                height = MAX_HEIGHT;
            }

            // Create canvas and resize image
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d');
            
            if (!ctx) {
                reject(new Error('Could not get canvas context'));
                return;
            }

            // Use better quality settings
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';
            
            // Draw image with white background (for transparent PNGs)
            ctx.fillStyle = '#FFFFFF';
            ctx.fillRect(0, 0, width, height);
            ctx.drawImage(img, 0, 0, width, height);

            // Convert to blob
            canvas.toBlob(
                (previewBlob) => {
                    if (!previewBlob) {
                        reject(new Error('Could not create preview blob'));
                        return;
                    }
                    resolve({
                        previewBlob,
                        previewUrl: canvas.toDataURL('image/jpeg', 0.85)
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