// Small DOM toolkit: elements, icons, toasts, sheets, progress, file picking, saving results.
import { saveFile, shareFile } from './native.js';

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (v === true) n.setAttribute(k, '');
    else n.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

// 24x24 line icons
const P = {
  merge: '<path d="M8 3v5a4 4 0 004 4 4 4 0 014 4v5"/><path d="M16 3v5a4 4 0 01-4 4"/><path d="M13 18l3 3 3-3"/>',
  split: '<path d="M12 21v-7a4 4 0 00-4-4H4"/><path d="M12 14a4 4 0 014-4h4"/><path d="M7 7l-3 3 3 3"/><path d="M17 7l3 3-3 3"/>',
  rotate: '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
  extract: '<rect x="4" y="3" width="11" height="14" rx="2"/><path d="M13 13h8M18 10l3 3-3 3"/>',
  organize: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="9" rx="1.5"/><rect x="3" y="15" width="7" height="6" rx="1.5"/><rect x="14" y="15" width="7" height="6" rx="1.5"/>',
  compress: '<path d="M4 14h6v6"/><path d="M20 10h-6V4"/><path d="M14 10l7-7"/><path d="M3 21l7-7"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>',
  word: '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><path d="M8.5 11l1.5 6 2-4.5 2 4.5 1.5-6"/>',
  text: '<path d="M5 6h14M12 6v13M9 19h6"/>',
  watermark: '<path d="M12 3s6 6.5 6 11a6 6 0 01-12 0c0-4.5 6-11 6-11z"/>',
  numbers: '<path d="M6 2h9l5 5v15H6z"/><path d="M10 13l2-1.5V18"/><path d="M10 18h4"/>',
  crop: '<path d="M6 2v14a2 2 0 002 2h14"/><path d="M2 6h14a2 2 0 012 2v14"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
  form: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 8h10"/><rect x="7" y="12" width="10" height="3" rx="1"/>',
  sign: '<path d="M3 17c3 0 4-9 6-9s0 8 2 8 2-4 4-4 1 3 3 3 2-1 3-1"/><path d="M3 21h18"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/>',
  unlock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 017.5-2"/>',
  redact: '<path d="M6 2h9l5 5v15H6z"/><rect x="8" y="11" width="9" height="3" fill="currentColor"/>',
  compare: '<rect x="2" y="4" width="8" height="16" rx="1.5"/><rect x="14" y="4" width="8" height="16" rx="1.5"/>',
  ai: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  translate: '<path d="M4 5h9"/><path d="M8.5 3v2c0 4-2 7-5 8.5"/><path d="M6 9c1.3 2 3.3 3.6 6 4.5"/><path d="M13 21l4-9 4 9"/><path d="M14.5 18h5"/>',
  ocr: '<path d="M3 8V5a2 2 0 012-2h3"/><path d="M16 3h3a2 2 0 012 2v3"/><path d="M21 16v3a2 2 0 01-2 2h-3"/><path d="M8 21H5a2 2 0 01-2-2v-3"/><path d="M8 16l2.5-8h1L14 16"/><path d="M9 13h4"/>',
  scan: '<path d="M4 7h3l2-3h6l2 3h3a1 1 0 011 1v11a1 1 0 01-1 1H4a1 1 0 01-1-1V8a1 1 0 011-1z"/><circle cx="12" cy="13" r="4"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
  repair: '<path d="M14.7 6.3a4 4 0 00-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 005.2-5.4l-2.6 2.6-2.4-.4-.4-2.4z"/>',
  pdf: '<path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/>',
  book: '<path d="M2 5c3-1.5 7-1.5 10 1v14c-3-2.5-7-2.5-10-1z"/><path d="M22 5c-3-1.5-7-1.5-10 1v14c3-2.5 7-2.5 10-1z"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  play: '<path d="M7 4l13 8-13 8z" fill="currentColor"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
  prev: '<path d="M19 5L9 12l10 7z" fill="currentColor"/><path d="M5 5v14"/>',
  next: '<path d="M5 5l10 7-10 7z" fill="currentColor"/><path d="M19 5v14"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/>',
  link: '<path d="M10 14a5 5 0 007 0l3-3a5 5 0 00-7-7l-1 1"/><path d="M14 10a5 5 0 00-7 0l-3 3a5 5 0 007 7l1-1"/>',
  clipboard: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4V3h6v1"/>',
  chat: '<path d="M21 12a8 8 0 01-11.6 7.1L4 20l1-4.6A8 8 0 1121 12z"/>',
  volume: '<path d="M4 9v6h4l5 4V5L8 9z"/><path d="M16 9a4 4 0 010 6"/><path d="M19 6a8 8 0 010 12"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  up: '<path d="M6 15l6-6 6 6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  left: '<path d="M15 6l-6 6 6 6"/>',
  right: '<path d="M9 6l6 6-6 6"/>',
  quiz: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 015 .5c0 1.7-2.5 2-2.5 3.5"/><path d="M12 17h.01"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
};

export function icon(name, size = 22, color = 'currentColor') {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('width', size); s.setAttribute('height', size);
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', color);
  s.setAttribute('stroke-width', '1.8'); s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.innerHTML = P[name] || P.pdf;
  s.classList.add('ic');
  return s;
}

