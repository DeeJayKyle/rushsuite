// Runs after `npx cap add android` (GitHub Actions): app icons, version, small manifest tweaks.
import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const res = path.join(root, 'android/app/src/main/res');

// icons (made from the desktop icon with ImageMagick if the PNGs aren't in the repo)
const icons = path.join(root, 'resources/android');
if (!fs.existsSync(icons)) {
  const src = path.join(root, '../app/assets/icon.png');
  const sizes = { mdpi: [48, 108], hdpi: [72, 162], xhdpi: [96, 216], xxhdpi: [144, 324], xxxhdpi: [192, 432] };
  try {
    for (const [d, [s, f]] of Object.entries(sizes)) {
      const dir = path.join(icons, `mipmap-${d}`);
      fs.mkdirSync(dir, { recursive: true });
      execSync(`convert "${src}" -resize ${s}x${s} "${dir}/ic_launcher.png"`);
      fs.copyFileSync(`${dir}/ic_launcher.png`, `${dir}/ic_launcher_round.png`);
      const inner = Math.round(f * 0.72);
      execSync(`convert "${src}" -resize ${inner}x${inner} -background none -gravity center -extent ${f}x${f} "${dir}/ic_launcher_foreground.png"`);
    }
  } catch (e) {
    console.warn('Icons skipped (ImageMagick not available):', e.message);
    fs.rmSync(icons, { recursive: true, force: true });
  }
}
for (const dir of (fs.existsSync(icons) ? fs.readdirSync(icons) : [])) {
  const dst = path.join(res, dir);
  fs.mkdirSync(dst, { recursive: true });
  for (const f of fs.readdirSync(path.join(icons, dir))) fs.copyFileSync(path.join(icons, dir, f), path.join(dst, f));
}
const bg = path.join(res, 'values/ic_launcher_background.xml');
if (fs.existsSync(bg)) fs.writeFileSync(bg, '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#0B0D12</color>\n</resources>\n');

// version from the CI run number
const gradle = path.join(root, 'android/app/build.gradle');
let g = fs.readFileSync(gradle, 'utf8');
const run = parseInt(process.env.GITHUB_RUN_NUMBER || '1', 10);
g = g.replace(/versionCode\s+\d+/, `versionCode ${run}`).replace(/versionName\s+"[^"]*"/, `versionName "1.0.${run}"`);
fs.writeFileSync(gradle, g);

// manifest: allow saving to Documents on Android 10 too
const mf = path.join(root, 'android/app/src/main/AndroidManifest.xml');
let m = fs.readFileSync(mf, 'utf8');
if (!m.includes('requestLegacyExternalStorage')) m = m.replace('<application', '<application\n        android:requestLegacyExternalStorage="true"');
if (!m.includes('WRITE_EXTERNAL_STORAGE')) {
  m = m.replace('</manifest>', '    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="29" />\n</manifest>');
}
fs.writeFileSync(mf, m);
console.log('Android project patched (icons, version 1.0.' + run + ')');
