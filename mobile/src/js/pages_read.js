// Read & Listen: library, reader with read-aloud and highlighting, AI assistant, settings.
import * as Lib from './library.js';
import { fileToText, urlToText, READABLE } from './importers.js';
import { imageFileToCanvas, recognize } from './ocr.js';
import { tts, shareText } from './native.js';
import * as AI from './ai.js';
import { settings, saveSettings } from './settings.js';
import { el, icon, badge, button, toast, progress, sheet, ask, errorBox, pickFiles, confirmBox } from './ui.js';

let nav = null;
export function bindNav(n) { nav = n; }

const KIND = { pdf: ['pdf', '#FF5A5F'], doc: ['text', '#4DA3FF'], book: ['book', '#8B7CFF'], web: ['link', '#36D6E7'], scan: ['scan', '#FFC857'], text: ['text', '#9BA3B8'] };

// ================================================================== library
export function libraryPage() {
  const list = el('div', { class: 'lib-list' });
  const refresh = async () => {
    const items = await Lib.all();
    list.innerHTML = '';
    if (!items.length) {
      list.append(el('div', { class: 'empty' }, icon('book', 40), el('p', {}, 'Add a PDF, Word file, e-book, web link or a photo of a page and RushSuite will read it to you.')));
      return;
    }
    for (const it of items) {
      const [ic, col] = KIND[it.kind] || KIND.text;
      const total = Math.max(1, it.total || 1);
      list.append(el('div', { class: 'lib-row', onclick: () => openReader(it.id) }, badge(ic, col, 40),
        el('div', { class: 'grow' }, el('div', { class: 'strong ellipsis' }, it.title),
          el('div', { class: 'faint' }, `${Math.round(((it.pos || 0) / total) * 100)}% · ${Math.ceil(it.text.length / 1100)} min read`)),
        el('button', { class: 'icon-btn', onclick: async (e) => { e.stopPropagation(); if (await confirmBox('Remove', `Remove "${it.title}" from the library?`)) { await Lib.remove(it.id); refresh(); } } }, icon('trash', 18))));
    }
  };
  const addFiles = async () => {
    const fs = await pickFiles({ accept: READABLE, multiple: true });
    let last = null;
    for (const f of fs) {
      try {
        progress.show(`Opening ${f.name}…`);
        const r = await fileToText(f, (fr, m) => progress.show(m, fr));
        last = await Lib.add(r.kind, r.title, r.text, f.name);
      } catch (e) {
        progress.hide();
        if (e.scanned && await confirmBox('Scanned PDF', 'This PDF is a scan. Read it with OCR (text recognition)? It takes a little while.')) {
          last = await ocrPdfToLibrary(f) || last;
        } else errorBox(e);
      }
    }
    progress.hide();
    refresh();
    if (last && fs.length === 1) openReader(last.id, true);
  };
  const addLink = async () => {
    const url = await ask('Read a web page', 'Link (https://…)', '', { type: 'url' });
    if (!url) return;
    try {
      progress.show('Opening page…');
      const r = await urlToText(url.trim());
      const it = await Lib.add(r.kind, r.title, r.text, url);
      progress.hide(); refresh(); openReader(it.id, true);
    } catch (e) { progress.hide(); errorBox(e); }
  };
  const addText = async () => {
    const t = await ask('Paste text', 'Text to read', '', { multiline: true });
    if (!t || !t.trim()) return;
    const it = await Lib.add('text', t.trim().split('\n')[0].slice(0, 60), t);
    refresh(); openReader(it.id, true);
  };
  const addScan = async () => {
    const fs = await pickFiles({ accept: 'image/*', multiple: true, capture: 'environment' });
    if (!fs.length) return;
    try {
      let text = '';
      for (let k = 0; k < fs.length; k++) {
        progress.show(`Reading photo ${k + 1} of ${fs.length}…`, k / fs.length);
        text += `${text ? '\n\n' : ''}${(await recognize(await imageFileToCanvas(fs[k]))).text}`;
      }
      progress.hide();
      if (!text.trim()) return toast('No text found in that photo', 'err');
      const it = await Lib.add('scan', `Scan ${new Date().toLocaleString()}`, text);
      refresh(); openReader(it.id, true);
    } catch (e) { progress.hide(); errorBox(e); }
  };
  refresh();
  const page = el('div', { class: 'page' },
    el('div', { class: 'hero' }, el('h1', {}, 'Read & Listen'), el('p', { class: 'muted' }, 'Anything you add is read aloud with highlighting. Ask AI about it too.')),
    el('div', { class: 'add-grid' },
      el('button', { class: 'add-btn', onclick: addFiles }, icon('pdf', 24), el('span', {}, 'File')),
      el('button', { class: 'add-btn', onclick: addScan }, icon('scan', 24), el('span', {}, 'Scan')),
      el('button', { class: 'add-btn', onclick: addLink }, icon('link', 24), el('span', {}, 'Link')),
      el('button', { class: 'add-btn', onclick: addText }, icon('clipboard', 24), el('span', {}, 'Paste'))),
    el('h3', { class: 'section' }, 'Library'), list);
  page.refresh = refresh;
  return page;
}

