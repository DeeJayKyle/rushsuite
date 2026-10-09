// Every PDF tool, declared once: the generic tool screen is built from these definitions.
import * as C from './pdfcore.js';
import { openPdf, allText } from './pdfview.js';
import { ocrPdf, scanToPdf, imageFileToCanvas, recognize } from './ocr.js';
import * as AI from './ai.js';
import { stem, humanSize } from './ui.js';

const PDF = '.pdf,application/pdf';
const IMG = 'image/*';
const pdfOut = (name, bytes) => ({ name, bytes, mime: 'application/pdf' });
const txtOut = (name, text) => ({ name, bytes: new TextEncoder().encode(text), mime: 'text/plain' });

export const CATS = ['Organize', 'Optimize', 'Convert', 'Edit', 'Security', 'Intelligence'];

async function docxFromText(title, text) {
  const { Document, Packer, Paragraph, HeadingLevel, TextRun } = await import('docx');
  const paras = [new Paragraph({ text: title, heading: HeadingLevel.TITLE })];
  for (const line of text.split('\n')) {
    const m = line.match(/^(#{1,3})\s+(.*)/);
    if (m) paras.push(new Paragraph({ text: m[2], heading: m[1].length === 1 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2 }));
    else if (/^\s*[-*•]\s+/.test(line)) paras.push(new Paragraph({ children: [new TextRun(line.replace(/^\s*[-*•]\s+/, '').replace(/\*\*/g, ''))], bullet: { level: 0 } }));
    else paras.push(new Paragraph({ children: [new TextRun(line.replace(/\*\*/g, ''))] }));
  }
  const doc = new Document({ sections: [{ children: paras }] });
  const blob = await Packer.toBlob(doc);
  return new Uint8Array(await blob.arrayBuffer());
}
const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

export const TOOLS = [
  // ------------------------------------------------------------- Organize
  { id: 'merge', name: 'Merge PDF', cat: 'Organize', icon: 'merge', color: '#FF6B6B', accept: `${PDF},${IMG}`, multiple: true, min: 2, order: true,
    desc: 'Combine PDFs (and photos) in the order you want into one PDF.',
    params: [{ key: 'name', label: 'File name', kind: 'text', def: 'merged' }],
    async run({ items, p, progress }) { return { outputs: [pdfOut(`${p.name || 'merged'}.pdf`, await C.merge(items, progress))] }; } },
  { id: 'split', name: 'Split PDF', cat: 'Organize', icon: 'split', color: '#FF6B6B', accept: PDF,
    desc: 'Separate one page or a whole set for easy conversion into independent PDF files.',
    params: [{ key: 'mode', label: 'Split', kind: 'choice', def: 'Custom ranges', options: ['Custom ranges', 'Every page', 'Every N pages'] },
      { key: 'ranges', label: 'Ranges (one file each)', kind: 'text', def: '1-2, 3-', show: ['mode', 'Custom ranges'] },
      { key: 'n', label: 'Pages per file', kind: 'number', def: 2, show: ['mode', 'Every N pages'] }],
    async run({ items, p }) {
      const parts = await C.split(items[0].bytes, p.mode, p.ranges, p.n);
      return { outputs: parts.map((x, k) => pdfOut(`${stem(items[0].name)}_${k + 1}_p${x.pages[0] + 1}-${x.pages[x.pages.length - 1] + 1}.pdf`, x.bytes)) };
    } },
  { id: 'organize', name: 'Organize PDF', cat: 'Organize', icon: 'organize', color: '#FF6B6B', accept: PDF, multiple: true, page: 'organize',
    desc: 'Sort, rotate, delete or add pages - visually, with thumbnails.' },
  { id: 'remove', name: 'Remove pages', cat: 'Organize', icon: 'trash', color: '#FF6B6B', accept: PDF,
    desc: 'Delete the pages you don\'t need.',
    params: [{ key: 'pages', label: 'Pages to remove', kind: 'pages', def: '' }],
    async run({ items, p }) { return { outputs: [pdfOut(`${stem(items[0].name)}_removed.pdf`, await C.removePages(items[0].bytes, p.pages))] }; } },
  { id: 'extract', name: 'Extract pages', cat: 'Organize', icon: 'extract', color: '#FF6B6B', accept: PDF,
    desc: 'Get only the pages you need as a new PDF.',
    params: [{ key: 'pages', label: 'Pages to keep', kind: 'pages', def: '1' }],
    async run({ items, p }) {
      const doc = await C.load(items[0].bytes);
      return { outputs: [pdfOut(`${stem(items[0].name)}_extract.pdf`, await C.selectPages(items[0].bytes, C.parsePages(p.pages, doc.getPageCount())))] };
    } },
  { id: 'rotate', name: 'Rotate PDF', cat: 'Organize', icon: 'rotate', color: '#FF6B6B', accept: PDF, multiple: true,
    desc: 'Rotate pages the way you need them.',
    params: [{ key: 'angle', label: 'Rotate', kind: 'choice', def: '90° right', options: ['90° right', '90° left', '180°'] },
      { key: 'pages', label: 'Pages', kind: 'pages', def: 'all' }],
    async run({ items, p }) {
      const a = { '90° right': 90, '90° left': 270, '180°': 180 }[p.angle];
      const outputs = [];
      for (const it of items) outputs.push(pdfOut(`${stem(it.name)}_rotated.pdf`, await C.rotate(it.bytes, p.pages, a)));
      return { outputs };
    } },
  // ------------------------------------------------------------- Optimize
  { id: 'compress', name: 'Compress PDF', cat: 'Optimize', icon: 'compress', color: '#3DDC97', accept: PDF, multiple: true,
    desc: 'Reduce file size while keeping the best quality possible.',
    params: [{ key: 'level', label: 'Compression', kind: 'choice', def: 'Recommended', options: ['Lossless', 'Recommended', 'Strong'] },
      { key: 'keepText', label: 'Keep text searchable', kind: 'bool', def: true }],
    async run({ items, p, progress }) {
      const outputs = []; const notes = [];
      for (const it of items) {
        const b = await C.compress(it.bytes, p.level, p.keepText, progress);
        notes.push(`${it.name}: ${humanSize(it.bytes.length)} → ${humanSize(b.length)}${b.length >= it.bytes.length ? ' (already optimal)' : ''}`);
        outputs.push(pdfOut(`${stem(it.name)}_compressed.pdf`, b));
      }
      return { outputs, note: notes.join('\n') };
    } },
  { id: 'ocr', name: 'OCR PDF', cat: 'Optimize', icon: 'ocr', color: '#3DDC97', accept: PDF,
    desc: 'Make scanned PDFs searchable and selectable (offline).',
    params: [{ key: 'pages', label: 'Pages', kind: 'pages', def: 'all' }, { key: 'force', label: 'Also re-read pages that already have text', kind: 'bool', def: false }],
    async run({ items, p, progress }) {
      const r = await ocrPdf(items[0].bytes, { spec: p.pages, force: p.force }, progress);
      if (!r.pages) throw new Error('This PDF already has selectable text. Tick "re-read" to OCR it anyway.');
      return { outputs: [pdfOut(`${stem(items[0].name)}_ocr.pdf`, r.bytes)], note: `${r.pages} page(s) made searchable.` };
    } },
  { id: 'repair', name: 'Repair PDF', cat: 'Optimize', icon: 'repair', color: '#3DDC97', accept: PDF,
    desc: 'Rebuild a damaged PDF so it opens again.',
    async run({ items }) { return { outputs: [pdfOut(`${stem(items[0].name)}_repaired.pdf`, await C.repair(items[0].bytes))] }; } },
  // ------------------------------------------------------------- Convert
  { id: 'img2pdf', name: 'JPG to PDF', cat: 'Convert', icon: 'image', color: '#FFC857', accept: IMG, multiple: true, order: true,
    desc: 'Turn photos and images into a PDF. Adjust page size and margins.',
    params: [{ key: 'page', label: 'Page size', kind: 'choice', def: 'A4', options: ['A4', 'Letter', 'Legal', 'A5', 'Fit to image'] },
      { key: 'orientation', label: 'Orientation', kind: 'choice', def: 'Auto', options: ['Auto', 'Portrait', 'Landscape'] },
      { key: 'margin', label: 'Margin', kind: 'choice', def: 'Small', options: ['None', 'Small', 'Big'] },
      { key: 'name', label: 'File name', kind: 'text', def: 'images' }],
    async run({ items, p, progress }) {
      const margin = { None: 0, Small: 20, Big: 50 }[p.margin];
      return { outputs: [pdfOut(`${p.name || 'images'}.pdf`, await C.imagesToPdf(items, { pageSize: p.page, margin, orientation: p.orientation }, progress))] };
    } },
  { id: 'scan', name: 'Scan to PDF', cat: 'Convert', icon: 'scan', color: '#FFC857', accept: IMG, multiple: true, camera: true, order: true,
    desc: 'Photograph paper documents: cleaned up, made into a PDF, with searchable text.',
    params: [{ key: 'enhance', label: 'Enhance', kind: 'choice', def: 'Auto', options: ['Auto', 'Black & white', 'Grayscale', 'Color', 'Original'] },
      { key: 'page', label: 'Page size', kind: 'choice', def: 'A4', options: ['A4', 'Letter', 'Fit to image'] },
      { key: 'ocr', label: 'Make text searchable (OCR)', kind: 'bool', def: true },
      { key: 'name', label: 'File name', kind: 'text', def: 'scan' }],
    async run({ files, p, progress }) {
      const r = await scanToPdf(files, { enhance: p.enhance, ocr: p.ocr, pageSize: p.page }, progress);
      return { outputs: [pdfOut(`${p.name || 'scan'}.pdf`, r.bytes)], text: r.text };
    } },
  { id: 'pdf2jpg', name: 'PDF to JPG', cat: 'Convert', icon: 'image', color: '#FFC857', accept: PDF,
    desc: 'Convert each PDF page into an image.',
    params: [{ key: 'format', label: 'Format', kind: 'choice', def: 'jpg', options: ['jpg', 'png'] },
      { key: 'dpi', label: 'Quality (DPI)', kind: 'choice', def: '150', options: ['72', '150', '220', '300'] },
      { key: 'pages', label: 'Pages', kind: 'pages', def: 'all' },
      { key: 'zip', label: 'Put all images in one ZIP', kind: 'bool', def: false }],
    async run({ items, p, progress }) {
      const r = await C.pdfToImages(items[0].bytes, { dpi: Number(p.dpi), format: p.format, spec: p.pages }, progress);
      const s = stem(items[0].name);
      return { outputs: p.zip || r.files.length > 20 ? [{ name: `${s}_images.zip`, bytes: r.zip, mime: 'application/zip' }]
        : r.files.map((f) => ({ name: `${s}_${f.name}`, bytes: f.bytes, mime: `image/${p.format === 'png' ? 'png' : 'jpeg'}` })) };
    } },
  { id: 'pdf2word', name: 'PDF to Word', cat: 'Convert', icon: 'word', color: '#2B6CB0', accept: PDF,
    desc: 'Get the text of a PDF as an editable Word document.',
    async run({ items, progress }) {
      const doc = await openPdf(items[0].bytes);
      const pages = await allText(doc, progress);
      const text = pages.join('\n\n');
      if (!text.trim()) throw new Error('No text found - it may be a scan. Run OCR PDF first.');
      return { outputs: [{ name: `${stem(items[0].name)}.docx`, bytes: await docxFromText(stem(items[0].name), text), mime: DOCX }], text };
    } },
  { id: 'pdf2text', name: 'PDF to Text', cat: 'Convert', icon: 'text', color: '#9BA3B8', accept: PDF,
    desc: 'All the text of a PDF as a .txt file.',
    async run({ items, progress }) {
      const pages = await allText(await openPdf(items[0].bytes), progress);
      const text = pages.join('\n\n');
      return { outputs: [txtOut(`${stem(items[0].name)}.txt`, text)], text };
    } },
  { id: 'img2text', name: 'Image to Text (OCR)', cat: 'Convert', icon: 'ocr', color: '#9BA3B8', accept: IMG, multiple: true, camera: true,
    desc: 'Recognise the text in photos or screenshots.',
    async run({ files, progress }) {
      let text = '';
      for (let k = 0; k < files.length; k++) {
        progress(k / files.length, `Reading image ${k + 1}`);
        text += `${text ? '\n\n' : ''}${(await recognize(await imageFileToCanvas(files[k]))).text}`;
      }
      return { outputs: [txtOut('scanned_text.txt', text)], text };
    } },
  // ------------------------------------------------------------- Edit
  { id: 'edit', name: 'Edit PDF', cat: 'Edit', icon: 'edit', color: '#9B7BFF', accept: PDF, page: 'annotate',
    desc: 'Add text, images, highlights, drawings or cover things up.' },
  { id: 'watermark', name: 'Watermark', cat: 'Edit', icon: 'watermark', color: '#9B7BFF', accept: PDF, multiple: true,
    desc: 'Stamp text over your PDF - choose size, colour, transparency and position.',
    params: [{ key: 'text', label: 'Text', kind: 'text', def: 'CONFIDENTIAL' },
      { key: 'position', label: 'Position', kind: 'choice', def: 'Center', options: ['Center', 'Tiled', 'Top left', 'Top right', 'Bottom left', 'Bottom right'] },
      { key: 'size', label: 'Size', kind: 'number', def: 48 }, { key: 'opacity', label: 'Opacity (0-1)', kind: 'number', def: 0.25 },
      { key: 'angle', label: 'Angle', kind: 'number', def: 45 }, { key: 'color', label: 'Colour', kind: 'color', def: '#D62828' },
      { key: 'pages', label: 'Pages', kind: 'pages', def: 'all' }],
    async run({ items, p }) {
      const outputs = [];
      for (const it of items) outputs.push(pdfOut(`${stem(it.name)}_watermarked.pdf`, await C.watermark(it.bytes, { ...p, spec: p.pages })));
      return { outputs };
    } },
  { id: 'numbers', name: 'Page numbers', cat: 'Edit', icon: 'numbers', color: '#9B7BFF', accept: PDF, multiple: true,
    desc: 'Add page numbers - pick the position and style.',
    params: [{ key: 'format', label: 'Format', kind: 'choice', def: '{n}', options: ['{n}', 'Page {n}', 'Page {n} of {total}', '{n} / {total}', '- {n} -'] },
      { key: 'position', label: 'Position', kind: 'choice', def: 'Bottom center', options: ['Bottom center', 'Bottom right', 'Bottom left', 'Top center', 'Top right', 'Top left'] },
      { key: 'start', label: 'First number', kind: 'number', def: 1 }, { key: 'size', label: 'Size', kind: 'number', def: 11 },
      { key: 'pages', label: 'Pages', kind: 'pages', def: 'all' }],
    async run({ items, p }) {
      const outputs = [];
      for (const it of items) outputs.push(pdfOut(`${stem(it.name)}_numbered.pdf`, await C.pageNumbers(it.bytes, { ...p, spec: p.pages })));
      return { outputs };
    } },
  { id: 'crop', name: 'Crop PDF', cat: 'Edit', icon: 'crop', color: '#9B7BFF', accept: PDF,
    desc: 'Trim the margins of your pages.',
    params: [{ key: 'top', label: 'Top (mm)', kind: 'number', def: 10 }, { key: 'bottom', label: 'Bottom (mm)', kind: 'number', def: 10 },
      { key: 'left', label: 'Left (mm)', kind: 'number', def: 10 }, { key: 'right', label: 'Right (mm)', kind: 'number', def: 10 },
      { key: 'pages', label: 'Pages', kind: 'pages', def: 'all' }],
    async run({ items, p }) {
      return { outputs: [pdfOut(`${stem(items[0].name)}_cropped.pdf`, await C.crop(items[0].bytes, { ...p, spec: p.pages }))] };
    } },
  { id: 'forms', name: 'Fill PDF forms', cat: 'Edit', icon: 'form', color: '#9B7BFF', accept: PDF, page: 'forms',
    desc: 'Fill in fillable PDF forms on your phone, and flatten them if you like.' },
  { id: 'flatten', name: 'Flatten PDF', cat: 'Edit', icon: 'layers', color: '#9B7BFF', accept: PDF,
    desc: 'Make form fields part of the page so they can no longer be changed.',
    async run({ items }) { return { outputs: [pdfOut(`${stem(items[0].name)}_flattened.pdf`, await C.flatten(items[0].bytes))] }; } },
  // ------------------------------------------------------------- Security
  { id: 'sign', name: 'Sign PDF', cat: 'Security', icon: 'sign', color: '#4DA3FF', accept: PDF, page: 'sign',
    desc: 'Draw your signature with your finger and place it, plus the date and your name.' },
  { id: 'protect', name: 'Protect PDF', cat: 'Security', icon: 'lock', color: '#4DA3FF', accept: PDF,
    desc: 'Encrypt a PDF with a password (AES).',
    params: [{ key: 'password', label: 'Password', kind: 'password', def: '' },
      { key: 'allowPrint', label: 'Allow printing', kind: 'bool', def: true }, { key: 'allowCopy', label: 'Allow copying text', kind: 'bool', def: true },
      { key: 'allowEdit', label: 'Allow editing', kind: 'bool', def: false }],
    async run({ items, p }) { return { outputs: [pdfOut(`${stem(items[0].name)}_protected.pdf`, await C.protect(items[0].bytes, p))] }; } },
  { id: 'unlock', name: 'Unlock PDF', cat: 'Security', icon: 'unlock', color: '#4DA3FF', accept: PDF,
    desc: 'Remove the password from PDFs you own.',
    params: [{ key: 'password', label: 'Password', kind: 'password', def: '' }],
    async run({ items, p, progress }) {
      const r = await C.unlock(items[0].bytes, p.password, progress);
      return { outputs: [pdfOut(`${stem(items[0].name)}_unlocked.pdf`, r.bytes)], note: r.exact ? '' : 'Pages were rebuilt as images with searchable text.' };
    } },
  { id: 'redact', name: 'Redact PDF', cat: 'Security', icon: 'redact', color: '#4DA3FF', accept: PDF, page: 'redact',
    desc: 'Permanently remove names, numbers, e-mails or any area you mark.' },
  // ------------------------------------------------------------- Intelligence
  { id: 'compare', name: 'Compare PDF', cat: 'Intelligence', icon: 'compare', color: '#7C5CFF', accept: PDF, page: 'compare',
    desc: 'See exactly which words changed between two versions.' },
  { id: 'summarize', name: 'AI Summarizer', cat: 'Intelligence', icon: 'ai', color: '#7C5CFF', accept: PDF, ai: true,
    desc: 'Key points of a long PDF in seconds (uses your AI key).',
    params: [{ key: 'length', label: 'Length', kind: 'choice', def: 'Medium', options: ['Short', 'Medium', 'Detailed'] },
      { key: 'language', label: 'Language', kind: 'choice', def: 'Same as document', options: ['Same as document', ...AI.LANGUAGES] },
      { key: 'focus', label: 'Focus on (optional)', kind: 'text', def: '' },
      { key: 'output', label: 'Save as', kind: 'choice', def: 'Word (.docx)', options: ['Word (.docx)', 'Text (.txt)', 'Markdown (.md)'] }],
    async run({ items, p, progress }) {
      const text = (await allText(await openPdf(items[0].bytes))).join('\n\n');
      const md = await AI.summarize(text, p, progress);
      const s = `${stem(items[0].name)}_summary`;
      const out = p.output.startsWith('Word') ? { name: `${s}.docx`, bytes: await docxFromText(`Summary - ${stem(items[0].name)}`, md), mime: DOCX }
        : txtOut(`${s}.${p.output.startsWith('Markdown') ? 'md' : 'txt'}`, md);
      return { outputs: [out], text: md };
    } },
  { id: 'translate', name: 'Translate PDF', cat: 'Intelligence', icon: 'translate', color: '#7C5CFF', accept: PDF, ai: true,
    desc: 'Translate the text of a PDF into 30+ languages (uses your AI key).',
    params: [{ key: 'language', label: 'Translate to', kind: 'choice', def: 'English', options: AI.LANGUAGES }],
    async run({ items, p, progress }) {
      const text = (await allText(await openPdf(items[0].bytes))).join('\n\n');
      if (!text.trim()) throw new Error('No text found - run OCR PDF first.');
      const t = await AI.translate(text, p.language, progress);
      return { outputs: [{ name: `${stem(items[0].name)}_${p.language.split(' ')[0].toLowerCase()}.docx`, bytes: await docxFromText(`${stem(items[0].name)} (${p.language})`, t), mime: DOCX }], text: t };
    } },
];

export const byId = Object.fromEntries(TOOLS.map((t) => [t.id, t]));
