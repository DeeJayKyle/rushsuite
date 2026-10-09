// PDF screens: tool grid, generic tool screen, and the interactive tools (organize, edit/sign, redact, forms, compare).
import { TOOLS, CATS } from './tools.js';
import * as C from './pdfcore.js';
import { openPdf, renderFit, renderPage, pageText, isPasswordError } from './pdfview.js';
import { aiReady } from './ai.js';
import { el, icon, badge, button, toast, progress, sheet, ask, errorBox, pickFiles, readBytes, humanSize, stem, deliver } from './ui.js';

let nav = null;   // set by app.js: {push(title, view), pop(), listenText(title, text), listenFile(file)}
export function bindNav(n) { nav = n; }

// ================================================================== tool grid
export function pdfHome() {
  let cat = 'All', q = '';
  const grid = el('div', { class: 'tool-grid' });
  const draw = () => {
    grid.innerHTML = '';
    for (const t of TOOLS) {
      if (cat !== 'All' && t.cat !== cat) continue;
      if (q && !(`${t.name} ${t.desc} ${t.cat}`.toLowerCase().includes(q))) continue;
      grid.append(el('button', { class: 'tile', onclick: () => openTool(t) }, badge(t.icon, t.color, 42),
        el('div', { class: 'tile-name' }, t.name), el('div', { class: 'tile-desc' }, t.desc)));
    }
    if (!grid.children.length) grid.append(el('p', { class: 'muted center' }, 'No tool matches your search.'));
  };
  const chips = el('div', { class: 'chips' }, ['All', ...CATS].map((c) => el('button', {
    class: `chip ${c === cat ? 'on' : ''}`, onclick: (e) => { cat = c; chips.querySelectorAll('.chip').forEach((b) => b.classList.remove('on')); e.currentTarget.classList.add('on'); draw(); },
  }, c)));
  const search = el('input', { class: 'search', placeholder: 'Search PDF tools…', oninput: (e) => { q = e.target.value.toLowerCase().trim(); draw(); } });
  draw();
  return el('div', { class: 'page' },
    el('div', { class: 'hero' }, el('h1', {}, 'Every PDF tool'), el('p', { class: 'muted' }, 'Merge, split, compress, convert, sign, OCR and more - right on your phone.')),
    search, chips, grid);
}

export function openTool(t, files = null) {
  const pages = { organize: organizePage, annotate: (tt, f) => annotatePage(tt, f, 'edit'), sign: (tt, f) => annotatePage(tt, f, 'sign'),
    redact: redactPage, forms: formsPage, compare: comparePage };
  const view = t.page ? pages[t.page](t, files) : toolPage(t, files);
  nav.push(t.name, view);
}

// ================================================================== generic tool screen
function paramControl(p, values, onChange) {
  const set = (v) => { values[p.key] = v; onChange(); };
  let input;
  if (p.kind === 'choice') {
    input = el('select', { onchange: (e) => set(e.target.value) }, p.options.map((o) => el('option', { value: o, selected: values[p.key] === o }, o)));
  } else if (p.kind === 'bool') {
    input = el('input', { type: 'checkbox', checked: !!values[p.key], onchange: (e) => set(e.target.checked) });
    return el('label', { class: 'check' }, input, el('span', {}, p.label));
  } else if (p.kind === 'color') {
    input = el('input', { type: 'color', value: values[p.key], oninput: (e) => set(e.target.value) });
  } else if (p.kind === 'number') {
    input = el('input', { type: 'number', inputmode: 'decimal', step: 'any', value: values[p.key], oninput: (e) => set(Number(e.target.value)) });
  } else {
    input = el('input', { type: p.kind === 'password' ? 'password' : 'text', value: values[p.key] ?? '', placeholder: p.kind === 'pages' ? 'all  (e.g. 1-3, 5, 8-)' : '', oninput: (e) => set(e.target.value) });
  }
  return el('label', { class: 'field' }, el('span', {}, p.label), input);
}