async function ocrPdfToLibrary(file) {
  const { openPdf, renderPage } = await import('./pdfview.js');
  try {
    const doc = await openPdf(new Uint8Array(await file.arrayBuffer()));
    let text = '';
    for (let i = 0; i < doc.numPages; i++) {
      progress.show(`Reading page ${i + 1} of ${doc.numPages}…`, i / doc.numPages);
      const c = await renderPage(doc, i, 2);
      text += `${text ? '\n\n' : ''}${(await recognize(c)).text}`;
      c.width = c.height = 0;
    }
    progress.hide();
    return await Lib.add('scan', file.name.replace(/\.pdf$/i, ''), text, file.name);
  } catch (e) { progress.hide(); errorBox(e); return null; }
}

export async function addAndRead(title, text, kind = 'text') {
  const it = await Lib.add(kind, title, text);
  openReader(it.id, true);
}

// ================================================================== reader
const player = { item: null, sents: [], pos: 0, playing: false, token: 0, onChange: null };

async function playLoop() {
  const my = ++player.token;
  player.playing = true;
  player.onChange && player.onChange();
  const s = settings();
  while (player.playing && my === player.token && player.pos < player.sents.length) {
    player.onChange && player.onChange();
    try {
      await tts.speak(player.sents[player.pos], { rate: s.rate, pitch: s.pitch, voice: s.voice });
    } catch (e) {
      player.playing = false;
      errorBox(new Error(`Read-aloud failed: ${e.message || e}. Check Settings → Voice (you may need to install a voice).`));
      break;
    }
    if (!player.playing || my !== player.token) break;
    player.pos++;
    savePos();
  }
  if (my === player.token) {
    if (player.pos >= player.sents.length) { player.pos = 0; player.playing = false; savePos(); }
    player.onChange && player.onChange();
  }
}
let saveTimer = null;
function savePos() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { if (player.item) { player.item.pos = player.pos; player.item.total = player.sents.length; player.item.opened = Date.now(); Lib.put(player.item); } }, 400);
}
export async function pause() { player.playing = false; player.token++; await tts.stop(); player.onChange && player.onChange(); }
async function jump(i) {
  await pause();
  player.pos = Math.max(0, Math.min(player.sents.length - 1, i));
  savePos();
  playLoop();
}

export async function openReader(id, autoplay = false) {
  const it = await Lib.get(id);
  if (!it) return;
  if (player.item?.id !== it.id) {
    await pause();
    player.item = it;
    player.sents = Lib.sentences(it.text);
    player.pos = Math.min(it.pos || 0, Math.max(0, player.sents.length - 1));
  }
  nav.push(it.title, readerView(), { keepAlive: false });
  if (autoplay && !player.playing) playLoop();
}

