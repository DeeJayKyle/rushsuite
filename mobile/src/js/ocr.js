// Offline OCR with tesseract.js (engine + English data are bundled in the app).
import { createWorker } from 'tesseract.js';
import { PDFDocument, StandardFonts } from 'pdf-lib';
import { openPdf, renderPage, pageText } from './pdfview.js';
import { addInvisibleText, parsePages, safeText, save } from './pdfcore.js';

let workerP = null;
function worker() {
  if (!workerP) {
    workerP = createWorker('eng', 1, {
      workerPath: 'vendor/tesseract-worker.min.js',
      corePath: 'vendor/tesseract-core',
      langPath: 'vendor/lang',
      gzip: true,
      cacheMethod: 'none',
      workerBlobURL: false,
    }).catch((e) => { workerP = null; throw e; });
  }
  return workerP;
}

/** canvas/image -> {text, words:[{text, x, y, w, h}]} in pixels */
export async function recognize(img) {
  const w = await worker();
  const { data } = await w.recognize(img, {}, { text: true, blocks: true });
  let words = data.words || [];
  if (!words.length && data.blocks) {
    for (const b of data.blocks) for (const p of b.paragraphs || []) for (const l of p.lines || []) words.push(...(l.words || []));
  }
  return {
    text: (data.text || '').trim(),
    words: words.map((x) => ({ text: x.text, x: x.bbox.x0, y: x.bbox.y0, w: x.bbox.x1 - x.bbox.x0, h: x.bbox.y1 - x.bbox.y0 })),
  };
}

export async function imageFileToCanvas(file, maxSide = 2400, enhance = 'Auto') {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
  const s = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas');
  c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
  const ctx = c.getContext('2d');
  ctx.drawImage(bmp, 0, 0, c.width, c.height);
  if (enhance !== 'Original') enhanceCanvas(c, enhance);
  return c;
}

/** Document clean-up: auto-contrast, whiten paper, optional grayscale / black & white. */
export function enhanceCanvas(c, mode = 'Auto') {
  const ctx = c.getContext('2d');
  const im = ctx.getImageData(0, 0, c.width, c.height);
  const d = im.data;
  let sat = 0;
  const hist = new Uint32Array(256);
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], g = d[i + 1], b = d[i + 2];
    sat += Math.max(r, g, b) - Math.min(r, g, b);
    hist[(r * 0.299 + g * 0.587 + b * 0.114) | 0]++;
  }
  sat /= d.length / 4;
  const n = d.length / 4;
  let lo = 0, hi = 255, acc = 0;
  for (; lo < 255 && (acc += hist[lo]) < n * 0.01; lo++);
  acc = 0;
  for (; hi > 0 && (acc += hist[hi]) < n * 0.08; hi--);   // paper becomes white
  lo = Math.max(0, Math.min(lo, hi - 90));     // never stretch a flat page into noise
  const span = Math.max(1, hi - lo);
  const color = mode === 'Color' || (mode === 'Auto' && sat > 28);
  for (let i = 0; i < d.length; i += 4) {
    if (color) {
      for (let k = 0; k < 3; k++) d[i + k] = Math.max(0, Math.min(255, ((d[i + k] - lo) * 255) / span));
    } else {
      let y = ((d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) - lo) * 255 / span;
      y = Math.max(0, Math.min(255, y));
      if (mode === 'Black & white') y = y > 150 ? 255 : 0;
      d[i] = d[i + 1] = d[i + 2] = y;
    }
  }
  ctx.putImageData(im, 0, 0);
  return c;
}

/** Add an invisible OCR text layer to scanned pages of a PDF (pages that already have text are kept). */
export async function ocrPdf(bytes, { spec = 'all', force = false } = {}, onProgress) {
  const src = await openPdf(bytes);
  const doc = await PDFDocument.load(bytes);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const idx = parsePages(spec, src.numPages);
  let done = 0;
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    if (!force && (await pageText(src, i)).length > 30) continue;
    onProgress && onProgress(k / idx.length, `Reading page ${i + 1} of ${src.numPages}`);
    const scale = 2.2;
    const c = await renderPage(src, i, scale);
    const r = await recognize(c);
    const page = doc.getPage(i);
    if (page.getRotation().angle % 360 === 0) {   // canvas px -> page points (rotated scans are rare: skipped)
      addInvisibleText(page, font, r.words.map((w) => ({ str: safeText(w.text), x: w.x / scale, y: w.y / scale, w: w.w / scale, h: w.h / scale })));
    }
    c.width = c.height = 0;
    done++;
  }
  return { bytes: await save(doc), pages: done };
}

/** Photos -> clean PDF pages (+ optional searchable text). */
export async function scanToPdf(files, { enhance = 'Auto', ocr = true, pageSize = 'A4' } = {}, onProgress) {
  const doc = await PDFDocument.create();
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const SIZES = { A4: [595.28, 841.89], Letter: [612, 792] };
  let text = '';
  for (let k = 0; k < files.length; k++) {
    onProgress && onProgress(k / files.length, `Cleaning page ${k + 1}`);
    const c = await imageFileToCanvas(files[k], 2400, enhance);
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.85));
    const img = await doc.embedJpg(new Uint8Array(await blob.arrayBuffer()));
    let [pw, ph] = pageSize === 'Fit to image' ? [c.width * 0.36, c.height * 0.36] : SIZES[pageSize] || SIZES.A4;
    if (pageSize !== 'Fit to image' && c.width > c.height) [pw, ph] = [ph, pw];
    const s = Math.min(pw / c.width, ph / c.height);
    const w = c.width * s, h = c.height * s, ox = (pw - w) / 2, oy = (ph - h) / 2;
    const page = doc.addPage([pw, ph]);
    page.drawImage(img, { x: ox, y: oy, width: w, height: h });
    if (ocr) {
      onProgress && onProgress((k + 0.5) / files.length, `Reading text on page ${k + 1}`);
      const r = await recognize(c);
      text += (text ? '\n\n' : '') + r.text;
      addInvisibleText(page, font, r.words.map((x) => ({ str: safeText(x.text), x: ox + x.x * s, y: (ph - oy - h) + x.y * s, w: x.w * s, h: x.h * s })));
    }
  }
  return { bytes: await save(doc), text };
}
