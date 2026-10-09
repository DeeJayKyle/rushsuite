// PDF operations with pdf-lib (the Android build uses @cantoo/pdf-lib, which adds encryption).
import { PDFDocument, StandardFonts, degrees, rgb } from 'pdf-lib';
import JSZip from 'jszip';
import { openPdf, renderPage, textBoxes, charOffset, splitWords } from './pdfview.js';

export const PAGE_SIZES = { A4: [595.28, 841.89], Letter: [612, 792], Legal: [612, 1008], A5: [419.53, 595.28] };
const MM = 72 / 25.4;

export async function load(bytes, password) {
  try {
    return await PDFDocument.load(bytes, password ? { password, ignoreEncryption: false } : { ignoreEncryption: false });
  } catch (e) {
    if (/encrypt/i.test(e.message || '')) {
      const err = new Error('This PDF is password-protected. Use Unlock PDF first.');
      err.encrypted = true;
      throw err;
    }
    throw new Error(`Couldn't read this PDF (${e.message}). Try Repair PDF.`);
  }
}

export const save = (doc) => doc.save({ useObjectStreams: true });

export function parsePages(spec, n) {
  spec = String(spec || '').trim().toLowerCase();
  if (!spec || spec === 'all' || spec === '*') return [...Array(n).keys()];
  if (spec === 'odd') return [...Array(n).keys()].filter((i) => i % 2 === 0);
  if (spec === 'even') return [...Array(n).keys()].filter((i) => i % 2 === 1);
  const out = [];
  for (let part of spec.split(/[,\s;]+/)) {
    if (!part) continue;
    part = part.replace(/last|end/g, String(n));
    const m = part.match(/^(\d*)-(\d*)$/);
    if (m) {
      const a = parseInt(m[1] || '1', 10);
      const b = parseInt(m[2] || String(n), 10);
      const step = b >= a ? 1 : -1;
      for (let i = a; step > 0 ? i <= b : i >= b; i += step) if (i >= 1 && i <= n) out.push(i - 1);
    } else if (/^\d+$/.test(part)) {
      const i = parseInt(part, 10);
      if (i >= 1 && i <= n) out.push(i - 1);
    } else {
      throw new Error(`Can't understand the page range "${part}". Use e.g. 1-3, 5, 8-`);
    }
  }
  return out;
}

// ------------------------------------------------------------------ visual coordinates
/** Map visual top-left points (as displayed) to PDF user space for a page, honouring /Rotate and the crop box. */
export function visualFrame(page) {
  const box = page.getCropBox ? page.getCropBox() : { x: 0, y: 0, ...page.getSize() };
  const r = ((page.getRotation().angle % 360) + 360) % 360;
  const w = box.width, h = box.height;
  const vw = r % 180 ? h : w, vh = r % 180 ? w : h;
  const toPdf = (vx, vyTop) => {
    const vy = vh - vyTop;                      // visual bottom-up
    let u, v;
    if (r === 90) { u = w - vy; v = vx; } else if (r === 180) { u = w - vx; v = h - vy; } else if (r === 270) { u = vy; v = h - vx; } else { u = vx; v = vy; }
    return { x: box.x + u, y: box.y + v };
  };
  return { vw, vh, rot: r, toPdf, rotate: degrees(r) };
}

const WINANSI = /[^\x20-\x7E -ÿ–—‘’“”•…€\n]/g;
export const safeText = (s) => String(s ?? '').replace(WINANSI, '?');