function toolPage(t, preset) {
  const values = Object.fromEntries((t.params || []).map((p) => [p.key, p.def]));
  let files = [];
  const list = el('div', { class: 'file-list' });
  const form = el('div', { class: 'form' });
  const runBtn = button(t.name, { icon: t.icon, kind: 'primary wide', onclick: () => run() });
  const drawForm = () => {
    form.innerHTML = '';
    for (const p of t.params || []) {
      if (p.show && values[p.show[0]] !== p.show[1]) continue;
      form.append(paramControl(p, values, drawForm));
    }
  };
  const drawFiles = () => {
    list.innerHTML = '';
    files.forEach((f, i) => list.append(el('div', { class: 'file-row' },
      icon(f.type.startsWith('image/') ? 'image' : 'pdf', 20),
      el('div', { class: 'grow' }, el('div', { class: 'strong ellipsis' }, f.name), el('div', { class: 'faint' }, humanSize(f.size))),
      t.order && files.length > 1 ? el('button', { class: 'icon-btn', disabled: i === 0, onclick: () => { [files[i - 1], files[i]] = [files[i], files[i - 1]]; drawFiles(); } }, icon('up', 18)) : null,
      t.order && files.length > 1 ? el('button', { class: 'icon-btn', disabled: i === files.length - 1, onclick: () => { [files[i + 1], files[i]] = [files[i], files[i + 1]]; drawFiles(); } }, icon('down', 18)) : null,
      el('button', { class: 'icon-btn', onclick: () => { files.splice(i, 1); drawFiles(); } }, icon('x', 18)))));
    const need = t.min || 1;
    runBtn.disabled = files.length < need;
    pickRow.querySelector('.pick-main span').textContent = files.length ? 'Add more' : (t.multiple ? 'Choose files' : 'Choose a file');
  };
  const add = async (capture) => {
    const fs = await pickFiles({ accept: t.accept, multiple: !!t.multiple, capture });
    if (!fs.length) return;
    files = t.multiple ? files.concat(fs) : fs.slice(0, 1);
    drawFiles();
  };
  const pickRow = el('div', { class: 'pick-row' },
    el('button', { class: 'btn primary pick-main', onclick: () => add(null) }, icon('plus', 18), el('span', {}, 'Choose')),
    t.camera ? button('Camera', { icon: 'scan', onclick: () => add('environment') }) : null);

  async function run() {
    if (t.ai && !aiReady()) { await sheet('AI key needed', el('p', { class: 'muted' }, 'Add a free Google Gemini or Groq key in Settings → AI first.'), [{ text: 'OK', kind: 'primary' }]); return; }
    try {
      progress.show(`${t.name}…`, 0);
      const items = [];
      for (const f of files) items.push({ name: f.name, type: f.type || '', bytes: await readBytes(f) });
      const r = await t.run({ files, items, p: { ...values }, progress: (fr, msg) => progress.show(msg || `${t.name}…`, fr) });
      progress.hide();
      const next = [];
      if (r.text && r.text.trim()) next.push({ text: 'Listen', icon: 'volume', run: () => nav.listenText(stem(files[0]?.name || t.name), r.text) });
      const pdfs = r.outputs.filter((o) => o.name.endsWith('.pdf'));
      if (pdfs.length === 1) next.push({ text: 'Use in another tool', icon: 'grid', run: () => continueWith(pdfs[0]) });
      await deliver(r.outputs, { note: r.note || '', next });
    } catch (e) {
      progress.hide();
      errorBox(e);
    }
  }
  if (preset && preset.length) { files = preset; }
  drawForm();
  setTimeout(drawFiles, 0);
  return el('div', { class: 'page' },
    el('div', { class: 'tool-head' }, badge(t.icon, t.color, 52), el('div', {}, el('h2', {}, t.name), el('p', { class: 'muted' }, t.desc))),
    pickRow, list, (t.params || []).length ? el('div', { class: 'card' }, el('h3', {}, 'Options'), form) : null,
    el('div', { class: 'run-bar' }, runBtn));
}

async function continueWith(out) {
  const f = new File([out.bytes], out.name, { type: 'application/pdf' });
  const choices = TOOLS.filter((t) => t.accept.includes('pdf'));
  const body = el('div', { class: 'list' }, choices.map((t) => el('button', { class: 'list-row', onclick: () => { document.querySelector('#modal').classList.remove('show'); openTool(t, [f]); } },
    badge(t.icon, t.color, 34), el('span', {}, t.name))));
  await sheet('Continue with…', body);
}

// ================================================================== helpers for the interactive screens
async function pickOnePdf() {
  const [f] = await pickFiles({ accept: '.pdf,application/pdf' });
  return f || null;
}

async function openWithPassword(bytes) {
  try { return { doc: await openPdf(bytes), password: undefined }; } catch (e) {
    if (!isPasswordError(e)) throw e;
    const pw = await ask('Password needed', 'This PDF is protected. Password:', '', { type: 'password' });
    if (pw === null) throw new Error('Cancelled');
    return { doc: await openPdf(bytes, pw), password: pw };
  }
}

function startScreen(t, onFile) {
  const box = el('div', { class: 'page' },
    el('div', { class: 'tool-head' }, badge(t.icon, t.color, 52), el('div', {}, el('h2', {}, t.name), el('p', { class: 'muted' }, t.desc))),
    button('Choose a PDF', { icon: 'plus', kind: 'primary wide', onclick: async () => { const f = await pickOnePdf(); if (f) onFile(f); } }));
  return box;
}

