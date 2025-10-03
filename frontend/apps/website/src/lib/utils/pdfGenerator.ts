/**
 * PDF Generator Utility
 * 
 * Generates PDF files from markdown content using jsPDF.
 * Works client-side for offline support.
 */

import { jsPDF } from 'jspdf';

/**
 * Generate PDF from markdown content
 * @param content - Markdown content to convert
 * @param title - Document title
 * @returns Blob of the generated PDF
 */
export async function generatePDF(content: string, title: string): Promise<void> {
    // Create new PDF document
    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4'
    });

    // Set font and title
    doc.setFontSize(20);
    doc.text(title, 20, 20);

    // Split content into lines and add to PDF
    // Simple implementation - can be enhanced with proper markdown parsing
    const lines = content.split('\n');
    let yPosition = 35;
    
    doc.setFontSize(12);
    
    for (const line of lines) {
        // Check if we need a new page
        if (yPosition > 280) {
            doc.addPage();
            yPosition = 20;
        }
        
        // Handle headers (simple detection)
        if (line.startsWith('# ')) {
            doc.setFontSize(18);
            doc.text(line.replace('# ', ''), 20, yPosition);
            doc.setFontSize(12);
            yPosition += 10;
        } else if (line.startsWith('## ')) {
            doc.setFontSize(16);
            doc.text(line.replace('## ', ''), 20, yPosition);
            doc.setFontSize(12);
            yPosition += 8;
        } else if (line.startsWith('### ')) {
            doc.setFontSize(14);
            doc.text(line.replace('### ', ''), 20, yPosition);
            doc.setFontSize(12);
            yPosition += 7;
        } else if (line.trim()) {
            // Regular text - split long lines
            const splitLines = doc.splitTextToSize(line, 170);
            doc.text(splitLines, 20, yPosition);
            yPosition += splitLines.length * 7;
        } else {
            // Empty line
            yPosition += 5;
        }
    }

    // Download the PDF
    const filename = `${title.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
    doc.save(filename);
}

/**
 * Generate PDF from multiple documents (folder download)
 * @param files - Array of file objects with title and content
 * @param folderName - Name of the folder
 */
export async function generateFolderPDF(files: any[], folderName: string): Promise<void> {
    const doc = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4'
    });

    // Add title page
    doc.setFontSize(24);
    doc.text(folderName, 20, 20);
    doc.setFontSize(12);
    doc.text(`${files.length} documents`, 20, 30);

    // Add each document
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        
        doc.addPage();
        
        doc.setFontSize(20);
        doc.text(file.title, 20, 20);
        
        const lines = file.content.split('\n');
        let yPosition = 35;
        
        doc.setFontSize(12);
        
        for (const line of lines) {
            if (yPosition > 280) {
                doc.addPage();
                yPosition = 20;
            }
            
            if (line.startsWith('# ')) {
                doc.setFontSize(18);
                doc.text(line.replace('# ', ''), 20, yPosition);
                doc.setFontSize(12);
                yPosition += 10;
            } else if (line.startsWith('## ')) {
                doc.setFontSize(16);
                doc.text(line.replace('## ', ''), 20, yPosition);
                doc.setFontSize(12);
                yPosition += 8;
            } else if (line.startsWith('### ')) {
                doc.setFontSize(14);
                doc.text(line.replace('### ', ''), 20, yPosition);
                doc.setFontSize(12);
                yPosition += 7;
            } else if (line.trim()) {
                const splitLines = doc.splitTextToSize(line, 170);
                doc.text(splitLines, 20, yPosition);
                yPosition += splitLines.length * 7;
            } else {
                yPosition += 5;
            }
        }
    }

    const filename = `${folderName.replace(/[^a-z0-9]/gi, '_').toLowerCase()}.pdf`;
    doc.save(filename);
}

