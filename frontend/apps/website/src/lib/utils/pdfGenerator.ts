/**
 * PDF Generator Utility
 * 
 * Generates PDF files from markdown content using jsPDF.
 * Works client-side for offline support.
 * Direct markdown-to-PDF conversion for better formatting and image handling.
 */

import { jsPDF } from 'jspdf';

/**
 * Parse markdown content and extract elements with proper formatting
 * @param markdownContent - Markdown content to parse
 * @returns Array of text elements with formatting info
 */
function parseMarkdownContent(markdownContent: string): Array<{text: string, type: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6' | 'p' | 'li' | 'text' | 'pre' | 'code' | 'img' | 'link', level?: number, src?: string, alt?: string, url?: string}> {
    const elements: Array<{text: string, type: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6' | 'p' | 'li' | 'text' | 'pre' | 'code' | 'img' | 'link', level?: number, src?: string, alt?: string, url?: string}> = [];
    
    // Split content into lines
    const lines = markdownContent.split('\n');
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmedLine = line.trim();
        
        // Skip empty lines
        if (!trimmedLine) {
            continue;
        }
        
        // Handle headings
        if (trimmedLine.startsWith('#')) {
            const level = trimmedLine.match(/^#+/)?.[0].length || 1;
            const text = trimmedLine.replace(/^#+\s*/, '').trim();
            if (text) {
                elements.push({
                    text,
                    type: `h${Math.min(level, 6)}` as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6',
                    level
                });
            }
        }
        // Handle images: ![alt](src) or [![alt](src)](link)
        else if (trimmedLine.includes('![') && trimmedLine.includes('](')) {
            const imageMatch = trimmedLine.match(/!\[([^\]]*)\]\(([^)]+)\)/);
            if (imageMatch) {
                const alt = imageMatch[1];
                const src = imageMatch[2];
                elements.push({
                    text: alt || '[Image]',
                    type: 'img',
                    src: src,
                    alt: alt
                });
            }
        }
        // Handle links: [text](url) - but only if they wrap images [![...](...)](link)
        else if (trimmedLine.match(/\[!\[.*\]\(.*\)\]\(.*\)/)) {
            // This is an image wrapped in a link - extract the link URL
            const wrapperMatch = trimmedLine.match(/\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)/);
            if (wrapperMatch) {
                const alt = wrapperMatch[1];
                const src = wrapperMatch[2];
                const url = wrapperMatch[3];
                elements.push({
                    text: alt || '[Image]',
                    type: 'img',
                    src: src,
                    alt: alt,
                    url: url
                });
            }
        }
        // Handle regular links: [text](url)
        else if (trimmedLine.includes('[') && trimmedLine.includes('](') && !trimmedLine.includes('![')) {
            // Extract link text and URL
            const linkMatch = trimmedLine.match(/\[([^\]]+)\]\(([^)]+)\)/);
            if (linkMatch) {
                const text = linkMatch[1];
                const url = linkMatch[2];
                elements.push({
                    text: text,
                    type: 'link',
                    url: url
                });
            } else {
                // If no match, just add as paragraph
                elements.push({
                    text: trimmedLine,
                    type: 'p'
                });
            }
        }
        // Handle code blocks
        else if (trimmedLine.startsWith('```')) {
            // Find the end of the code block
            let codeContent = '';
            let j = i + 1;
            while (j < lines.length && !lines[j].startsWith('```')) {
                codeContent += lines[j] + '\n';
                j++;
            }
            if (codeContent.trim()) {
                elements.push({
                    text: codeContent.trim(),
                    type: 'pre'
                });
            }
            i = j; // Skip to end of code block
        }
        // Handle list items
        else if (trimmedLine.startsWith('- ') || trimmedLine.startsWith('* ') || /^\d+\.\s/.test(trimmedLine)) {
            const text = trimmedLine.replace(/^[-*]\s+/, '').replace(/^\d+\.\s+/, '').trim();
            if (text) {
                elements.push({
                    text,
                    type: 'li'
                });
            }
        }
        // Handle blockquotes
        else if (trimmedLine.startsWith('>')) {
            const text = trimmedLine.replace(/^>\s*/, '').trim();
            if (text) {
                elements.push({
                    text,
                    type: 'p'
                });
            }
        }
        // Handle regular paragraphs
        else {
            elements.push({
                text: trimmedLine,
                type: 'p'
            });
        }
    }
    
    console.log('🔍 Markdown parsing found:', elements.length, 'elements');
    console.log('🔍 Image elements:', elements.filter(e => e.type === 'img'));
    
    return elements;
}