// ================================================================== Organize
function organizePage(t, preset) {
  const root = el('div', { class: 'page' });
  const sources = {};
  let refs = [];          // {src, page, rot, thumb}
  let sel = new Set();
  const grid = el('div', { class: 'thumb-grid' });
  const count = el('span', { class: 'muted' });

  const addPdf = async (f) => {
    const bytes = await readBytes(f);
    const key = `${f.name}#${Object.keys(sources).length}`;
    sources[key] = bytes;
    progress.show('Loading pages…', 0);
    try {
      const doc = await openPdf(bytes);
      for (let i = 0; i < doc.numPages; i++) {
        progress.show(`Page ${i + 1} of ${doc.numPages}`, i / doc.numPages);
        const c = await renderPage(doc, i, 0.35);
        refs.push({ src: key, page: i, rot: 0, thumb: c.toDataURL('image/jpeg', 0.7), label: `${stem(f.name).slice(0, 12)} p${i + 1}` });
      }
    } catch (e) { errorBox(e); }
    progress.hide();
    draw();
  };
  const draw = () => {
    grid.innerHTML = '';
    refs.forEach((r, i) => {
      const img = r.thumb ? el('img', { src: r.thumb, style: { transform: `rotate(${r.rot}deg)` } }) : el('div', { class: 'blank' }, 'blank');
      grid.append(el('button', { class: `thumb ${sel.has(i) ? 'sel' : ''}`, onclick: () => { sel.has(i) ? sel.delete(i) : sel.add(i); draw(); } },
        el('div', { class: 'thumb-img' }, img), el('div', { class: 'thumb-label' }, `${i + 1} · ${r.label}`)));
    });
    count.textContent = `${refs.length} pages${sel.size ? ` · ${sel.size} selected` : ''}`;
  };
  const selected = () => (sel.size ? [...sel].sort((a, b) => a - b) : []);
  const act = {
    rotate: (d) => { (selected().length ? selected() : refs.map((_r, i) => i)).forEach((i) => { refs[i].rot = (refs[i].rot + d + 360) % 360; }); draw(); },
    remove: () => { if (!sel.size) return toast('Tap pages to select them first', 'info'); refs = refs.filter((_r, i) => !sel.has(i)); sel = new Set(); draw(); },
    move: (d) => {
      const s = selected();
      if (!s.length) return toast('Select pages to move', 'info');
      if ((d < 0 && s[0] === 0) || (d > 0 && s[s.length - 1] === refs.length - 1)) return;
      for (const i of (d < 0 ? s : [...s].reverse())) [refs[i], refs[i + d]] = [refs[i + d], refs[i]];
      sel = new Set(s.map((i) => i + d)); draw();
    },
    dup: () => { const s = selected(); for (const i of s.reverse()) refs.splice(i + 1, 0, { ...refs[i] }); sel = new Set(); draw(); },
    blank: () => { const s = selected(); const at = s.length ? s[s.length - 1] + 1 : refs.length; refs.splice(at, 0, { src: null, page: 0, rot: 0, label: 'blank' }); sel = new Set(); draw(); },
    reverse: () => { refs.reverse(); sel = new Set(); draw(); },
  };
  const save = async () => {
    if (!refs.length) return;
    try {
      progress.show('Saving…');
      const bytes = await C.organize(refs.map((r) => ({ src: r.src, page: r.page, rot: r.rot })), sources);
      progress.hide();
      await deliver([{ name: `${stem(Object.keys(sources)[0].split('#')[0])}_organized.pdf`, bytes, mime: 'application/pdf' }]);
    } catch (e) { progress.hide(); errorBox(e); }
  };
  const bar = el('div', { class: 'toolbar' },
    button('', { icon: 'rotate', title: 'Rotate right', onclick: () => act.rotate(90) }),
    button('', { icon: 'left', title: 'Move left', onclick: () => act.move(-1) }),
    button('', { icon: 'right', title: 'Move right', onclick: () => act.move(1) }),
    button('', { icon: 'layers', title: 'Duplicate', onclick: act.dup }),
    button('', { icon: 'pdf', title: 'Blank page', onclick: act.blank }),
    button('', { icon: 'trash', title: 'Delete', onclick: act.remove }),
    button('', { icon: 'plus', title: 'Add PDF', onclick: async () => { const f = await pickOnePdf(); if (f) addPdf(f); } }));
  const start = startScreen(t, async (f) => { root.innerHTML = ''; root.append(editor); await addPdf(f); });
  const editor = el('div', {}, el('div', { class: 'row between' }, count, button('Reverse', { kind: 'ghost', onclick: act.reverse })),
    bar, el('p', { class: 'faint' }, 'Tap pages to select, then use the buttons above.'), grid,
    el('div', { class: 'run-bar' }, button('Save PDF', { icon: 'check', kind: 'primary wide', onclick: save })));
  root.append(start);
  if (preset && preset[0]) { root.innerHTML = ''; root.append(editor); addPdf(preset[0]); }
  return root;
}

// ================================================================== Edit & Sign (annotate)
function signaturePad() {
  return new Promise((resolve) => {
    const c = el('canvas', { class: 'sigpad', width: 900, height: 360 });
    const ctx = c.getContext('2d');
    let drawing = false, ink = '#0B2A8C', any = false;
    const pos = (e) => { const r = c.getBoundingClientRect(); return [(e.clientX - r.left) * (c.width / r.width), (e.clientY - r.top) * (c.height / r.height)]; };
    c.addEventListener('pointerdown', (e) => { drawing = true; any = true; c.setPointerCapture(e.pointerId); const [x, y] = pos(e); ctx.beginPath(); ctx.moveTo(x, y); });
    c.addEventListener('pointermove', (e) => { if (!drawing) return; const [x, y] = pos(e); ctx.lineTo(x, y); ctx.strokeStyle = ink; ctx.lineWidth = 6; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke(); });
    c.addEventListener('pointerup', () => { drawing = false; });
    const colors = el('div', { class: 'row' }, ['#0B2A8C', '#111111', '#B3261E'].map((col) => el('button', { class: 'swatch', style: { background: col }, onclick: () => { ink = col; } })),
      button('Clear', { kind: 'ghost', onclick: () => { ctx.clearRect(0, 0, c.width, c.height); any = false; } }));
    sheet('Draw your signature', el('div', {}, c, colors), [
      { text: 'Cancel', kind: 'ghost', value: () => null },
      { text: 'Use it', kind: 'primary', value: () => { if (!any) { toast('Draw first', 'info'); return false; } return trimCanvas(c).toDataURL('image/png'); } },
    ]).then(resolve);
  });
}

