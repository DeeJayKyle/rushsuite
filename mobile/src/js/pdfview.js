// PDF.js helpers: open, render pages to canvases, extract text (with positions).
import * as pdfjs from 'pdfjs';

pdfjs.GlobalWorkerOptions.workerSrc = 'vendor/pdf.worker.min.mjs';

export async function openPdf(bytes, password = undefined) {
  const task = pdfjs.getDocument({ data: bytes.slice(0), password, isEvalSupported: false, useSystemFonts: true });
  return task.promise;
}

export function isPasswordError(e) {
  return e && (e.name === 'PasswordException' || /password/i.test(e.message || ''));
}

export async function renderPage(doc, index, scale = 1.5) {
  const page = await doc.getPage(index + 1);
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: ctx, canvas, viewport }).promise;
  page.cleanup();
  return canvas;
}

/** Render to fit a width in CSS pixels (sharp on high-DPI screens). */
export async function renderFit(doc, index, cssWidth) {
  const page = await doc.getPage(index + 1);
  const vp1 = page.getViewport({ scale: 1 });
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
  const scale = (cssWidth / vp1.width) * dpr;
  const c = await renderPage(doc, index, scale);
  c.style.width = `${cssWidth}px`;
  c.style.height = `${(vp1.height / vp1.width) * cssWidth}px`;
  return { canvas: c, width: vp1.width, height: vp1.height };
}

export async function pageText(doc, index) {
  const page = await doc.getPage(index + 1);
  const tc = await page.getTextContent();
  let out = '';
  let lastY = null;
  for (const it of tc.items) {
    if (!('str' in it)) continue;
    const y = it.transform[5];
    if (lastY !== null && Math.abs(y - lastY) > 2) out += '\n';
    else if (out && !out.endsWith(' ') && it.str && !it.str.startsWith(' ')) out += ' ';
    out += it.str;
    if (it.hasEOL) out += '\n';
    lastY = y;
  }
  return out.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
}

export async function allText(doc, onProgress = null) {
  const parts = [];
  for (let i = 0; i < doc.numPages; i++) {
    onProgress && onProgress(i / doc.numPages, `Reading page ${i + 1}`);
    parts.push(await pageText(doc, i));
  }
  return parts;
}

let measureCtx = null;
/** x-offset (fraction of the item width) where character `i` starts, measured with a similar font. */
export function charOffset(str, i) {
  if (!measureCtx) { measureCtx = document.createElement('canvas').getContext('2d'); measureCtx.font = '100px Helvetica, Arial, sans-serif'; }
  const full = measureCtx.measureText(str).width || 1;
  return measureCtx.measureText(str.slice(0, i)).width / full;
}

/** Split a line item into word items (better hit-testing for redaction / text layers). */
export function splitWords(it) {
  const out = [];
  const re = /\S+/g;
  let m;
  while ((m = re.exec(it.str))) {
    const a = charOffset(it.str, m.index), b = charOffset(it.str, m.index + m[0].length);
    out.push({ str: m[0], x: it.x + it.w * a, y: it.y, w: Math.max(1, it.w * (b - a)), h: it.h });
  }
  return out;
}

/** Text items with boxes in *viewport* (top-left, visual) coordinates at scale 1. */
export async function textBoxes(doc, index) {
  const page = await doc.getPage(index + 1);
  const vp = page.getViewport({ scale: 1 });
  const tc = await page.getTextContent();
  const items = [];
  for (const it of tc.items) {
    if (!it.str) continue;
    const tx = pdfjs.Util.transform(vp.transform, it.transform);
    const fontH = Math.hypot(tx[2], tx[3]);
    const w = it.width * (vp.scale || 1);
    items.push({ str: it.str, x: tx[4], y: tx[5] - fontH, w: Math.max(w, fontH * 0.3 * it.str.length), h: fontH * 1.2 });
  }
  return { items, width: vp.width, height: vp.height };
}