export function hexRgb(hex) {
  const h = (hex || '#000000').replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

// ------------------------------------------------------------------ organize
export async function merge(items, onProgress) {
  const out = await PDFDocument.create();
  for (let k = 0; k < items.length; k++) {
    const it = items[k];
    onProgress && onProgress(k / items.length, `Adding ${it.name}`);
    if (it.type.startsWith('image/') || /\.(jpe?g|png|webp|bmp|gif)$/i.test(it.name)) {
      await addImagePage(out, it.bytes, it.name, 'Fit to image', 0);
    } else {
      const src = await load(it.bytes);
      const pages = await out.copyPages(src, src.getPageIndices());
      pages.forEach((p) => out.addPage(p));
    }
  }
  return save(out);
}

export async function selectPages(bytes, indices) {
  const src = await load(bytes);
  const out = await PDFDocument.create();
  const pages = await out.copyPages(src, indices);
  pages.forEach((p) => out.addPage(p));
  return save(out);
}

export async function split(bytes, mode, spec, everyN) {
  const src = await load(bytes);
  const n = src.getPageCount();
  let groups = [];
  if (mode === 'Every page') groups = [...Array(n).keys()].map((i) => [i]);
  else if (mode === 'Every N pages') {
    const N = Math.max(1, parseInt(everyN, 10) || 1);
    for (let i = 0; i < n; i += N) groups.push([...Array(Math.min(N, n - i)).keys()].map((k) => i + k));
  } else {
    groups = String(spec || '').split(',').map((s) => s.trim()).filter(Boolean).map((s) => parsePages(s, n)).filter((g) => g.length);
    if (!groups.length) throw new Error('Type the ranges, e.g. 1-3, 4-6, 7');
  }
  const outs = [];
  for (const g of groups) {
    const d = await PDFDocument.create();
    (await d.copyPages(src, g)).forEach((p) => d.addPage(p));
    outs.push({ pages: g, bytes: await save(d) });
  }
  return outs;
}

export async function removePages(bytes, spec) {
  const src = await load(bytes);
  const n = src.getPageCount();
  const drop = new Set(parsePages(spec, n));
  const keep = [...Array(n).keys()].filter((i) => !drop.has(i));
  if (!keep.length) throw new Error("That would remove every page.");
  return selectPages(bytes, keep);
}

export async function rotate(bytes, spec, angle) {
  const doc = await load(bytes);
  for (const i of parsePages(spec, doc.getPageCount())) {
    const p = doc.getPage(i);
    p.setRotation(degrees((((p.getRotation().angle + angle) % 360) + 360) % 360));
  }
  return save(doc);
}

/** refs: [{src: bytesKey|null, page, rot}] with sources {key: bytes} */
export async function organize(refs, sources) {
  const out = await PDFDocument.create();
  const loaded = {};
  for (const r of refs) {
    if (r.src === null) {
      out.addPage(r.size || PAGE_SIZES.A4);
    } else {
      loaded[r.src] = loaded[r.src] || await load(sources[r.src]);
      const [p] = await out.copyPages(loaded[r.src], [r.page]);
      out.addPage(p);
    }
    if (r.rot) {
      const p = out.getPage(out.getPageCount() - 1);
      p.setRotation(degrees((p.getRotation().angle + r.rot) % 360));
    }
  }
  return save(out);
}

// ------------------------------------------------------------------ images
async function toEmbeddable(bytes, name) {
  if (/\.(jpe?g)$/i.test(name) || (bytes[0] === 0xff && bytes[1] === 0xd8)) return { kind: 'jpg', bytes };
  if (/\.png$/i.test(name) || (bytes[0] === 0x89 && bytes[1] === 0x50)) return { kind: 'png', bytes };
  const bmp = await createImageBitmap(new Blob([bytes]));
  const c = document.createElement('canvas');
  c.width = bmp.width; c.height = bmp.height;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(bmp, 0, 0);
  const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
  return { kind: 'jpg', bytes: new Uint8Array(await blob.arrayBuffer()) };
}

export async function addImagePage(doc, bytes, name, pageSize = 'A4', margin = 20, orientation = 'Auto') {
  const e = await toEmbeddable(bytes, name);
  const img = e.kind === 'jpg' ? await doc.embedJpg(e.bytes) : await doc.embedPng(e.bytes);
  let pw, ph;
  if (pageSize === 'Fit to image') { pw = img.width * 0.75 + 2 * margin; ph = img.height * 0.75 + 2 * margin; }
  else {
    [pw, ph] = PAGE_SIZES[pageSize] || PAGE_SIZES.A4;
    const land = orientation === 'Landscape' || (orientation === 'Auto' && img.width > img.height);
    if (land) [pw, ph] = [ph, pw];
  }
  const page = doc.addPage([pw, ph]);
  const s = Math.min((pw - 2 * margin) / img.width, (ph - 2 * margin) / img.height);
  const w = img.width * s, h = img.height * s;
  page.drawImage(img, { x: (pw - w) / 2, y: (ph - h) / 2, width: w, height: h });
  return page;
}

export async function imagesToPdf(items, { pageSize = 'A4', margin = 20, orientation = 'Auto' } = {}, onProgress) {
  const doc = await PDFDocument.create();
  for (let k = 0; k < items.length; k++) {
    onProgress && onProgress(k / items.length, `Image ${k + 1} of ${items.length}`);
    await addImagePage(doc, items[k].bytes, items[k].name, pageSize, margin, orientation);
  }
  return save(doc);
}

export async function pdfToImages(bytes, { dpi = 150, format = 'jpg', spec = 'all' } = {}, onProgress) {
  const doc = await openPdf(bytes);
  const idx = parsePages(spec, doc.numPages);
  const zip = new JSZip();
  const files = [];
  for (let k = 0; k < idx.length; k++) {
    onProgress && onProgress(k / idx.length, `Page ${idx[k] + 1}`);
    const c = await renderPage(doc, idx[k], dpi / 72);
    const blob = await new Promise((r) => c.toBlob(r, format === 'png' ? 'image/png' : 'image/jpeg', 0.9));
    const b = new Uint8Array(await blob.arrayBuffer());
    const name = `page${String(idx[k] + 1).padStart(String(doc.numPages).length, '0')}.${format}`;
    zip.file(name, b);
    files.push({ name, bytes: b });
    c.width = c.height = 0;
  }
  return { files, zip: await zip.generateAsync({ type: 'uint8array' }) };
}

// ------------------------------------------------------------------ optimize
export async function compress(bytes, level, keepText, onProgress) {
  const lossless = await (async () => { const d = await load(bytes); return save(d); })();
  if (level === 'Lossless') return lossless.length < bytes.length ? lossless : bytes;
  const dpi = level === 'Strong' ? 96 : 144;
  const quality = level === 'Strong' ? 0.55 : 0.72;
  const src = await openPdf(bytes);
  const out = await PDFDocument.create();
  const font = keepText ? await out.embedFont(StandardFonts.Helvetica) : null;
  for (let i = 0; i < src.numPages; i++) {
    onProgress && onProgress(i / src.numPages, `Page ${i + 1} of ${src.numPages}`);
    const c = await renderPage(src, i, dpi / 72);
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', quality));
    const img = await out.embedJpg(new Uint8Array(await blob.arrayBuffer()));
    const tb = await textBoxes(src, i);
    const page = out.addPage([tb.width, tb.height]);
    page.drawImage(img, { x: 0, y: 0, width: tb.width, height: tb.height });
    if (font) addInvisibleText(page, font, tb.items.map((t) => ({ ...t, str: safeText(t.str) })));
    c.width = c.height = 0;
  }
  const res = await save(out);
  return res.length < Math.min(bytes.length, lossless.length) ? res : (lossless.length < bytes.length ? lossless : bytes);
}

/** Searchable but invisible text over a page image. items in visual top-left points. */
export function addInvisibleText(page, font, items) {
  const H = page.getHeight();
  for (const t of items) {
    const s = (t.str || '').trim();
    if (!s) continue;
    const size = Math.max(2, t.h * 0.8);
    const wNat = font.widthOfTextAtSize(s, size) || 1;
    try {
      page.drawText(s, { x: t.x, y: H - t.y - t.h * 0.85, size: size * Math.min(3, Math.max(0.3, t.w / wNat)), font, opacity: 0 });
    } catch { /* unsupported glyphs */ }
  }
}

export async function repair(bytes) {
  const doc = await PDFDocument.load(bytes, { ignoreEncryption: true, throwOnInvalidObject: false, updateMetadata: false });
  return save(doc);
}

// ------------------------------------------------------------------ edit
function anchor(pos, W, H, w, h, m = 24) {
  const x = pos.includes('left') ? m : pos.includes('right') ? W - w - m : (W - w) / 2;
  const y = pos.startsWith('top') ? H - h - m : pos.startsWith('bottom') ? m : (H - h) / 2;
  return [x, y];
}

export async function watermark(bytes, { text = 'CONFIDENTIAL', size = 48, opacity = 0.25, angle = 45, color = '#D62828', position = 'Center', spec = 'all' } = {}) {
  const doc = await load(bytes);
  const font = await doc.embedFont(StandardFonts.HelveticaBold);
  const t = safeText(text);
  for (const i of parsePages(spec, doc.getPageCount())) {
    const page = doc.getPage(i);
    const f = visualFrame(page);
    const tw = font.widthOfTextAtSize(t, size);
    const a = position === 'Center' || position === 'Tiled' ? Number(angle) : 0;
    const rad = (a * Math.PI) / 180;
    const cy0 = size * 0.35;                    // text centre above the baseline
    const centres = [];                         // visual, y measured from the bottom
    if (position === 'Tiled') {
      const stepX = tw + size * 2, stepY = size * 4;
      for (let y = stepY / 2, row = 0; y < f.vh + stepY; y += stepY, row++) {
        for (let x = (row % 2 ? stepX / 2 : 0); x < f.vw + stepX; x += stepX) centres.push([x, y]);
      }
    } else if (position === 'Center') {
      centres.push([f.vw / 2, f.vh / 2]);
    } else {
      const [x, yb] = anchor(position.toLowerCase(), f.vw, f.vh, tw, size);
      centres.push([x + tw / 2, yb + cy0]);
    }
    for (const [cx, cyb] of centres) {
      const ox = cx - (Math.cos(rad) * tw / 2 - Math.sin(rad) * cy0);
      const oy = cyb - (Math.sin(rad) * tw / 2 + Math.cos(rad) * cy0);
      const p = f.toPdf(ox, f.vh - oy);
      page.drawText(t, { x: p.x, y: p.y, size: Number(size), font, color: hexRgb(color), opacity: Number(opacity), rotate: degrees(f.rot + a) });
    }
  }
  return save(doc);
}

export async function pageNumbers(bytes, { format = '{n}', position = 'Bottom center', start = 1, size = 11, spec = 'all' } = {}) {
  const doc = await load(bytes);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const idx = parsePages(spec, doc.getPageCount());
  idx.forEach((i, k) => {
    const page = doc.getPage(i);
    const f = visualFrame(page);
    const t = safeText(format.replace('{n}', String(Number(start) + k)).replace('{total}', String(idx.length + Number(start) - 1)));
    const tw = font.widthOfTextAtSize(t, size);
    const [x, yb] = anchor(position.toLowerCase(), f.vw, f.vh, tw, size, 26);
    const p = f.toPdf(x, f.vh - yb);
    page.drawText(t, { x: p.x, y: p.y, size: Number(size), font, color: rgb(0.15, 0.15, 0.15), rotate: f.rotate });
  });
  return save(doc);
}

export async function crop(bytes, { top = 10, bottom = 10, left = 10, right = 10, spec = 'all' } = {}) {
  const doc = await load(bytes);
  for (const i of parsePages(spec, doc.getPageCount())) {
    const page = doc.getPage(i);
    const f = visualFrame(page);
    const a = f.toPdf(left * MM, f.vh - bottom * MM);
    const b = f.toPdf(f.vw - right * MM, top * MM);
    const x0 = Math.min(a.x, b.x), y0 = Math.min(a.y, b.y);
    const w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
    if (w > 10 && h > 10) page.setCropBox(x0, y0, w, h);
  }
  return save(doc);
}

/** ops in visual top-left points: {page, type: text|image|rect|highlight|whiteout|ink|line, ...} */
export async function applyEdits(bytes, ops) {
  const doc = await load(bytes);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const bold = await doc.embedFont(StandardFonts.HelveticaBold);
  const imgs = {};
  for (const op of ops) {
    const page = doc.getPage(op.page);
    const f = visualFrame(page);
    const rot = f.rotate;
    const color = hexRgb(op.color || '#000000');
    if (op.type === 'text') {
      const size = Number(op.size || 14);
      String(op.text || '').split('\n').forEach((line, k) => {
        const p = f.toPdf(op.x, op.y + size * (k + 1) - size * 0.2);
        page.drawText(safeText(line), { x: p.x, y: p.y, size, font: op.bold ? bold : font, color, rotate: rot });
      });
    } else if (op.type === 'image') {
      const key = op.key || op.dataUrl;
      if (!imgs[key]) {
        const b = op.bytes || dataUrlBytes(op.dataUrl);
        imgs[key] = (b[0] === 0x89) ? await doc.embedPng(b) : await doc.embedJpg(b);
      }
      const p = f.toPdf(op.x, op.y + op.h);
      page.drawImage(imgs[key], { x: p.x, y: p.y, width: op.w, height: op.h, rotate: rot });
    } else if (['rect', 'highlight', 'whiteout', 'redactbox'].includes(op.type)) {
      const p = f.toPdf(op.x, op.y + op.h);
      const o = { x: p.x, y: p.y, width: op.w, height: op.h, rotate: rot };
      if (op.type === 'highlight') page.drawRectangle({ ...o, color: hexRgb(op.color || '#FFE14D'), opacity: 0.4 });
      else if (op.type === 'whiteout') page.drawRectangle({ ...o, color: rgb(1, 1, 1) });
      else page.drawRectangle({ ...o, borderColor: color, borderWidth: Number(op.width || 2), color: op.fill ? hexRgb(op.fill) : undefined, opacity: op.fill ? 0.5 : undefined });
    } else if (op.type === 'ink' || op.type === 'line') {
      const strokes = op.type === 'line' ? [[[op.x1, op.y1], [op.x2, op.y2]]] : op.points;
      for (const s of strokes) {
        for (let k = 1; k < s.length; k++) {
          const a = f.toPdf(s[k - 1][0], s[k - 1][1]);
          const b = f.toPdf(s[k][0], s[k][1]);
          page.drawLine({ start: a, end: b, thickness: Number(op.width || 2), color, lineCap: 1 });
        }
      }
    }
  }
  return save(doc);
}

export function dataUrlBytes(u) {
  const b = atob(u.split(',')[1]);
  const a = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) a[i] = b.charCodeAt(i);
  return a;
}

