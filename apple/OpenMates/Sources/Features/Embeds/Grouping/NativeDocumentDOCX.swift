// Legacy HTML DOCX export follows web html-docx-js's OpenXML altChunk package.
// HTML is sanitized locally; no document bytes are uploaded or fetched.
import Foundation
import ZIPFoundation

enum NativeDocumentDOCX {
    static func build(html: String) throws -> Data {
        let safe = DocumentCanvasSource.sanitizeHTML(html)
        guard !safe.isEmpty else { throw URLError(.zeroByteResource) }
        let xmlHeader = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        let files: [String: String] = [
            "[Content_Types].xml": xmlHeader + "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/><Override PartName=\"/word/afchunk.mht\" ContentType=\"message/rfc822\"/></Types>",
            "_rels/.rels": xmlHeader + "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/></Relationships>",
            "word/document.xml": xmlHeader + "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><w:body><w:altChunk r:id=\"htmlChunk\"/><w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/><w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/></w:sectPr></w:body></w:document>",
            "word/_rels/document.xml.rels": xmlHeader + "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"htmlChunk\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk\" Target=\"afchunk.mht\"/></Relationships>",
            "word/afchunk.mht": "MIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=\"openmates-docx\"\r\n\r\n--openmates-docx\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\nContent-Location: file:///document.html\r\n\r\n" + Data(("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>" + safe + "</body></html>").utf8).base64EncodedString(options: [.lineLength76Characters, .endLineWithCarriageReturn, .endLineWithLineFeed]) + "\r\n--openmates-docx--\r\n"
        ]
        let archive = try Archive(data: Data(), accessMode: .create)
        for path in files.keys.sorted() {
            let bytes = Data(files[path]!.utf8)
            try archive.addEntry(with: path, type: .file, uncompressedSize: Int64(bytes.count), compressionMethod: .deflate) { offset, count in
                bytes.subdata(in: Int(offset)..<min(bytes.count, Int(offset) + count))
            }
        }
        guard let bytes = archive.data, !bytes.isEmpty else { throw URLError(.cannotCreateFile) }
        return bytes
    }
}