function readerView() {
  const s = settings();
  const textBox = el('div', { class: `reader-text theme-${s.readerTheme.toLowerCase()}`, style: { fontSize: `${s.readerFont}px` } });
  const spans = player.sents.map((t, i) => el('span', { class: 'sent', onclick: () => jump(i) }, `${t} `));
  // paragraphs: re-insert breaks where the original text had them
  let cursor = 0;
  const txt = player.item.text;
  spans.forEach((sp, i) => {
    const at = txt.indexOf(player.sents[i].slice(0, 20), cursor);
    if (i > 0 && at > 0 && /\n/.test(txt.slice(cursor, at))) textBox.append(el('br'), el('br'));
    if (at >= 0) cursor = at + 1;
    textBox.append(sp);
  });
  const playBtn = el('button', { class: 'play-btn', onclick: () => (player.playing ? pause() : playLoop()) }, icon('play', 28));
  const prog = el('input', { type: 'range', min: 0, max: Math.max(0, player.sents.length - 1), value: player.pos, class: 'grow', onchange: (e) => jump(Number(e.target.value)) });
  const pct = el('span', { class: 'faint' });
  const speed = el('button', { class: 'chip on', onclick: async () => {
    const opts = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];
    const cur = settings().rate;
    const next = opts[(opts.indexOf(cur) + 1) % opts.length] || 1;
    saveSettings({ rate: next }); speed.textContent = `${next}×`;
    if (player.playing) jump(player.pos);
  } }, `${s.rate}×`);
  let last = -1;
  const update = () => {
    if (last >= 0 && spans[last]) spans[last].classList.remove('cur');
    const cur = spans[player.pos];
    if (cur) { cur.classList.add('cur'); if (player.playing) cur.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    last = player.pos;
    playBtn.innerHTML = '';
    playBtn.append(icon(player.playing ? 'pause' : 'play', 28));
    prog.value = player.pos;
    pct.textContent = `${Math.round((player.pos / Math.max(1, player.sents.length)) * 100)}%`;
  };
  player.onChange = update;
  setTimeout(() => { update(); spans[player.pos]?.scrollIntoView({ block: 'center' }); }, 50);
  const aiRow = el('div', { class: 'toolbar scroll' },
    el('button', { class: 'tbtn', onclick: () => aiAction('summary') }, icon('ai', 18), el('span', {}, 'Summarize')),
    el('button', { class: 'tbtn', onclick: () => aiAction('ask') }, icon('chat', 18), el('span', {}, 'Ask')),
    el('button', { class: 'tbtn', onclick: () => aiAction('quiz') }, icon('quiz', 18), el('span', {}, 'Quiz me')),
    el('button', { class: 'tbtn', onclick: () => aiAction('translate') }, icon('translate', 18), el('span', {}, 'Translate')),
    el('button', { class: 'tbtn', onclick: () => voicePicker() }, icon('volume', 18), el('span', {}, 'Voice')),
    el('button', { class: 'tbtn', onclick: () => shareText(player.item.text, player.item.title) }, icon('share', 18), el('span', {}, 'Share')));
  return el('div', { class: 'reader' }, aiRow, textBox,
    el('div', { class: 'player' },
      el('div', { class: 'row' }, prog, pct),
      el('div', { class: 'row center' },
        el('button', { class: 'icon-btn big', onclick: () => jump(player.pos - 1) }, icon('prev', 24)), playBtn,
        el('button', { class: 'icon-btn big', onclick: () => jump(player.pos + 1) }, icon('next', 24)), speed)));
}