/** True removal: pages with marks become images with black boxes burned in (+ invisible text for the rest). */
export async function redact(bytes, marks, onProgress) {
  const src = await openPdf(bytes);
  const doc = await load(bytes);
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const pages = Object.keys(marks).map(Number).filter((i) => marks[i] && marks[i].length).sort((a, b) => a - b);
  for (let k = 0; k < pages.length; k++) {
    const i = pages[k];
    onProgress && onProgress(k / pages.length, `Redacting page ${i + 1}`);
    const scale = 200 / 72;
    const c = await renderPage(src, i, scale);
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#000';
    for (const r of marks[i]) ctx.fillRect(r.x * scale - 1, r.y * scale - 1, r.w * scale + 2, r.h * scale + 2);
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.9));
    const img = await doc.embedJpg(new Uint8Array(await blob.arrayBuffer()));
    const tb = await textBoxes(src, i);
    const W = tb.width, H = tb.height;
    const np = doc.insertPage(i, [W, H]);
    doc.removePage(i + 1);
    np.drawImage(img, { x: 0, y: 0, width: W, height: H });
    const hit = (t) => marks[i].some((r) => t.x < r.x + r.w && r.x < t.x + t.w && t.y < r.y + r.h && r.y < t.y + t.h);
    addInvisibleText(np, font, tb.items.flatMap(splitWords).filter((t) => !hit(t)).map((t) => ({ ...t, str: safeText(t.str) })));
    c.width = c.height = 0;
  }
  doc.setTitle(''); doc.setAuthor(''); doc.setSubject(''); doc.setKeywords([]); doc.setCreator('RushSuite'); doc.setProducer('RushSuite');
  return save(doc);
}