export function badge(name, color, size = 44) {
  return el('div', { class: 'badge', style: { width: `${size}px`, height: `${size}px`, color, background: hexA(color, 0.16) } },
    icon(name, Math.round(size * 0.52), color));
}

function hexA(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

export function button(text, { icon: ic = null, kind = '', onclick = null, title = null } = {}) {
  return el('button', { class: `btn ${kind}`, onclick, title }, ic ? icon(ic, 18) : null, text ? el('span', {}, text) : null);
}

// ------------------------------------------------------------------ toast / progress / sheets
let toastTimer = null;
export function toast(msg, kind = 'ok') {
  const t = $('#toast');
  t.textContent = msg;
  t.className = `show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ''; }, 3200);
}

export const progress = {
  show(msg = 'Working…', frac = null) {
    const p = $('#progress');
    p.classList.add('show');
    $('#progress .msg').textContent = msg;
    const bar = $('#progress .bar > i');
    if (frac === null) { bar.style.width = '35%'; bar.parentElement.classList.add('indet'); }
    else { bar.parentElement.classList.remove('indet'); bar.style.width = `${Math.round(Math.max(0, Math.min(1, frac)) * 100)}%`; }
  },
  hide() { $('#progress').classList.remove('show'); },
};

export function sheet(title, body, actions = []) {
  return new Promise((resolve) => {
    const root = $('#modal');
    const close = (v) => { root.classList.remove('show'); root.innerHTML = ''; resolve(v); };
    const box = el('div', { class: 'sheet' },
      el('div', { class: 'sheet-head' }, el('h3', {}, title), el('button', { class: 'icon-btn', onclick: () => close(null) }, icon('x'))),
      el('div', { class: 'sheet-body' }, body),
      actions.length ? el('div', { class: 'sheet-actions' }, actions.map((a) => button(a.text, {
        kind: a.kind || '', icon: a.icon, onclick: async () => { const v = a.value ? await a.value() : a.text; if (v !== false) close(v); },
      }))) : null);
    root.innerHTML = '';
    root.append(el('div', { class: 'scrim', onclick: () => close(null) }), box);
    root.classList.add('show');
  });
}

export async function ask(title, label, value = '', { type = 'text', multiline = false } = {}) {
  const input = multiline ? el('textarea', { rows: 6 }, value) : el('input', { type, value });
  setTimeout(() => input.focus(), 50);
  const r = await sheet(title, el('label', { class: 'field' }, el('span', {}, label), input),
    [{ text: 'Cancel', kind: 'ghost', value: () => null }, { text: 'OK', kind: 'primary', value: () => input.value }]);
  return r === null ? null : r;
}

export function confirmBox(title, msg) {
  return sheet(title, el('p', { class: 'muted' }, msg),
    [{ text: 'Cancel', kind: 'ghost', value: () => null }, { text: 'OK', kind: 'primary', value: () => true }])
    .then((r) => r === true);
}

export function errorBox(e) {
  const msg = (e && e.message) || String(e);
  console.error(e);
  return sheet('Something went wrong', el('p', { class: 'muted' }, msg), [{ text: 'OK', kind: 'primary' }]);
}

// ------------------------------------------------------------------ files
export function pickFiles({ accept = '', multiple = false, capture = null } = {}) {
  return new Promise((resolve) => {
    const inp = el('input', { type: 'file', accept, multiple: multiple || null, capture: capture || null, style: { display: 'none' } });
    inp.addEventListener('change', () => { resolve([...inp.files]); inp.remove(); });
    inp.addEventListener('cancel', () => { resolve([]); inp.remove(); });
    document.body.append(inp);
    inp.click();
  });
}

export async function readBytes(file) {
  return new Uint8Array(await file.arrayBuffer());
}

export function humanSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function stem(name) { return name.replace(/\.[^.]+$/, ''); }

/** Save outputs and show a results sheet with Share buttons and follow-up actions. */
export async function deliver(outputs, { note = '', next = [] } = {}) {
  const saved = [];
  for (const o of outputs) {
    const r = await saveFile(o.name, o.bytes, o.mime);
    saved.push({ ...o, ...r });
  }
  const list = el('div', { class: 'results' }, saved.map((s) => el('div', { class: 'result-row' },
    icon(s.name.endsWith('.pdf') ? 'pdf' : 'text', 20),
    el('div', { class: 'grow' }, el('div', { class: 'strong' }, s.name), el('div', { class: 'faint' }, `${humanSize(s.bytes.length)} · ${s.where}`)),
    el('button', { class: 'icon-btn', onclick: () => shareFile(s.uri, s.name) }, icon('share', 20)))));
  const body = el('div', {}, note ? el('p', { class: 'muted' }, note) : null, list,
    next.length ? el('div', { class: 'next-row' }, next.map((n) => button(n.text, {
      icon: n.icon, kind: 'ghost', onclick: () => { $('#modal').classList.remove('show'); n.run(saved); },
    }))) : null);
  await sheet(saved.length === 1 ? 'Done!' : `Done - ${saved.length} files`, body, [{ text: 'Close', kind: 'primary' }]);
  return saved;
}
