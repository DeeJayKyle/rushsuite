// RushSuite Mobile: app shell (tabs + screen stack + Android back button).
import { pdfHome, openTool, bindNav as bindPdf } from './pages_pdf.js';
import { libraryPage, aiPage, settingsPage, addAndRead, pause, bindNav as bindRead } from './pages_read.js';
import { byId } from './tools.js';
import { el, icon, $ } from './ui.js';

const TABS = [
  { key: 'pdf', label: 'PDF tools', icon: 'grid', make: pdfHome, title: 'RushSuite' },
  { key: 'read', label: 'Listen', icon: 'volume', make: libraryPage, title: 'Read & Listen' },
  { key: 'ai', label: 'AI', icon: 'ai', make: aiPage, title: 'AI assistant' },
  { key: 'settings', label: 'Settings', icon: 'settings', make: settingsPage, title: 'Settings' },
];
const roots = {};
let tab = 'pdf';
const stack = [];          // [{title, view}]

function render() {
  const view = $('#view');
  view.innerHTML = '';
  const top = stack[stack.length - 1];
  const t = TABS.find((x) => x.key === tab);
  if (top) view.append(top.view);
  else {
    if (!roots[tab] || tab === 'ai') roots[tab] = t.make();
    if (roots[tab].refresh) roots[tab].refresh();
    view.append(roots[tab]);
  }
  $('#title').textContent = top ? top.title : t.title;
  $('#back').style.visibility = stack.length ? 'visible' : 'hidden';
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.k === tab));
  view.scrollTop = 0;
  window.scrollTo(0, 0);
}

const nav = {
  push(title, view) {
    stack.push({ title, view });
    history.pushState({ depth: stack.length }, '');
    render();
  },
  pop() { if (stack.length) history.back(); },
  tab(key, toolId = null) {
    stack.length = 0;
    tab = key;
    history.replaceState({ depth: 0 }, '');
    render();
    if (toolId && byId[toolId]) openTool(byId[toolId]);
  },
  listenText(title, text) { tab = 'read'; stack.length = 0; render(); addAndRead(title, text); },
};

window.addEventListener('popstate', () => {
  if (stack.length) {
    const top = stack.pop();
    if (top.view.classList.contains('reader')) pause();
    render();
  }
});

function boot() {
  bindPdf(nav);
  bindRead(nav);
  const tabs = $('#tabs');
  for (const t of TABS) {
    tabs.append(el('button', { 'data-k': t.key, onclick: () => nav.tab(t.key) }, icon(t.icon, 22), el('span', {}, t.label)));
  }
  $('#back').append(icon('back', 24));
  $('#back').addEventListener('click', () => nav.pop());
  history.replaceState({ depth: 0 }, '');
  render();
}

window.rushsuite = { nav, openTool, byId };
boot();