export async function findTextMarks(bytes, terms, patterns, ignoreCase = true) {
  const src = await openPdf(bytes);
  const marks = {};
  const flags = ignoreCase ? 'gi' : 'g';
  const res = [...terms.filter(Boolean).map((t) => new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), flags)), ...patterns.map((p) => new RegExp(p, flags))];
  for (let i = 0; i < src.numPages; i++) {
    const tb = await textBoxes(src, i);
    for (const it of tb.items) {
      for (const re of res) {
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(it.str))) {
          if (!m[0]) { re.lastIndex++; continue; }
          const a = charOffset(it.str, m.index), b = charOffset(it.str, m.index + m[0].length);
          (marks[i] = marks[i] || []).push({ x: it.x + it.w * a - 1, y: it.y, w: it.w * (b - a) + 2, h: it.h });
        }
      }
    }
  }
  return marks;
}

export const PRESETS = {
  'Email addresses': '[\\w.+-]+@[\\w-]+(?:\\.[\\w-]+)+',
  'Phone numbers': '\\+?\\d[\\d\\s().-]{7,}\\d',
  'Long numbers (IDs, accounts)': '\\d[\\d -]{6,}\\d',
  Dates: '\\b\\d{1,2}[/.-]\\d{1,2}[/.-]\\d{2,4}\\b',
};

