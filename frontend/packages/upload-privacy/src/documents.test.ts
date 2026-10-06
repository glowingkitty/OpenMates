import assert from 'node:assert/strict';
import { test } from 'node:test';
import JSZip from 'jszip';
import { PDFDict, PDFDocument, PDFName, PDFString } from 'pdf-lib';
import { stripDocumentMetadata } from './documents.js';

const utf8 = (bytes: Uint8Array) => Buffer.from(bytes).toString('utf8');
const concat = (...parts: Uint8Array[]): Uint8Array => Buffer.concat(parts);
const text = (value: string): Uint8Array => new TextEncoder().encode(value);
const pngChunk = (name: string, data: Uint8Array): Uint8Array => concat(
  Uint8Array.of(data.length >>> 24, data.length >>> 16 & 255, data.length >>> 8 & 255, data.length & 255),
  text(name), data, Uint8Array.of(0, 0, 0, 0),
);

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('PDF removes Info, nested XMP, annotation metadata and stale objects while preserving pages', async () => {
  const pdf = await PDFDocument.create();
  const page = pdf.addPage([320, 240]);
  page.drawText('Visible paragraph stays', { x: 20, y: 150 });
  pdf.setAuthor('InfoSecretAuthor');
  pdf.setCreationDate(new Date('2001-02-03T00:00:00Z'));
  const context = pdf.context;
  context.lookup(context.trailerInfo.Info, PDFDict).set(PDFName.of('PrivateField'), PDFString.of('CustomInfoSecretAuthor'));
  context.lookup(context.trailerInfo.Info, PDFDict).set(PDFName.of('SourcePath'), PDFString.of('/workspace/private/report.pdf'));
  const xmp = context.stream(Buffer.from('<x:xmpmeta>NestedSecretAuthor</x:xmpmeta>'), {
    Type: 'Metadata', Subtype: 'XML',
  });
  const xmpRef = context.register(xmp);
  const nested = context.obj({ Metadata: xmpRef });
  page.node.set(PDFName.of('PieceInfo'), nested);
  pdf.catalog.set(PDFName.of('Metadata'), xmpRef);
  context.register(context.obj({ Creator: 'UnreachableSecretAuthor' }));
  const annotation = context.obj({ Type: 'Annot', Subtype: 'Text', T: 'AnnotationSecretAuthor', Contents: 'Useful note', NM: 'SecretAnnotationId' });
  page.node.set(PDFName.of('Annots'), context.obj([context.register(annotation)]));
  const original = await pdf.save({ useObjectStreams: false });
  const oldXref = /startxref\s+(\d+)\s+%%EOF\s*$/.exec(utf8(original))?.[1];
  assert.ok(oldXref);
  const newObjectNumber = context.largestObjectNumber + 1;
  const prelude = Buffer.from('\n% EarlierRevisionSecretAuthor\n');
  const objectOffset = original.length + prelude.length;
  const extraInfo = Buffer.from(`${newObjectNumber} 0 obj\n<< /Author (IncrementalSecretAuthor) /SourcePath (/workspace/private/report.pdf) >>\nendobj\n`);
  const xrefOffset = objectOffset + extraInfo.length;
  const incrementalTrailer = Buffer.from(
    `xref\n${newObjectNumber} 1\n${String(objectOffset).padStart(10, '0')} 00000 n \n` +
    `trailer\n<< /Size ${newObjectNumber + 1} /Root ${context.trailerInfo.Root} /Info ${newObjectNumber} 0 R /Prev ${oldXref} >>\n` +
    `startxref\n${xrefOffset}\n%%EOF\n`,
  );
  const priorRevision = Buffer.concat([Buffer.from(original), prelude, extraInfo, incrementalTrailer]);
  assert.equal((await PDFDocument.load(priorRevision, { updateMetadata: false })).getAuthor(), 'IncrementalSecretAuthor');

  const result = await stripDocumentMetadata(priorRevision, 'application/pdf', 'notes.pdf');
  assert.ok(result);
  const output = utf8(result);
  for (const secret of ['InfoSecretAuthor', 'CustomInfoSecretAuthor', 'IncrementalSecretAuthor', 'NestedSecretAuthor', 'UnreachableSecretAuthor',
    'AnnotationSecretAuthor', 'SecretAnnotationId', 'EarlierRevisionSecretAuthor']) {
    assert.ok(!output.includes(secret), `${secret} survived PDF rewrite`);
  }
  const reopened = await PDFDocument.load(result, { updateMetadata: false });
  assert.equal(reopened.getPageCount(), 1);
  assert.deepEqual(reopened.getPage(0).getSize(), { width: 320, height: 240 });
  assert.ok(!reopened.catalog.has(PDFName.of('Metadata')));
  const cleanInfo = reopened.context.lookup(reopened.context.trailerInfo.Info, PDFDict);
  assert.equal(cleanInfo.get(PDFName.of('SourcePath'))?.toString(), '(/workspace/private/report.pdf)');
  assert.equal(cleanInfo.get(PDFName.of('PrivateField')), undefined);
  const pageContents = reopened.getPage(0).node.Contents();
  assert.ok(pageContents, 'page content stream remains');
  const annotationRef = reopened.getPage(0).node.Annots()?.get(0);
  assert.ok(annotationRef);
  const cleanAnnotation = reopened.context.lookup(annotationRef, PDFDict);
  assert.equal(cleanAnnotation.get(PDFName.of('T')), undefined);
  assert.ok(cleanAnnotation.get(PDFName.of('Contents')));
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('signed PDFs are returned unchanged for upload fallback', async () => {
  const pdf = await PDFDocument.create();
  pdf.addPage();
  pdf.context.register(pdf.context.obj({ Type: 'Sig', ByteRange: [0, 1, 2, 3] }));
  const bytes = await pdf.save({ useObjectStreams: false });
  assert.equal(await stripDocumentMetadata(bytes, 'application/pdf', 'signed.pdf'), undefined);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('Office ZIP removes properties, revision authors, archive metadata and embedded image metadata', async () => {
  const zip = new JSZip();
  zip.file('[Content_Types].xml', '<Types/>');
  zip.file('docProps/core.xml', '<cp:coreProperties xmlns:cp="urn:core" xmlns:dc="urn:dc"><dc:creator>CoreSecretAuthor</dc:creator></cp:coreProperties>');
  zip.file('docProps/custom.xml', '<Properties><property name="PrivateName">CustomSecretAuthor</property><property name="SourcePath">/project/folder/notes.docx</property></Properties>');
  zip.file('docProps/app.xml', '<Properties><Company>CompanySecretAuthor</Company><HyperlinkBase>../source/folder</HyperlinkBase></Properties>');
  zip.file('word/document.xml', '<w:document xmlns:w="urn:word"><w:body><w:p w:rsidR="1234"><w:r><w:t>Visible document text</w:t></w:r></w:p></w:body></w:document>', { comment: 'EntrySecretAuthor', date: new Date('2020-01-01') });
  zip.file('word/comments.xml', '<w:comments xmlns:w="urn:word"><w:comment w:author="CommentSecretAuthor" w:date="2020-01-01"><w:p><w:r><w:t>Useful comment text</w:t></w:r></w:p></w:comment></w:comments>');
  zip.file('word/media/image1.png', concat(
    Uint8Array.of(137, 80, 78, 71, 13, 10, 26, 10),
    pngChunk('IHDR', Uint8Array.of(0, 0, 0, 1, 0, 0, 0, 1, 8, 6, 0, 0, 0)),
    pngChunk('tEXt', text('ImageSecretAuthor')),
    pngChunk('IDAT', Uint8Array.of(1, 2, 3)),
    pngChunk('IEND', new Uint8Array()),
  ));
  const original = await zip.generateAsync({ type: 'uint8array', comment: 'ArchiveSecretAuthor' });

  const result = await stripDocumentMetadata(original, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'notes.docx');
  assert.ok(result);
  const raw = utf8(result);
  for (const secret of ['ArchiveSecretAuthor', 'CoreSecretAuthor', 'CustomSecretAuthor', 'CompanySecretAuthor', 'EntrySecretAuthor', 'CommentSecretAuthor', 'ImageSecretAuthor']) {
    assert.ok(!raw.includes(secret), `${secret} survived ZIP rewrite`);
  }
  const reopened = await JSZip.loadAsync(result, { checkCRC32: true });
  assert.equal(reopened.file('word/document.xml')?.comment, null);
  assert.match(await reopened.file('word/document.xml')!.async('string'), /Visible document text/);
  assert.match(await reopened.file('word/comments.xml')!.async('string'), /Useful comment text/);
  assert.doesNotMatch(await reopened.file('word/comments.xml')!.async('string'), /CommentSecretAuthor/);
  assert.match(await reopened.file('docProps/custom.xml')!.async('string'), /\/project\/folder\/notes\.docx/);
  assert.match(await reopened.file('docProps/app.xml')!.async('string'), /\.\.\/source\/folder/);
  assert.equal(reopened.file('word/document.xml')?.date.getFullYear(), 1980);
  assert.ok(!utf8(await reopened.file('word/media/image1.png')!.async('uint8array')).includes('ImageSecretAuthor'));
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('EPUB clears publication creator and date while retaining the reading spine', async () => {
  const zip = new JSZip();
  zip.file('mimetype', 'application/epub+zip', { compression: 'STORE' });
  zip.file('META-INF/container.xml', '<container/>');
  zip.file('OEBPS/book.opf', '<package xmlns:dc="http://purl.org/dc/elements/1.1/" unique-identifier="book-id"><metadata><dc:title>Useful title</dc:title><dc:identifier id="book-id">urn:isbn:1234567890</dc:identifier><dc:source>../source/book.epub</dc:source><dc:creator>BookSecretAuthor</dc:creator><meta property="dcterms:modified">2020-01-01</meta></metadata><spine><itemref idref="chapter"/></spine></package>');
  zip.file('OEBPS/chapter.xhtml', '<html><body>Readable chapter</body></html>');
  const result = await stripDocumentMetadata(await zip.generateAsync({ type: 'uint8array' }), 'application/epub+zip', 'book.epub');
  assert.ok(result);
  const reopened = await JSZip.loadAsync(result);
  const opf = await reopened.file('OEBPS/book.opf')!.async('string');
  assert.doesNotMatch(opf, /BookSecretAuthor|2020-01-01/);
  assert.match(opf, /Useful title|itemref/);
  assert.match(opf, /unique-identifier="book-id"/);
  assert.match(opf, /<dc:identifier id="book-id">urn:isbn:1234567890<\/dc:identifier>/);
  assert.match(opf, /<dc:source>\.\.\/source\/book\.epub<\/dc:source>/);
  assert.equal(Buffer.from(result).toString('utf8', 30, 38), 'mimetype');
  assert.equal(new DataView(result.buffer, result.byteOffset).getUint16(8, true), 0);
  assert.match(await reopened.file('OEBPS/chapter.xhtml')!.async('string'), /Readable chapter/);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('unsupported formats and signed Office packages use upload fallback', async () => {
  assert.equal(await stripDocumentMetadata(new Uint8Array([1, 2]), 'text/plain', 'notes.txt'), undefined);
  const zip = new JSZip();
  zip.file('_xmlsignatures/sig1.xml', '<Signature/>');
  zip.file('word/document.xml', '<document/>');
  assert.equal(await stripDocumentMetadata(await zip.generateAsync({ type: 'uint8array' }), 'application/zip', 'signed.docx'), undefined);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('generic project ZIP removes archive comments and timestamps without changing files', async () => {
  const zip = new JSZip();
  zip.file('src/notes.txt', 'Keep project text', { comment: 'EntrySecret', date: new Date('2024-01-01') });
  const result = await stripDocumentMetadata(await zip.generateAsync({ type: 'uint8array', comment: 'ArchiveSecret' }), 'application/zip', 'project.zip');
  assert.ok(result);
  assert.ok(!utf8(result).includes('EntrySecret'));
  assert.ok(!utf8(result).includes('ArchiveSecret'));
  const reopened = await JSZip.loadAsync(result);
  assert.equal(await reopened.file('src/notes.txt')!.async('string'), 'Keep project text');
  assert.equal(reopened.file('src/notes.txt')!.date.getFullYear(), 1980);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('ODF clears package and annotation creators while retaining text and stored mimetype', async () => {
  const zip = new JSZip();
  zip.file('mimetype', 'application/vnd.oasis.opendocument.text', { compression: 'STORE' });
  zip.file('meta.xml', '<office:document-meta xmlns:office="urn:office" xmlns:dc="urn:dc"><office:meta><dc:creator>PackageSecretAuthor</dc:creator></office:meta></office:document-meta>');
  zip.file('content.xml', '<office:document-content xmlns:office="urn:office" xmlns:dc="urn:dc" xmlns:text="urn:text"><office:body><office:text><text:p>Visible ODF text</text:p><office:annotation><dc:creator>NoteSecretAuthor</dc:creator><dc:date>2024-01-01</dc:date><text:p>Useful note</text:p></office:annotation></office:text></office:body></office:document-content>');
  const result = await stripDocumentMetadata(await zip.generateAsync({ type: 'uint8array' }), 'application/vnd.oasis.opendocument.text', 'notes.odt');
  assert.ok(result);
  const reopened = await JSZip.loadAsync(result);
  const meta = await reopened.file('meta.xml')!.async('string');
  assert.doesNotMatch(meta, /PackageSecretAuthor/);
  assert.match(meta, /<office:meta\s*\/>/);
  const content = await reopened.file('content.xml')!.async('string');
  assert.doesNotMatch(content, /NoteSecretAuthor|2024-01-01/);
  assert.match(content, /Visible ODF text|Useful note/);
  assert.equal(Buffer.from(result).toString('utf8', 30, 38), 'mimetype');
  assert.equal(new DataView(result.buffer, result.byteOffset).getUint16(8, true), 0);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('oversized ZIP declaration skips cleanup before expansion', async () => {
  const zip = new JSZip();
  zip.file('tiny.txt', 'safe content');
  const bytes = await zip.generateAsync({ type: 'uint8array' });
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const end = bytes.length - 22;
  assert.equal(view.getUint32(end, true), 0x06054b50);
  const centralDirectory = view.getUint32(end + 16, true);
  view.setUint32(centralDirectory + 24, 256 * 1024 * 1024 + 1, true);
  assert.equal(await stripDocumentMetadata(bytes, 'application/zip', 'oversized.zip'), undefined);
});

// contract-test: supporting surface=gui.web assertions=pii.surface.semantic-parity
test('ZIPs whose entry paths JSZip would normalize use the original upload', async () => {
  for (const path of ['folder/../report.txt', 'folder//report.txt', './report.txt', 'folder//']) {
    const zip = new JSZip();
    zip.file(path, 'Visible project content');
    const original = await zip.generateAsync({ type: 'uint8array' });
    assert.equal(await stripDocumentMetadata(original, 'application/zip', 'project.zip'), undefined, path);
  }
});