function trimCanvas(c) {
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  let x0 = c.width, y0 = c.height, x1 = 0, y1 = 0;
  for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) if (d[(y * c.width + x) * 4 + 3] > 10) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  if (x1 <= x0) return c;
  const o = document.createElement('canvas');
  o.width = x1 - x0 + 12; o.height = y1 - y0 + 12;
  o.getContext('2d').drawImage(c, x0 - 6, y0 - 6, o.width, o.height, 0, 0, o.width, o.height);
  return o;
}

function annotatePage(t, preset, mode) {
  const root = el('div', { class: 'page wide' });
  let bytes = null, doc = null, name = 'document.pdf', pageIdx = 0, scale = 1, pageW = 0, pageH = 0;
  const items = [];          // {page, type, x, y, w, h, text, size, color, dataUrl, points}
  let tool = 'move', selected = null;
  const stage = el('div', { class: 'stage' });
  const layer = el('div', { class: 'layer' });
  const pageLbl = el('span', { class: 'muted' });
  const saved = JSON.parse(localStorage.getItem('rushsuite.signatures') || '[]');

  const toolsList = mode === 'sign'
    ? [['sig', 'Signature', 'sign'], ['initials', 'Initials', 'edit'], ['date', 'Date', 'numbers'], ['text', 'Text', 'text'], ['check', '✓ Tick', 'check'], ['move', 'Move', 'grid']]
    : [['text', 'Text', 'text'], ['image', 'Image', 'image'], ['highlight', 'Highlight', 'edit'], ['whiteout', 'Whiteout', 'layers'], ['ink', 'Draw', 'sign'], ['rect', 'Box', 'organize'], ['move', 'Move', 'grid']];
  const toolBar = el('div', { class: 'toolbar scroll' }, toolsList.map(([k, label, ic]) => el('button', { class: `tbtn ${k === tool ? 'on' : ''}`, 'data-k': k, onclick: () => pick(k) }, icon(ic, 18), el('span', {}, label))));
  const colorIn = el('input', { type: 'color', value: mode === 'sign' ? '#0B2A8C' : '#D62828' });
  const sizeIn = el('input', { type: 'range', min: 8, max: 48, value: 14 });

  const pick = async (k) => {
    tool = k;
    toolBar.querySelectorAll('.tbtn').forEach((b) => b.classList.toggle('on', b.dataset.k === k));
    if (k === 'sig' || k === 'initials') {
      let url = mode === 'sign' && k === 'sig' && saved.length ? await chooseSaved() : null;
      if (url === undefined) return;
      if (!url) url = await signaturePad();
      if (!url) return;
      if (!saved.includes(url) && k === 'sig') { saved.unshift(url); localStorage.setItem('rushsuite.signatures', JSON.stringify(saved.slice(0, 4))); }
      const img = new Image();
      img.src = url;
      await img.decode();
      const w = k === 'sig' ? 150 : 70;
      addItem({ type: 'image', dataUrl: url, x: pageW / 2 - w / 2, y: pageH * 0.75, w, h: (w * img.height) / img.width });
      pick('move');
      toast('Drag it into place', 'info');
    } else if (k === 'image') {
      const [f] = await pickFiles({ accept: 'image/png,image/jpeg' });
      if (!f) return pick('move');
      const url = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(f); });
      const img = new Image(); img.src = url; await img.decode();
      addItem({ type: 'image', dataUrl: url, x: pageW * 0.3, y: pageH * 0.3, w: 160, h: (160 * img.height) / img.width });
      pick('move');
    }
  };
  const chooseSaved = () => sheet('Your signatures', el('div', { class: 'list' }, saved.map((u) => el('button', { class: 'list-row sig', onclick: () => { document.querySelector('#modal').classList.remove('show'); chosen(u); } }, el('img', { src: u })))),
    [{ text: 'Draw a new one', kind: 'primary', value: () => '' }]).then((v) => (v === null ? undefined : v === '' ? null : v));
  let chosen = () => {};

  const addItem = (it) => { it.page = pageIdx; items.push(it); selected = it; drawItems(); };

  const drawItems = () => {
    layer.innerHTML = '';
    for (const it of items.filter((x) => x.page === pageIdx)) {
      const node = el('div', { class: `item ${it === selected ? 'sel' : ''} t-${it.type}` });
      const place = () => Object.assign(node.style, { left: `${it.x * scale}px`, top: `${it.y * scale}px`, width: `${it.w * scale}px`, height: `${it.h * scale}px` });
      if (it.type === 'text') {
        node.textContent = it.text;
        Object.assign(node.style, { color: it.color, fontSize: `${it.size * scale}px`, lineHeight: `${it.size * scale}px`, fontWeight: it.bold ? '700' : '400' });
        it.w = Math.max(...it.text.split('\n').map((l) => l.length)) * it.size * 0.55 + 4; it.h = it.size * it.text.split('\n').length + 2;
        node.addEventListener('dblclick', async () => { const v = await ask('Edit text', 'Text', it.text, { multiline: true }); if (v !== null) { it.text = v; drawItems(); } });
      } else if (it.type === 'image') node.append(el('img', { src: it.dataUrl }));
      else if (it.type === 'ink') {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', `${pageW * scale}`); svg.setAttribute('height', `${pageH * scale}`);
        svg.innerHTML = it.points.map((s) => `<polyline fill="none" stroke="${it.color}" stroke-width="${(it.width || 2) * scale}" stroke-linecap="round" stroke-linejoin="round" points="${s.map((p) => `${p[0] * scale},${p[1] * scale}`).join(' ')}"/>`).join('');
        node.style.pointerEvents = 'none';
        Object.assign(node.style, { left: '0px', top: '0px' });
        node.append(svg);
        layer.append(node);
        continue;
      } else if (it.type === 'highlight') node.style.background = 'rgba(255,225,77,.45)';
      else if (it.type === 'whiteout') { node.style.background = '#fff'; node.style.outline = '1px dashed #bbb'; }
      else if (it.type === 'rect') node.style.border = `${Math.max(1, (it.width || 2) * scale)}px solid ${it.color}`;
      place();
      dragify(node, it, place);
      if (it === selected) {
        node.append(el('button', { class: 'del', onclick: (e) => { e.stopPropagation(); items.splice(items.indexOf(it), 1); selected = null; drawItems(); } }, icon('x', 14)));
        if (it.type !== 'text') {
          const h = el('div', { class: 'grip' });
          resizer(h, it, place);
          node.append(h);
        }
      }
      layer.append(node);
    }
  };

  const dragify = (node, it, place) => {
    node.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.del,.grip')) return;
      e.stopPropagation();
      if (selected !== it) { selected = it; drawItems(); return; }
      const sx = e.clientX, sy = e.clientY, ox = it.x, oy = it.y;
      node.setPointerCapture(e.pointerId);
      const mv = (ev) => { it.x = ox + (ev.clientX - sx) / scale; it.y = oy + (ev.clientY - sy) / scale; place(); };
      const up = () => { node.removeEventListener('pointermove', mv); node.removeEventListener('pointerup', up); };
      node.addEventListener('pointermove', mv); node.addEventListener('pointerup', up);
    });
  };
  const resizer = (h, it, place) => {
    h.addEventListener('pointerdown', (e) => {
      e.stopPropagation();
      const sx = e.clientX, ow = it.w, oh = it.h, ratio = it.h / it.w;
      h.setPointerCapture(e.pointerId);
      const mv = (ev) => { it.w = Math.max(10, ow + (ev.clientX - sx) / scale); it.h = it.type === 'image' ? it.w * ratio : Math.max(6, oh + (ev.clientX - sx) / scale * (oh / ow)); place(); };
      const up = () => { h.removeEventListener('pointermove', mv); h.removeEventListener('pointerup', up); };
      h.addEventListener('pointermove', mv); h.addEventListener('pointerup', up);
    });
  };

  // tap / drag on the page to create things
  layer.addEventListener('pointerdown', async (e) => {
    if (e.target !== layer) return;
    const r = layer.getBoundingClientRect();
    const x = (e.clientX - r.left) / scale, y = (e.clientY - r.top) / scale;
    selected = null;
    if (tool === 'text' || tool === 'date' || tool === 'check') {
      let text = tool === 'date' ? new Date().toLocaleDateString() : tool === 'check' ? '✓' : await ask('Add text', 'Text', '', { multiline: true });
      if (!text) return;
      if (tool === 'check') text = 'X';
      addItem({ type: 'text', text, x, y: y - Number(sizeIn.value) / 2, size: Number(sizeIn.value), color: colorIn.value, bold: tool === 'check' });
      return;
    }
    if (['highlight', 'whiteout', 'rect', 'ink'].includes(tool)) {
      layer.setPointerCapture(e.pointerId);
      const it = tool === 'ink' ? { type: 'ink', points: [[[x, y]]], color: colorIn.value, width: Math.max(1, Number(sizeIn.value) / 6) }
        : { type: tool, x, y, w: 1, h: 1, color: tool === 'highlight' ? '#FFE14D' : colorIn.value, width: 2 };
      it.page = pageIdx; items.push(it);
      const mv = (ev) => {
        const px = (ev.clientX - r.left) / scale, py = (ev.clientY - r.top) / scale;
        if (it.type === 'ink') it.points[0].push([px, py]);
        else { it.w = Math.abs(px - x); it.h = Math.abs(py - y); it.x = Math.min(px, x); it.y = Math.min(py, y); }
        drawItems();
      };
      const up = () => {
        layer.removeEventListener('pointermove', mv); layer.removeEventListener('pointerup', up);
        if (it.type !== 'ink' && (it.w < 4 || it.h < 4)) { it.w = 120; it.h = 24; it.x = x - 60; it.y = y - 12; }
        selected = it.type === 'ink' ? null : it; drawItems();
      };
      layer.addEventListener('pointermove', mv); layer.addEventListener('pointerup', up);
      return;
    }
    drawItems();
  });

  const showPage = async (i) => {
    pageIdx = Math.max(0, Math.min(doc.numPages - 1, i));
    const width = Math.min(stage.parentElement ? stage.parentElement.clientWidth : window.innerWidth - 24, 900);
    const r = await renderFit(doc, pageIdx, width);
    pageW = r.width; pageH = r.height; scale = width / pageW;
    stage.innerHTML = '';
    Object.assign(layer.style, { width: `${width}px`, height: `${pageH * scale}px` });
    stage.append(r.canvas, layer);
    pageLbl.textContent = `Page ${pageIdx + 1} / ${doc.numPages}`;
    selected = null;
    drawItems();
  };

  const save = async () => {
    const ops = items.map((it) => ({ ...it }));
    if (!ops.length) return toast(mode === 'sign' ? 'Place your signature first' : 'Add something first', 'info');
    try {
      progress.show('Saving…');
      let src = bytes;
      if (pwd) src = (await C.unlock(bytes, pwd)).bytes;
      const out = await C.applyEdits(src, ops);
      progress.hide();
      await deliver([{ name: `${stem(name)}_${mode === 'sign' ? 'signed' : 'edited'}.pdf`, bytes: out, mime: 'application/pdf' }]);
    } catch (e) { progress.hide(); errorBox(e); }
  };
  let pwd;
  const open = async (f) => {
    try {
      bytes = await readBytes(f); name = f.name;
      const r = await openWithPassword(bytes);
      doc = r.doc; pwd = r.password;
      root.innerHTML = '';
      root.append(editorUi);
      await showPage(0);
    } catch (e) { if (e.message !== 'Cancelled') errorBox(e); }
  };
  const editorUi = el('div', {},
    toolBar,
    el('div', { class: 'row' }, el('label', { class: 'mini' }, 'Colour ', colorIn), el('label', { class: 'mini grow' }, 'Size ', sizeIn)),
    el('div', { class: 'stage-wrap' }, stage),
    el('div', { class: 'row between pager' }, button('', { icon: 'left', onclick: () => showPage(pageIdx - 1) }), pageLbl, button('', { icon: 'right', onclick: () => showPage(pageIdx + 1) })),
    el('p', { class: 'faint' }, mode === 'sign' ? 'Tip: tap a tool, then tap the page. Drag to move, use the corner to resize.' : 'Tip: pick a tool and tap or drag on the page. Tap an item to select it; double-tap text to change it.'),
    el('div', { class: 'run-bar' }, button(mode === 'sign' ? 'Sign & save' : 'Save PDF', { icon: 'check', kind: 'primary wide', onclick: save })));
  chosen = async (u) => {
    const img = new Image(); img.src = u; await img.decode();
    addItem({ type: 'image', dataUrl: u, x: pageW / 2 - 75, y: pageH * 0.75, w: 150, h: (150 * img.height) / img.width });
    pick('move');
  };
  root.append(startScreen(t, open));
  if (preset && preset[0]) open(preset[0]);
  return root;
}