// ------------------------------------------------------------------ security
export async function protect(bytes, { password, owner, allowPrint = true, allowCopy = true, allowEdit = false }) {
  if (!password) throw new Error('Type a password.');
  const doc = await load(bytes);
  if (typeof doc.encrypt !== 'function') throw new Error('Password protection needs the full app build.');
  await doc.encrypt({
    userPassword: password,
    ownerPassword: owner || `${password}-${Math.random().toString(36).slice(2)}`,
    permissions: {
      printing: allowPrint ? 'highResolution' : false, copying: allowCopy, modifying: allowEdit,
      annotating: allowEdit, fillingForms: true, contentAccessibility: true, documentAssembly: allowEdit,
    },
  });
  return doc.save({ useObjectStreams: false });
}

export async function unlock(bytes, password, onProgress) {
  try {
    const doc = await PDFDocument.load(bytes, { password });
    if (doc.isEncrypted && typeof doc.encrypt === 'function' && !password) throw new Error('needs password');
    const out = await PDFDocument.create();
    (await out.copyPages(doc, doc.getPageIndices())).forEach((p) => out.addPage(p));
    return { bytes: await save(out), exact: true };
  } catch {
    // Fallback: render every page with PDF.js (which can decrypt) and keep the text searchable.
    const src = await openPdf(bytes, password);
    const out = await PDFDocument.create();
    const font = await out.embedFont(StandardFonts.Helvetica);
    for (let i = 0; i < src.numPages; i++) {
      onProgress && onProgress(i / src.numPages, `Page ${i + 1}`);
      const c = await renderPage(src, i, 2);
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.88));
      const img = await out.embedJpg(new Uint8Array(await blob.arrayBuffer()));
      const tb = await textBoxes(src, i);
      const page = out.addPage([tb.width, tb.height]);
      page.drawImage(img, { x: 0, y: 0, width: tb.width, height: tb.height });
      addInvisibleText(page, font, tb.items.map((t) => ({ ...t, str: safeText(t.str) })));
    }
    return { bytes: await save(out), exact: false };
  }
}

