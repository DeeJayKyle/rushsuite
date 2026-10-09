// Bundles src/ into www/ (esbuild) and copies the PDF.js worker, OCR engine and OCR language data.
import { build } from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import https from 'node:https';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const www = path.join(root, 'www');
const require = createRequire(path.join(root, 'package.json'));
const LOCAL = process.env.RUSH_LOCAL === '1';           // local test build: stubs for native plugins
const has = (m) => { try { require.resolve(m); return true; } catch { return false; } };

fs.rmSync(www, { recursive: true, force: true });
fs.mkdirSync(path.join(www, 'vendor'), { recursive: true });

const pdfjsLegacy = has('pdfjs-dist/legacy/build/pdf.mjs');
const alias = {
  'pdfjs': pdfjsLegacy ? 'pdfjs-dist/legacy/build/pdf.mjs' : 'pdfjs-dist/build/pdf.mjs',
  'pdf-lib': has('@cantoo/pdf-lib') ? '@cantoo/pdf-lib' : 'pdf-lib',
};
if (LOCAL || !has('@capacitor/core')) alias['@capacitor/core'] = path.join(root, 'src/stubs/capacitor-core.js');
if (!has('tesseract.js')) alias['tesseract.js'] = path.join(root, 'src/stubs/tesseract.js');

await build({
  entryPoints: [path.join(root, 'src/js/app.js')],
  bundle: true, format: 'esm', target: ['chrome100'], minify: !LOCAL, sourcemap: LOCAL,
  outfile: path.join(www, 'app.js'), alias, logLevel: 'info',
  define: { 'process.env.NODE_ENV': '"production"' },
  nodePaths: [path.join(root, 'node_modules'), ...(process.env.NODE_PATH ? process.env.NODE_PATH.split(':') : [])],
});

for (const f of ['index.html', 'styles.css', 'icon.png']) fs.copyFileSync(path.join(root, 'src', f), path.join(www, f));

// PDF.js worker
const wdir = path.dirname(require.resolve(pdfjsLegacy ? 'pdfjs-dist/legacy/build/pdf.mjs' : 'pdfjs-dist/build/pdf.mjs'));
fs.copyFileSync(path.join(wdir, 'pdf.worker.min.mjs'), path.join(www, 'vendor', 'pdf.worker.min.mjs'));

// OCR (tesseract.js): worker + wasm core + English language data, all served locally (works offline)
if (has('tesseract.js')) {
  const tdir = path.dirname(require.resolve('tesseract.js/package.json'));
  fs.copyFileSync(path.join(tdir, 'dist', 'worker.min.js'), path.join(www, 'vendor', 'tesseract-worker.min.js'));
  const cdir = path.dirname(require.resolve('tesseract.js-core/package.json'));
  fs.mkdirSync(path.join(www, 'vendor', 'tesseract-core'), { recursive: true });
  for (const f of fs.readdirSync(cdir)) {
    if (/^tesseract-core.*\.(js|wasm)$/.test(f)) fs.copyFileSync(path.join(cdir, f), path.join(www, 'vendor', 'tesseract-core', f));
  }
  const langDir = path.join(www, 'vendor', 'lang');
  fs.mkdirSync(langDir, { recursive: true });
  const dest = path.join(langDir, 'eng.traineddata.gz');
  const cache = path.join(root, '.cache', 'eng.traineddata.gz');
  if (!fs.existsSync(cache)) {
    fs.mkdirSync(path.dirname(cache), { recursive: true });
    const urls = ['https://tessdata.projectnaptha.com/4.0.0_fast/eng.traineddata.gz',
      'https://github.com/naptha/tessdata/raw/gh-pages/4.0.0_fast/eng.traineddata.gz',
      'https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz'];
    let ok = false;
    for (const u of urls) {
      try { await download(u, cache); ok = fs.statSync(cache).size > 100000; if (ok) break; } catch (e) { console.warn('OCR data:', e.message); }
    }
    if (!ok) throw new Error('Could not download the OCR language data');
  }
  fs.copyFileSync(cache, dest);
}
console.log('www ready:', fs.readdirSync(www).join(', '));

function download(url, dest, hops = 5) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && hops > 0) {
        res.resume();
        return resolve(download(new URL(res.headers.location, url).toString(), dest, hops - 1));
      }
      if (res.statusCode !== 200) return reject(new Error(`download ${url}: HTTP ${res.statusCode}`));
      const out = fs.createWriteStream(dest);
      res.pipe(out);
      out.on('finish', () => out.close(resolve));
    }).on('error', reject);
  });
}