// ================================================================== Redact
function redactPage(t, preset) {
  const root = el('div', { class: 'page wide' });
  let bytes = null, doc = null, name = '', pageIdx = 0, scale = 1;
  let marks = {};
  const stage = el('div', { class: 'stage' });
  const layer = el('div', { class: 'layer' });
  const info = el('span', { class: 'muted' });
  const terms = el('textarea', { rows: 2, placeholder: 'Words or phrases to remove (one per line)' });
  const presetBoxes = Object.keys(C.PRESETS).map((k) => el('label', { class: 'check' }, el('input', { type: 'checkbox', value: k }), el('span', {}, k)));
  const count = () => Object.values(marks).reduce((a, m) => a + m.length, 0);
  const drawMarks = () => {
    layer.innerHTML = '';
    (marks[pageIdx] || []).forEach((m, k) => layer.append(el('div', { class: 'redmark', style: { left: `${m.x * scale}px`, top: `${m.y * scale}px`, width: `${m.w * scale}px`, height: `${m.h * scale}px` },
      onclick: (e) => { e.stopPropagation(); marks[pageIdx].splice(k, 1); drawMarks(); } })));
    info.textContent = `Page ${pageIdx + 1} / ${doc.numPages} · ${count()} marked`;
  };
  layer.addEventListener('pointerdown', (e) => {
    if (e.target !== layer) return;
    const r = layer.getBoundingClientRect();
    const x = (e.clientX - r.left) / scale, y = (e.clientY - r.top) / scale;
    const m = { x, y, w: 1, h: 1 };
    (marks[pageIdx] = marks[pageIdx] || []).push(m);
    layer.setPointerCapture(e.pointerId);
    const mv = (ev) => { const px = (ev.clientX - r.left) / scale, py = (ev.clientY - r.top) / scale; m.x = Math.min(x, px); m.y = Math.min(y, py); m.w = Math.abs(px - x); m.h = Math.abs(py - y); drawMarks(); };
    const up = () => { layer.removeEventListener('pointermove', mv); layer.removeEventListener('pointerup', up); if (m.w < 4 || m.h < 4) { marks[pageIdx].splice(marks[pageIdx].indexOf(m), 1); } drawMarks(); };
    layer.addEventListener('pointermove', mv); layer.addEventListener('pointerup', up);
  });
  const showPage = async (i) => {
    pageIdx = Math.max(0, Math.min(doc.numPages - 1, i));
    const width = Math.min(window.innerWidth - 24, 900);
    const r = await renderFit(doc, pageIdx, width);
    scale = width / r.width;
    stage.innerHTML = '';
    Object.assign(layer.style, { width: `${width}px`, height: `${r.height * scale}px` });
    stage.append(r.canvas, layer);
    drawMarks();
  };
  const find = async () => {
    const ts = terms.value.split('\n').map((s) => s.trim()).filter(Boolean);
    const ps = presetBoxes.filter((b) => b.querySelector('input').checked).map((b) => C.PRESETS[b.querySelector('input').value]);
    if (!ts.length && !ps.length) return toast('Type words or tick a category', 'info');
    progress.show('Searching…');
    try {
      const found = await C.findTextMarks(bytes, ts, ps);
      for (const [i, list] of Object.entries(found)) marks[i] = (marks[i] || []).concat(list);
      progress.hide();
      const n = Object.values(found).reduce((a, m) => a + m.length, 0);
      toast(n ? `Marked ${n} match${n === 1 ? '' : 'es'}` : 'Nothing found (scanned PDF? run OCR first)', n ? 'ok' : 'info');
      const first = Object.keys(found).map(Number).sort((a, b) => a - b)[0];
      await showPage(first ?? pageIdx);
    } catch (e) { progress.hide(); errorBox(e); }
  };
  const apply = async () => {
    if (!count()) return toast('Mark something first', 'info');
    try {
      progress.show('Redacting…', 0);
      const out = await C.redact(bytes, marks, (f, m) => progress.show(m, f));
      progress.hide();
      await deliver([{ name: `${stem(name)}_redacted.pdf`, bytes: out, mime: 'application/pdf' }], { note: 'Marked content was permanently removed in this copy. Your original is unchanged.' });
    } catch (e) { progress.hide(); errorBox(e); }
  };
  const ui = el('div', {},
    el('div', { class: 'card' }, terms, el('div', { class: 'checks' }, presetBoxes), button('Find & mark', { icon: 'search', onclick: find })),
    el('p', { class: 'faint' }, 'Or drag on the page to mark any area. Tap a black box to unmark it.'),
    el('div', { class: 'stage-wrap' }, stage),
    el('div', { class: 'row between pager' }, button('', { icon: 'left', onclick: () => showPage(pageIdx - 1) }), info, button('', { icon: 'right', onclick: () => showPage(pageIdx + 1) })),
    el('div', { class: 'run-bar' }, button('Redact & save', { icon: 'redact', kind: 'primary wide', onclick: apply })));
  const open = async (f) => {
    try {
      bytes = await readBytes(f); name = f.name; marks = {};
      doc = await openPdf(bytes);
      root.innerHTML = ''; root.append(ui); await showPage(0);
    } catch (e) { errorBox(isPasswordError(e) ? new Error('This PDF is protected - unlock it first.') : e); }
  };
  root.append(startScreen(t, open));
  if (preset && preset[0]) open(preset[0]);
  return root;
}