// ------------------------------------------------------------------ forms
export async function listFields(bytes) {
  const doc = await load(bytes);
  const form = doc.getForm();
  return form.getFields().map((f) => {
    const type = f.constructor.name.replace('PDF', '').replace('Field', '').toLowerCase();
    let value = '', options = [];
    try {
      if (type === 'textfield' || type === 'text') value = f.getText() || '';
      else if (type === 'checkbox') value = f.isChecked();
      else if (type === 'dropdown' || type === 'optionlist') { options = f.getOptions(); value = (f.getSelected() || [])[0] || ''; }
      else if (type === 'radiogroup') { options = f.getOptions(); value = f.getSelected() || ''; }
    } catch { /* odd field */ }
    return { name: f.getName(), type, value, options };
  });
}

export async function fillFields(bytes, values, flatten = false) {
  const doc = await load(bytes);
  const form = doc.getForm();
  for (const [name, v] of Object.entries(values)) {
    let f;
    try { f = form.getField(name); } catch { continue; }
    const type = f.constructor.name;
    try {
      if (type === 'PDFTextField') f.setText(String(v ?? ''));
      else if (type === 'PDFCheckBox') (v ? f.check() : f.uncheck());
      else if (type === 'PDFDropdown' || type === 'PDFOptionList') { if (v) f.select(String(v)); }
      else if (type === 'PDFRadioGroup') { if (v) f.select(String(v)); }
    } catch { /* value not allowed */ }
  }
  if (flatten) form.flatten();
  return save(doc);
}

export async function flatten(bytes) {
  const doc = await load(bytes);
  try { doc.getForm().flatten(); } catch { /* no form */ }
  return save(doc);
}
