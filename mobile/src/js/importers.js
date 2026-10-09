// Turn files, links, pasted text and photos into readable text.
import JSZip from 'jszip';
import { openPdf, allText } from './pdfview.js';

export const READABLE = '.pdf,.txt,.md,.docx,.epub,.html,.htm,text/plain,application/pdf';

export async function fileToText(file, onProgress) {
  const name = file.name || 'document';
  const ext = (name.match(/\.([^.]+)$/) || [])[1]?.toLowerCase() || '';
  const title = name.replace(/\.[^.]+$/, '');
  if (ext === 'pdf' || file.type === 'application/pdf') {
    const doc = await openPdf(new Uint8Array(await file.arrayBuffer()));
    const pages = await allText(doc, onProgress);
    const text = pages.join('\n\n');
    if (text.replace(/\s/g, '').length < 20) {
      const e = new Error('This PDF has no text layer (it is a scan). Use OCR / Scan in PDF tools first.');
      e.scanned = true;
      throw e;
    }
    return { title, text, kind: 'pdf' };
  }
  if (ext === 'docx') return { title, text: await docxText(await file.arrayBuffer()), kind: 'doc' };
  if (ext === 'epub') return { title, ...(await epubText(await file.arrayBuffer())), kind: 'book' };
  if (ext === 'html' || ext === 'htm') return { title, text: htmlToText(await file.text()).text, kind: 'web' };
  return { title, text: await file.text(), kind: 'text' };
}

export async function docxText(buf) {
  const zip = await JSZip.loadAsync(buf);
  const xml = await zip.file('word/document.xml')?.async('string');
  if (!xml) throw new Error('Not a Word document');
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
  const paras = [...doc.getElementsByTagNameNS(W, 'p')].map((p) =>
    [...p.getElementsByTagNameNS(W, 't')].map((t) => t.textContent).join(''));
  return paras.filter((p) => p.trim()).join('\n');
}

export async function epubText(buf) {
  const zip = await JSZip.loadAsync(buf);
  const container = await zip.file('META-INF/container.xml').async('string');
  const opfPath = container.match(/full-path="([^"]+)"/)[1];
  const base = opfPath.includes('/') ? opfPath.slice(0, opfPath.lastIndexOf('/') + 1) : '';
  const opf = new DOMParser().parseFromString(await zip.file(opfPath).async('string'), 'application/xml');
  const title = opf.getElementsByTagName('dc:title')[0]?.textContent || '';
  const manifest = {};
  for (const it of opf.getElementsByTagName('item')) manifest[it.getAttribute('id')] = it.getAttribute('href');
  const parts = [];
  for (const ref of opf.getElementsByTagName('itemref')) {
    const href = manifest[ref.getAttribute('idref')];
    const f = href && zip.file(decodeURIComponent(base + href));
    if (f) parts.push(htmlToText(await f.async('string')).text);
  }
  return { text: parts.join('\n\n'), ...(title ? { title } : {}) };
}

/** Main readable text of a web page (article, or the biggest cluster of paragraphs). */
export function htmlToText(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script,style,noscript,nav,header,footer,aside,form,iframe,svg,button').forEach((n) => n.remove());
  const title = doc.querySelector('meta[property="og:title"]')?.content || doc.title || '';
  let root = doc.querySelector('article') || doc.querySelector('main') || doc.body;
  if (root) {
    let best = null, bestLen = 0;
    root.querySelectorAll('div,section,article').forEach((d) => {
      const len = [...d.querySelectorAll(':scope > p')].reduce((a, p) => a + p.textContent.length, 0);
      if (len > bestLen) { best = d; bestLen = len; }
    });
    if (best && bestLen > 400) root = best;
  }
  const blocks = root ? [...root.querySelectorAll('h1,h2,h3,h4,p,li,blockquote,pre')].map((n) => n.textContent.replace(/\s+/g, ' ').trim()).filter((t) => t.length > 1) : [];
  const text = blocks.length ? blocks.join('\n') : (root?.textContent || '').replace(/\s+\n/g, '\n');
  return { title: title.trim(), text };
}

export async function urlToText(url) {
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`;
  let res;
  try { res = await fetch(url, { headers: { 'user-agent': 'Mozilla/5.0 (Linux; Android 14) RushSuite' } }); } catch {
    throw new Error("Couldn't open that link - check the address and your internet.");
  }
  if (!res.ok) throw new Error(`The site answered ${res.status}.`);
  const type = res.headers.get('content-type') || '';
  if (type.includes('pdf')) {
    const doc = await openPdf(new Uint8Array(await res.arrayBuffer()));
    return { title: url.split('/').pop() || 'PDF', text: (await allText(doc)).join('\n\n'), kind: 'pdf' };
  }
  const r = htmlToText(await res.text());
  return { title: r.title || new URL(url).hostname, text: r.text, kind: 'web' };
}