// ================================================================== Forms
function formsPage(t, preset) {
  const root = el('div', { class: 'page' });
  const open = async (f) => {
    try {
      const bytes = await readBytes(f);
      const fields = await C.listFields(bytes);
      root.innerHTML = '';
      if (!fields.length) {
        root.append(el('div', { class: 'card' }, el('h3', {}, 'No fillable fields'), el('p', { class: 'muted' },
          'This PDF has no form fields. Use Edit PDF to type text anywhere on the page instead.'),
        button('Open in Edit PDF', { icon: 'edit', onclick: () => openTool(TOOLS.find((x) => x.id === 'edit'), [f]) })));
        return;
      }
      const values = {};
      const inputs = fields.map((fd) => {
        values[fd.name] = fd.value;
        let inp;
        if (fd.type === 'checkbox') inp = el('input', { type: 'checkbox', checked: !!fd.value, onchange: (e) => { values[fd.name] = e.target.checked; } });
        else if (fd.options && fd.options.length) inp = el('select', { onchange: (e) => { values[fd.name] = e.target.value; } }, ['', ...fd.options].map((o) => el('option', { value: o, selected: o === fd.value }, o)));
        else if (fd.type === 'signature' || fd.type === 'button') return null;
        else inp = el('input', { type: 'text', value: fd.value || '', oninput: (e) => { values[fd.name] = e.target.value; } });
        return fd.type === 'checkbox' ? el('label', { class: 'check' }, inp, el('span', {}, fd.name)) : el('label', { class: 'field' }, el('span', {}, fd.name), inp);
      });
      const flat = el('input', { type: 'checkbox' });
      root.append(el('div', { class: 'tool-head' }, badge(t.icon, t.color, 44), el('div', {}, el('h2', {}, f.name), el('p', { class: 'muted' }, `${fields.length} fields`))),
        el('div', { class: 'card form' }, inputs),
        el('label', { class: 'check' }, flat, el('span', {}, 'Flatten (lock the answers into the page)')),
        el('div', { class: 'run-bar' }, button('Save filled PDF', { icon: 'check', kind: 'primary wide', onclick: async () => {
          try {
            progress.show('Saving…');
            const out = await C.fillFields(bytes, values, flat.checked);
            progress.hide();
            await deliver([{ name: `${stem(f.name)}_filled.pdf`, bytes: out, mime: 'application/pdf' }]);
          } catch (e) { progress.hide(); errorBox(e); }
        } })));
    } catch (e) { errorBox(e); }
  };
  root.append(startScreen(t, open));
  if (preset && preset[0]) open(preset[0]);
  return root;
}