/**
 * Generate PDF from markdown content
 * @param markdownContent - Markdown content to convert
 * @param title - Document title
 * @returns Promise that resolves when PDF is generated
 */
export async function generatePDFFromMarkdown(markdownContent: string, title: string): Promise<void> {
    // Create new PDF document
    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4'
    });

    // Parse markdown content
    const elements = parseMarkdownContent(markdownContent);
    
    // Set up initial positioning
    let yPosition = 20;
    const pageHeight = 280; // A4 page height minus margins
    const leftMargin = 20;
    const maxWidth = 170; // A4 width minus margins
    
    // Process each element
    for (const element of elements) {
        // Skip empty elements
        if (!element.text || element.text.trim() === '') {
            continue;
        }
        
        // Check if we need a new page
        if (yPosition > pageHeight) {
            doc.addPage();
            yPosition = 20;
        }
        
        // Set font based on element type
        switch (element.type) {
            case 'h1':
                doc.setFontSize(20);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(72, 103, 205); // Primary color for main headings
                break;
            case 'h2':
            doc.setFontSize(18);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(0, 0, 0);
                break;
            case 'h3':
            doc.setFontSize(16);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(0, 0, 0);
                break;
            case 'h4':
            doc.setFontSize(14);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(0, 0, 0);
                break;
            case 'h5':
            case 'h6':
            doc.setFontSize(12);
                doc.setFont('helvetica', 'bold');
                doc.setTextColor(0, 0, 0);
                break;
            case 'li':
                doc.setFontSize(11);
                doc.setFont('helvetica', 'normal');
                doc.setTextColor(0, 0, 0);
                // Add bullet point
                element.text = '• ' + element.text;
                break;
            case 'pre':
            case 'code':
                doc.setFontSize(10);
                doc.setFont('courier', 'normal');
                doc.setTextColor(0, 0, 0);
                break;
            case 'img':
                doc.setFontSize(10);
                doc.setFont('helvetica', 'italic');
                doc.setTextColor(100, 100, 100);
                break;
            case 'link':
                doc.setFontSize(11);
                doc.setFont('helvetica', 'normal');
                doc.setTextColor(72, 103, 205); // Link color
                break;
            case 'p':
            case 'text':
            default:
                doc.setFontSize(11);
                doc.setFont('helvetica', 'normal');
                doc.setTextColor(0, 0, 0);
                break;
        }
        
        // For code blocks, preserve formatting and use smaller font
        if (element.type === 'pre' || element.type === 'code') {
            // Split by lines to preserve ASCII art formatting
            const lines = element.text.split('\n');
            for (const line of lines) {
                if (yPosition > pageHeight) {
                    doc.addPage();
                    yPosition = 20;
                }
                
                // Use smaller font for code blocks
                doc.setFontSize(9);
                doc.setFont('courier', 'normal');
                
                // Split long lines but preserve formatting
                const splitLines = doc.splitTextToSize(line, maxWidth);
                doc.text(splitLines, leftMargin, yPosition);
                yPosition += splitLines.length * 5; // Smaller line height for code
            }
        } else if (element.type === 'img') {
            // Handle images - embed actual images
            console.log('🔍 Processing image element:', element);
            
            if (yPosition > pageHeight) {
                doc.addPage();
                yPosition = 20;
            }
            
            if (element.src) {
                try {
                    // Convert relative path to absolute URL
                    let imageUrl = element.src;
                    if (imageUrl.startsWith('../../')) {
                        // Convert ../../images/... to /docs/images/...
                        imageUrl = imageUrl.replace(/^\.\.\/\.\.\//, '/docs/');
                    } else if (imageUrl.startsWith('../')) {
                        imageUrl = imageUrl.replace(/^\.\.\//, '/docs/');
                    } else if (!imageUrl.startsWith('http') && !imageUrl.startsWith('/')) {
                        imageUrl = '/docs/' + imageUrl;
                    }
                    
                    console.log('🔍 Loading image from:', imageUrl);
                    
                    // Load image
                    const img = new Image();
                    img.crossOrigin = 'anonymous';
                    
                    // Wait for image to load
                    await new Promise<void>((resolve, reject) => {
                        img.onload = () => {
                            try {
                                // Calculate dimensions to fit within page
                                const maxImageWidth = maxWidth;
                                const maxImageHeight = 100; // Max height in mm
                                
                                let imgWidth = img.width;
                                let imgHeight = img.height;
                                
                                // Scale to fit
                                const widthRatio = maxImageWidth / (imgWidth * 0.264583); // Convert px to mm
                                const heightRatio = maxImageHeight / (imgHeight * 0.264583);
                                const ratio = Math.min(widthRatio, heightRatio, 1);
                                
                                imgWidth = (imgWidth * 0.264583) * ratio;
                                imgHeight = (imgHeight * 0.264583) * ratio;
                                
                                // Check if we need a new page
                                if (yPosition + imgHeight > pageHeight) {
                                    doc.addPage();
                                    yPosition = 20;
                                }
                                
                                // Add image to PDF
                                doc.addImage(img, 'JPEG', leftMargin, yPosition, imgWidth, imgHeight);
                                
                                // Make image clickable if it has a URL
                                if (element.url) {
                                    doc.link(leftMargin, yPosition, imgWidth, imgHeight, { url: element.url });
                                }
                                
                                yPosition += imgHeight + 5; // Add spacing after image
                                
                                // Add caption if there's alt text
                                if (element.text) {
                                    doc.setFontSize(9);
                                    doc.setFont('helvetica', 'italic');
                                    doc.setTextColor(100, 100, 100);
                                    const caption = doc.splitTextToSize(element.text, maxWidth);
                                    doc.text(caption, leftMargin, yPosition);
                                    yPosition += caption.length * 4 + 3;
                                }
                                
                                console.log('✅ Image embedded successfully');
                                resolve();
                            } catch (err) {
                                console.error('❌ Failed to embed image:', err);
                                reject(err);
                            }
                        };
                        
                        img.onerror = () => {
                            console.error('❌ Failed to load image:', imageUrl);
                            // Fallback to text
                            doc.setFontSize(10);
                            doc.setFont('helvetica', 'italic');
                            doc.setTextColor(100, 100, 100);
                            const fallbackText = `[Image not available: ${element.text}]`;
                            const splitLines = doc.splitTextToSize(fallbackText, maxWidth);
                            doc.text(splitLines, leftMargin, yPosition);
                            yPosition += splitLines.length * 6;
                            resolve();
                        };
                        
                        img.src = imageUrl;
                    });
                } catch (err) {
                    console.error('❌ Error processing image:', err);
                    // Fallback to text
                    doc.setFontSize(10);
                    doc.setFont('helvetica', 'italic');
                    doc.setTextColor(100, 100, 100);
                    const fallbackText = `[Image error: ${element.text}]`;
                    const splitLines = doc.splitTextToSize(fallbackText, maxWidth);
                    doc.text(splitLines, leftMargin, yPosition);
                    yPosition += splitLines.length * 6;
                }
            }
        } else if (element.type === 'link') {
            // Handle links - make them clickable
            if (yPosition > pageHeight) {
                doc.addPage();
                yPosition = 20;
            }
            
            const splitLines = doc.splitTextToSize(element.text, maxWidth);
            
            // Add clickable link
            if (element.url) {
                // Calculate text dimensions for link area
                const textWidth = doc.getTextWidth(splitLines[0]);
                const textHeight = 5; // Approximate height for one line
                
                // Add link annotation
                doc.textWithLink(element.text, leftMargin, yPosition, { url: element.url });
                yPosition += splitLines.length * 6;
            } else {
                // No URL, just render as text
                doc.text(splitLines, leftMargin, yPosition);
                yPosition += splitLines.length * 6;
            }
        } else {
            // Regular text processing
            const splitLines = doc.splitTextToSize(element.text, maxWidth);
            
            // Add text to PDF
            doc.text(splitLines, leftMargin, yPosition);
            
            // Calculate new Y position based on number of lines
            const lineHeight = element.type.startsWith('h') ? 8 : 6;
            yPosition += splitLines.length * lineHeight;
        }
        
        // Add appropriate spacing based on element type
        if (element.type.startsWith('h')) {
            // Add spacing after headings
            if (element.type === 'h1') {
                yPosition += 8; // More space after main headings
            } else if (element.type === 'h2') {
                yPosition += 6; // Medium space after h2
            } else {
                yPosition += 4; // Standard space after other headings
            }
        } else if (element.type === 'p') {
            // Add spacing after paragraphs
            yPosition += 3;
        } else if (element.type === 'pre' || element.type === 'code') {
            // Add spacing after code blocks
            yPosition += 4;
        } else if (element.type === 'li') {
            // Add spacing after list items
            yPosition += 2;
        } else {
            // Add minimal spacing for other elements
            yPosition += 1;
        }
    }

    // Download the PDF
    const filename = `${title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
    doc.save(filename);
}

/**
 * Generate PDF from multiple markdown files in a folder
 * @param files - Array of file objects with originalMarkdown and title
 * @param folderName - Name of the folder
 * @returns Promise that resolves when PDF is generated
 */
export async function generateFolderPDF(files: any[], folderName: string): Promise<void> {
    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4'
    });

    // Set up initial positioning for folder PDF
    let yPosition = 20;

    // Add each document
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        
        if (i > 0) {
        doc.addPage();
        }
        
        // Parse markdown content for each file - no fallbacks!
        if (!file.originalMarkdown) {
            throw new Error(`Markdown source not available for file: ${file.title} - this should never happen!`);
        }
        
        const elements = parseMarkdownContent(file.originalMarkdown);
        
        // Set up positioning
        let yPosition = 20;
        const pageHeight = 280;
        const leftMargin = 20;
        const maxWidth = 170;
        
        // Process each element (same logic as single document)
        for (const element of elements) {
            // Skip empty elements
            if (!element.text || element.text.trim() === '') {
                continue;
            }
            
            // Check if we need a new page
            if (yPosition > pageHeight) {
                doc.addPage();
                yPosition = 20;
            }
            
            // Set font based on element type
            switch (element.type) {
                case 'h1':
                    doc.setFontSize(20);
                    doc.setFont('helvetica', 'bold');
                    doc.setTextColor(72, 103, 205); // Primary color for main headings
                    break;
                case 'h2':
                doc.setFontSize(18);
                    doc.setFont('helvetica', 'bold');
                    doc.setTextColor(0, 0, 0);
                    break;
                case 'h3':
                doc.setFontSize(16);
                    doc.setFont('helvetica', 'bold');
                    doc.setTextColor(0, 0, 0);
                    break;
                case 'h4':
                doc.setFontSize(14);
                    doc.setFont('helvetica', 'bold');
                    doc.setTextColor(0, 0, 0);
                    break;
                case 'h5':
                case 'h6':
                doc.setFontSize(12);
                    doc.setFont('helvetica', 'bold');
                    doc.setTextColor(0, 0, 0);
                    break;
                case 'li':
                    doc.setFontSize(11);
                    doc.setFont('helvetica', 'normal');
                    doc.setTextColor(0, 0, 0);
                    // Add bullet point
                    element.text = '• ' + element.text;
                    break;
                case 'pre':
                case 'code':
                    doc.setFontSize(10);
                    doc.setFont('courier', 'normal');
                    doc.setTextColor(0, 0, 0);
                    break;
                case 'img':
                    doc.setFontSize(10);
                    doc.setFont('helvetica', 'italic');
                    doc.setTextColor(100, 100, 100);
                    break;
                case 'link':
                    doc.setFontSize(11);
                    doc.setFont('helvetica', 'normal');
                    doc.setTextColor(72, 103, 205); // Link color
                    break;
                case 'p':
                case 'text':
                default:
                    doc.setFontSize(11);
                    doc.setFont('helvetica', 'normal');
                    doc.setTextColor(0, 0, 0);
                    break;
            }
            
            // For code blocks, preserve formatting and use smaller font
            if (element.type === 'pre' || element.type === 'code') {
                // Split by lines to preserve ASCII art formatting
                const lines = element.text.split('\n');
                for (const line of lines) {
                    if (yPosition > pageHeight) {
                        doc.addPage();
                        yPosition = 20;
                    }
                    
                    // Use smaller font for code blocks
                    doc.setFontSize(9);
                    doc.setFont('courier', 'normal');
                    
                    // Split long lines but preserve formatting
                    const splitLines = doc.splitTextToSize(line, maxWidth);
                    doc.text(splitLines, leftMargin, yPosition);
                    yPosition += splitLines.length * 5; // Smaller line height for code
                }
            } else if (element.type === 'img') {
                // Handle images - embed actual images
                console.log('🔍 Processing image element in folder PDF:', element);
                
                if (yPosition > pageHeight) {
                    doc.addPage();
                    yPosition = 20;
                }
                
                if (element.src) {
                    try {
                        // Convert relative path to absolute URL
                        let imageUrl = element.src;
                        if (imageUrl.startsWith('../../')) {
                            imageUrl = imageUrl.replace(/^\.\.\/\.\.\//, '/docs/');
                        } else if (imageUrl.startsWith('../')) {
                            imageUrl = imageUrl.replace(/^\.\.\//, '/docs/');
                        } else if (!imageUrl.startsWith('http') && !imageUrl.startsWith('/')) {
                            imageUrl = '/docs/' + imageUrl;
                        }
                        
                        console.log('🔍 Loading image from:', imageUrl);
                        
                        // Load image
                        const img = new Image();
                        img.crossOrigin = 'anonymous';
                        
                        // Wait for image to load
                        await new Promise<void>((resolve, reject) => {
                            img.onload = () => {
                                try {
                                    // Calculate dimensions to fit within page
                                    const maxImageWidth = maxWidth;
                                    const maxImageHeight = 100;
                                    
                                    let imgWidth = img.width;
                                    let imgHeight = img.height;
                                    
                                    // Scale to fit
                                    const widthRatio = maxImageWidth / (imgWidth * 0.264583);
                                    const heightRatio = maxImageHeight / (imgHeight * 0.264583);
                                    const ratio = Math.min(widthRatio, heightRatio, 1);
                                    
                                    imgWidth = (imgWidth * 0.264583) * ratio;
                                    imgHeight = (imgHeight * 0.264583) * ratio;
                                    
                                    // Check if we need a new page
                                    if (yPosition + imgHeight > pageHeight) {
                                        doc.addPage();
                                        yPosition = 20;
                                    }
                                    
                                    // Add image to PDF
                                    doc.addImage(img, 'JPEG', leftMargin, yPosition, imgWidth, imgHeight);
                                    
                                    // Make image clickable if it has a URL
                                    if (element.url) {
                                        doc.link(leftMargin, yPosition, imgWidth, imgHeight, { url: element.url });
                                    }
                                    
                                    yPosition += imgHeight + 5;
                                    
                                    // Add caption
                                    if (element.text) {
                                        doc.setFontSize(9);
                                        doc.setFont('helvetica', 'italic');
                                        doc.setTextColor(100, 100, 100);
                                        const caption = doc.splitTextToSize(element.text, maxWidth);
                                        doc.text(caption, leftMargin, yPosition);
                                        yPosition += caption.length * 4 + 3;
                                    }
                                    
                                    console.log('✅ Image embedded successfully in folder PDF');
                                    resolve();
                                } catch (err) {
                                    console.error('❌ Failed to embed image:', err);
                                    reject(err);
                                }
                            };
                            
                            img.onerror = () => {
                                console.error('❌ Failed to load image:', imageUrl);
                                // Fallback to text
                                doc.setFontSize(10);
                                doc.setFont('helvetica', 'italic');
                                doc.setTextColor(100, 100, 100);
                                const fallbackText = `[Image not available: ${element.text}]`;
                                const splitLines = doc.splitTextToSize(fallbackText, maxWidth);
                                doc.text(splitLines, leftMargin, yPosition);
                                yPosition += splitLines.length * 6;
                                resolve();
                            };
                            
                            img.src = imageUrl;
                        });
                    } catch (err) {
                        console.error('❌ Error processing image:', err);
                        // Fallback to text
                        doc.setFontSize(10);
                        doc.setFont('helvetica', 'italic');
                        doc.setTextColor(100, 100, 100);
                        const fallbackText = `[Image error: ${element.text}]`;
                        const splitLines = doc.splitTextToSize(fallbackText, maxWidth);
                        doc.text(splitLines, leftMargin, yPosition);
                        yPosition += splitLines.length * 6;
                    }
                }
            } else if (element.type === 'link') {
                // Handle links - make them clickable
                if (yPosition > pageHeight) {
                    doc.addPage();
                    yPosition = 20;
                }
                
                const splitLines = doc.splitTextToSize(element.text, maxWidth);
                
                // Add clickable link
                if (element.url) {
                    // Add link annotation
                    doc.textWithLink(element.text, leftMargin, yPosition, { url: element.url });
                    yPosition += splitLines.length * 6;
                } else {
                    // No URL, just render as text
                    doc.text(splitLines, leftMargin, yPosition);
                    yPosition += splitLines.length * 6;
                }
            } else {
                // Regular text processing
                const splitLines = doc.splitTextToSize(element.text, maxWidth);
                
                // Add text to PDF
                doc.text(splitLines, leftMargin, yPosition);
                
                // Calculate new Y position based on number of lines
                const lineHeight = element.type.startsWith('h') ? 8 : 6;
                yPosition += splitLines.length * lineHeight;
            }
            
            // Add appropriate spacing based on element type
            if (element.type.startsWith('h')) {
                // Add spacing after headings
                if (element.type === 'h1') {
                    yPosition += 8; // More space after main headings
                } else if (element.type === 'h2') {
                    yPosition += 6; // Medium space after h2
                } else {
                    yPosition += 4; // Standard space after other headings
                }
            } else if (element.type === 'p') {
                // Add spacing after paragraphs
                yPosition += 3;
            } else if (element.type === 'pre' || element.type === 'code') {
                // Add spacing after code blocks
                yPosition += 4;
            } else if (element.type === 'li') {
                // Add spacing after list items
                yPosition += 2;
            } else {
                // Add minimal spacing for other elements
                yPosition += 1;
            }
        }
    }

    // Download the PDF
    const filename = `${folderName.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
    doc.save(filename);
}