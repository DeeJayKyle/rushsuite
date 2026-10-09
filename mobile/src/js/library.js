// Read & Listen library, stored on the phone (IndexedDB).
const DB = 'rushsuite', STORE = 'items';
let dbP = null;
function db() {
  if (!dbP) {
    dbP = new Promise((resolve, reject) => {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: 'id' });
      r.onsuccess = () => resolve(r.result);
      r.onerror = () => reject(r.error);
    });
  }
  return dbP;
}
async function tx(mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(STORE, mode);
    const res = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(res && 'result' in res ? res.result : res);
    t.onerror = () => reject(t.error);
  });
}
export async function all() {
  const items = await tx('readonly', (s) => s.getAll());
  return (items || []).sort((a, b) => (b.opened || b.created) - (a.opened || a.created));
}
export const get = (id) => tx('readonly', (s) => s.get(id));
export async function put(item) {
  item.id = item.id || `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  item.created = item.created || Date.now();
  await tx('readwrite', (s) => s.put(item));
  return item;
}
export const remove = (id) => tx('readwrite', (s) => s.delete(id));
export async function add(kind, title, text, source = '') {
  const clean = String(text || '').replace(/\r/g, '').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  if (!clean) throw new Error('No readable text found.');
  return put({ kind, title: title || 'Untitled', text: clean, source, pos: 0 });
}

const ABBR = /\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e|Fig|No|Vol|pp|approx|Inc|Ltd|Co)\.$/i;
/** Split text into sentences (keeps headings / list items as their own lines). */
export function sentences(text) {
  const out = [];
  for (const para of String(text).split(/\n+/)) {
    const p = para.trim();
    if (!p) continue;
    let cur = '';
    const parts = p.split(/(?<=[.!?…]["')\]]?)\s+/);
    for (const part of parts) {
      cur = cur ? `${cur} ${part}` : part;
      if (ABBR.test(cur) || cur.length < 12) continue;
      out.push(cur);
      cur = '';
    }
    if (cur) out.push(cur);
  }
  // keep long sentences speakable
  return out.flatMap((s) => (s.length > 400 ? s.match(/.{1,380}(?:[,;:]\s|\s|$)/g).map((x) => x.trim()) : [s]));
}