// ================================================================== Compare
export function diffWords(a, b) {
  // Myers-style LCS on word arrays (bounded): returns [{op: '=', '-', '+', text}]
  const A = a.split(/\s+/).filter(Boolean), B = b.split(/\s+/).filter(Boolean);
  const n = A.length, m = B.length;
  if (n * m > 4e6) return [{ op: '-', text: A.join(' ') }, { op: '+', text: B.join(' ') }];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  const push = (op, w) => { const last = out[out.length - 1]; if (last && last.op === op) last.text += ` ${w}`; else out.push({ op, text: w }); };
  while (i < n && j < m) {
    if (A[i] === B[j]) { push('=', A[i]); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) { push('-', A[i]); i++; } else { push('+', B[j]); j++; }
  }
  while (i < n) push('-', A[i++]);
  while (j < m) push('+', B[j++]);
  return out;
}

function comparePage(t) {
  const root = el('div', { class: 'page' });
  const slots = [null, null];
  const out = el('div', {});
  const slot = (k, label) => {
    const b = el('button', { class: 'slot', onclick: async () => { const f = await pickOnePdf(); if (f) { slots[k] = f; b.querySelector('.faint').textContent = f.name; } } },
      icon('pdf', 26), el('div', { class: 'strong' }, label), el('div', { class: 'faint' }, 'Tap to choose'));
    return b;
  };
  const run = async () => {
    if (!slots[0] || !slots[1]) return toast('Choose both PDFs', 'info');
    try {
      progress.show('Comparing…', 0);
      const da = await openPdf(await readBytes(slots[0])), db = await openPdf(await readBytes(slots[1]));
      const n = Math.max(da.numPages, db.numPages);
      out.innerHTML = '';
      let changes = 0, report = `Comparison: ${slots[0].name} vs ${slots[1].name}\n\n`;
      for (let i = 0; i < n; i++) {
        progress.show(`Page ${i + 1} of ${n}`, i / n);
        const ta = i < da.numPages ? await pageText(da, i) : '', tb = i < db.numPages ? await pageText(db, i) : '';
        const d = diffWords(ta, tb);
        const ch = d.filter((x) => x.op !== '=');
        if (!ch.length) continue;
        changes += ch.length;
        out.append(el('div', { class: 'card' }, el('h3', {}, `Page ${i + 1} · ${ch.length} change${ch.length === 1 ? '' : 's'}`),
          el('p', { class: 'diff' }, d.map((x) => (x.op === '=' ? el('span', {}, `${x.text.length > 160 ? `${x.text.slice(0, 70)} … ${x.text.slice(-70)}` : x.text} `) : el(x.op === '-' ? 'del' : 'ins', {}, `${x.text} `))))));
        report += `--- Page ${i + 1}\n${ch.map((x) => `${x.op} ${x.text}`).join('\n')}\n\n`;
      }
      progress.hide();
      out.prepend(el('div', { class: 'card' }, el('h3', {}, changes ? `${changes} difference${changes === 1 ? '' : 's'} found` : 'No text differences'),
        el('p', { class: 'muted' }, el('del', {}, 'removed'), ' · ', el('ins', {}, 'added')),
        changes ? button('Save report', { icon: 'share', onclick: () => deliver([{ name: 'comparison.txt', bytes: new TextEncoder().encode(report), mime: 'text/plain' }]) }) : null));
    } catch (e) { progress.hide(); errorBox(e); }
  };
  root.append(el('div', { class: 'tool-head' }, badge(t.icon, t.color, 52), el('div', {}, el('h2', {}, t.name), el('p', { class: 'muted' }, t.desc))),
    el('div', { class: 'slots' }, slot(0, 'Original'), slot(1, 'Changed version')),
    button('Compare', { icon: 'compare', kind: 'primary wide', onclick: run }), out);
  return root;
}