async function aiAction(kind) {
  if (!AI.aiReady()) {
    await sheet('AI key needed', el('p', { class: 'muted' }, 'Go to Settings → AI and paste a free Google Gemini or Groq key.'), [{ text: 'OK', kind: 'primary' }]);
    return;
  }
  const text = player.item.text;
  try {
    if (kind === 'summary') {
      progress.show('Summarizing…');
      const md = await AI.summarize(text, { length: 'Medium' }, (f, m) => progress.show(m, f));
      progress.hide();
      showAnswer('Summary', md);
    } else if (kind === 'ask') {
      chatSheet(player.item.title, text);
    } else if (kind === 'translate') {
      const lang = await chooseLang();
      if (!lang) return;
      progress.show('Translating…');
      const t = await AI.translate(text, lang, (f, m) => progress.show(m, f));
      progress.hide();
      await addAndRead(`${player.item.title} (${lang})`, t, player.item.kind);
    } else if (kind === 'quiz') {
      progress.show('Making a quiz…');
      const qs = await AI.quiz(text, 5);
      progress.hide();
      quizSheet(qs);
    }
  } catch (e) { progress.hide(); errorBox(e); }
}

function mdToNodes(md) {
  return md.split('\n').filter((l) => l.trim()).map((l) => {
    const h = l.match(/^#{1,3}\s+(.*)/);
    const b = l.match(/^\s*[-*•]\s+(.*)/);
    const inline = (s) => s.split(/(\*\*[^*]+\*\*)/).map((p) => (p.startsWith('**') ? el('b', {}, p.slice(2, -2)) : p));
    if (h) return el('h4', {}, inline(h[1]));
    if (b) return el('li', {}, inline(b[1]));
    return el('p', {}, inline(l));
  });
}

function showAnswer(title, md) {
  sheet(title, el('div', { class: 'md' }, mdToNodes(md)), [
    { text: 'Listen', icon: 'volume', value: async () => { await addAndRead(`${title}: ${player.item?.title || ''}`, md.replace(/[#*]/g, ''), 'text'); return true; } },
    { text: 'Share', icon: 'share', value: async () => { await shareText(md, title); return false; } },
    { text: 'Close', kind: 'primary' }]);
}

async function chooseLang() {
  const sel = el('select', {}, AI.LANGUAGES.map((l) => el('option', {}, l)));
  return sheet('Translate to', el('label', { class: 'field' }, el('span', {}, 'Language'), sel),
    [{ text: 'Cancel', kind: 'ghost', value: () => null }, { text: 'Translate', kind: 'primary', value: () => sel.value }]);
}

function quizSheet(qs) {
  let score = 0, answered = 0;
  const body = el('div', { class: 'quiz' }, qs.map((q, qi) => {
    const box = el('div', { class: 'card' }, el('div', { class: 'strong' }, `${qi + 1}. ${q.question}`));
    q.options.forEach((o, oi) => box.append(el('button', { class: 'opt', onclick: (e) => {
      if (box.dataset.done) return;
      box.dataset.done = '1'; answered++;
      const ok = oi === q.answer;
      if (ok) score++;
      e.currentTarget.classList.add(ok ? 'right' : 'wrong');
      box.querySelectorAll('.opt')[q.answer].classList.add('right');
      box.append(el('p', { class: 'faint' }, q.explanation || ''));
      if (answered === qs.length) toast(`Score: ${score} / ${qs.length}`, 'ok');
    } }, o)));
    return box;
  }));
  sheet('Quiz', body, [{ text: 'Done', kind: 'primary' }]);
}

export function chatSheet(title, docText = '') {
  const history = [];
  const log = el('div', { class: 'chat-log' });
  const input = el('textarea', { rows: 2, placeholder: docText ? 'Ask about this document…' : 'Ask anything…' });
  const sendBtn = button('', { icon: 'chat', kind: 'primary', onclick: () => send() });
  const send = async () => {
    const q = input.value.trim();
    if (!q) return;
    input.value = '';
    log.append(el('div', { class: 'bubble me' }, q));
    const wait = el('div', { class: 'bubble ai faint' }, 'Thinking…');
    log.append(wait);
    log.scrollTop = log.scrollHeight;
    try {
      const a = docText ? await AI.askDoc(docText, q, history) : await AI.chat([{ role: 'system', content: 'You are a helpful, concise assistant.' }, ...history.slice(-8), { role: 'user', content: q }]);
      history.push({ role: 'user', content: q }, { role: 'assistant', content: a });
      wait.replaceWith(el('div', { class: 'bubble ai' }, el('div', { class: 'md' }, mdToNodes(a)),
        el('button', { class: 'link-btn', onclick: () => tts.speak(a.replace(/[#*]/g, ''), { rate: settings().rate, voice: settings().voice }) }, icon('volume', 16), ' Listen')));
    } catch (e) { wait.textContent = e.message; }
    log.scrollTop = log.scrollHeight;
  };
  sheet(`Ask: ${title}`, el('div', { class: 'chat' }, log, el('div', { class: 'row' }, input, sendBtn)));
}

async function voicePicker() {
  const vs = await tts.voices();
  const s = settings();
  const sel = el('select', {}, el('option', { value: -1 }, 'Phone default'),
    vs.map((v, i) => el('option', { value: i, selected: i === s.voice }, `${v.name || v.voiceURI} (${v.lang})`)));
  const pitch = el('input', { type: 'range', min: 0.5, max: 2, step: 0.1, value: s.pitch });
  const r = await sheet('Voice', el('div', { class: 'form' },
    el('label', { class: 'field' }, el('span', {}, 'Voice'), sel),
    el('label', { class: 'field' }, el('span', {}, 'Pitch'), pitch),
    button('Get more voices', { kind: 'ghost', icon: 'plus', onclick: () => tts.installVoices() }),
    el('p', { class: 'faint' }, 'Voices come from your phone (Google Speech Services). Tip: install high-quality voices in Android Settings → Text-to-speech.')),
  [{ text: 'Test', kind: 'ghost', value: async () => { await tts.speak('Hello! This is how I sound.', { voice: Number(sel.value), pitch: Number(pitch.value), rate: s.rate }); return false; } },
    { text: 'Save', kind: 'primary', value: () => 'save' }]);
  if (r === 'save') {
    saveSettings({ voice: Number(sel.value), pitch: Number(pitch.value) });
    if (player.playing) jump(player.pos);
    toast('Voice saved');
  }
}

// ================================================================== AI tab
export function aiPage() {
  const ready = AI.aiReady();
  return el('div', { class: 'page' },
    el('div', { class: 'hero' }, el('h1', {}, 'AI assistant'), el('p', { class: 'muted' }, ready ? `Using ${settings().provider}.` : 'Add a free AI key in Settings to start.')),
    el('div', { class: 'list' },
      el('button', { class: 'list-row', onclick: () => chatSheet('AI') }, badge('chat', '#8B7CFF', 40), el('div', {}, el('div', { class: 'strong' }, 'Chat'), el('div', { class: 'faint' }, 'Ask anything'))),
      el('button', { class: 'list-row', onclick: async () => { const t = await ask('Summarize text', 'Paste the text', '', { multiline: true }); if (t) { try { progress.show('Summarizing…'); const md = await AI.summarize(t); progress.hide(); showAnswer('Summary', md); } catch (e) { progress.hide(); errorBox(e); } } } },
        badge('ai', '#FF5A5F', 40), el('div', {}, el('div', { class: 'strong' }, 'Summarize text'), el('div', { class: 'faint' }, 'Paste anything long'))),
      el('button', { class: 'list-row', onclick: async () => { const t = await ask('Translate text', 'Paste the text', '', { multiline: true }); if (!t) return; const lang = await chooseLang(); if (!lang) return; try { progress.show('Translating…'); const r = await AI.translate(t, lang); progress.hide(); showAnswer(`Translation (${lang})`, r); } catch (e) { progress.hide(); errorBox(e); } } },
        badge('translate', '#36D6E7', 40), el('div', {}, el('div', { class: 'strong' }, 'Translate text'), el('div', { class: 'faint' }, '30+ languages incl. Swahili & Luganda'))),
      el('button', { class: 'list-row', onclick: () => nav.tab('pdf', 'summarize') }, badge('pdf', '#FFC857', 40), el('div', {}, el('div', { class: 'strong' }, 'Summarize or translate a PDF'), el('div', { class: 'faint' }, 'Opens the PDF AI tools')))));
}

// ================================================================== settings
export function settingsPage() {
  const s = settings();
  const prov = el('select', {}, Object.keys(AI.PROVIDERS).map((p) => el('option', { selected: p === s.provider }, p)));
  const key = el('input', { type: 'password', placeholder: 'Paste your API key', value: (s.keys || {})[s.provider] || '' });
  const model = el('input', { type: 'text', placeholder: AI.PROVIDERS[s.provider]?.model || 'model', value: s.model || '' });
  const base = el('input', { type: 'url', placeholder: 'https://…/v1 (custom only)', value: s.baseUrl || '' });
  const getKey = el('a', { class: 'link-btn', href: AI.PROVIDERS[s.provider]?.keyUrl || '#', target: '_blank' }, 'Get a free key →');
  prov.addEventListener('change', () => {
    key.value = (settings().keys || {})[prov.value] || '';
    model.placeholder = AI.PROVIDERS[prov.value].model || 'model';
    getKey.href = AI.PROVIDERS[prov.value].keyUrl || '#';
    base.parentElement.style.display = prov.value.startsWith('Custom') ? '' : 'none';
  });
  const out = el('p', { class: 'faint' });
  const saveAi = () => {
    const keys = { ...(settings().keys || {}) };
    keys[prov.value] = key.value.trim();
    saveSettings({ provider: prov.value, keys, model: model.value.trim(), baseUrl: base.value.trim() });
    toast('AI settings saved');
  };
  const font = el('input', { type: 'range', min: 14, max: 30, value: s.readerFont, onchange: (e) => saveSettings({ readerFont: Number(e.target.value) }) });
  const theme = el('select', { onchange: (e) => saveSettings({ readerTheme: e.target.value }) }, ['Dark', 'Light', 'Sepia'].map((t) => el('option', { selected: t === s.readerTheme }, t)));
  const baseField = el('label', { class: 'field', style: { display: s.provider.startsWith('Custom') ? '' : 'none' } }, el('span', {}, 'Server URL'), base);
  return el('div', { class: 'page' },
    el('div', { class: 'hero' }, el('h1', {}, 'Settings')),
    el('div', { class: 'card form' }, el('h3', {}, 'AI'),
      el('p', { class: 'faint' }, 'Used for summaries, questions, quizzes and translation. Google Gemini and Groq give free keys. Your key stays on this phone; the text you ask about is sent to that provider.'),
      el('label', { class: 'field' }, el('span', {}, 'Provider'), prov),
      el('label', { class: 'field' }, el('span', {}, 'API key'), key), getKey,
      el('label', { class: 'field' }, el('span', {}, 'Model (optional)'), model), baseField,
      el('div', { class: 'row' }, button('Save', { kind: 'primary', icon: 'check', onclick: saveAi }),
        button('Test', { icon: 'ai', onclick: async () => { saveAi(); out.textContent = 'Testing…'; try { out.textContent = `✔ ${await AI.chat([{ role: 'user', content: 'Say hello in five words.' }], { maxTokens: 30 })}`; } catch (e) { out.textContent = `✘ ${e.message}`; } } })), out),
    el('div', { class: 'card form' }, el('h3', {}, 'Reading'),
      el('label', { class: 'field' }, el('span', {}, 'Text size'), font),
      el('label', { class: 'field' }, el('span', {}, 'Reader theme'), theme),
      button('Voice & pitch', { icon: 'volume', onclick: voicePicker })),
    el('div', { class: 'card' }, el('h3', {}, 'About'),
      el('p', { class: 'faint' }, 'RushSuite Mobile 1.0 - PDF tools, read & listen and AI. Files you create are saved in Documents/RushSuite. PDF tools and OCR work offline.')));
}
