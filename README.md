# RushSuite: PDF tools + Read & Listen + AI (Windows exe and Android apk)

RushSuite combines **PDFRush**, which covers every iLovePDF-style tool, with **ReadRush**, which covers the Speechify-style reading, voice and AI features. It comes in two forms:

| | **Windows (RushSuite.exe)** | **Android (RushSuite.apk)** |
|---|---|---|
| PDF tools | 35 tools. Merge, split, organize, compress, repair, OCR, PDF/A, Word/PowerPoint/Excel/HTML/JPG ⇄ PDF, Markdown, edit, sign, watermark, page numbers, crop, forms (detect/create/fill), flatten, protect, unlock, true redaction, compare, AI summarize, translate keeping the layout, and workflows | 27 tools. Merge, split, organize (thumbnails), remove/extract/rotate, compress, OCR, repair, JPG→PDF, **Scan to PDF with the camera**, PDF→JPG/Word/Text, image→text, edit (text, image, highlight, whiteout, draw), **sign with your finger**, watermark, page numbers, crop, fill forms, flatten, protect, unlock, redact, compare, AI summarize, translate |
| Read & Listen | Natural offline Kokoro voices with word highlighting, any document or web page, scan & listen, MP3 export, voice typing anywhere (Ctrl+Alt+Space), AI podcasts, meeting notes, notes, browser extension, optional voice cloning | Library (PDF, Word, EPUB, web links, pasted text, **photos of pages**), read-aloud with sentence highlighting using the phone's voices, speed, voice and pitch, resume where you stopped |
| AI | Offline model (optional) or a free online key, shared by both halves | Your free Gemini or Groq key (or Claude/OpenAI/OpenRouter): summarize, ask, quiz, translate |
| Works offline | Yes, everything except the online AI | PDF tools, OCR and reading: yes. AI: needs internet |

On Windows, the rail on the left switches between **PDF** and **Read & Listen**. Every PDF result has a **Listen** button, and files dropped on the window can be sent to either half.

## Build with GitHub (free)

1. Create a **Private** repository, e.g. `rushsuite`. It should be private because it contains the Android signing key.
2. Upload **everything inside this folder**, including the hidden `.github` folder. There are more than 100 files, which is too many for the web uploader, so use **GitHub Desktop**: clone the empty repo, copy these files in, then click **Commit** and **Push**.
3. **Actions** starts "Build RushSuite" automatically:
   - **Windows:** the job builds the portable Python runtime, engines, voices, speech recognition and OCR, then makes an installer. It takes about 30–60 minutes.
   - **Android:** the job bundles the web app, creates the Capacitor Android project and makes a signed APK. It takes about 10 minutes.
4. Open **Releases**. Download **RushSuite-Setup-1.0.N.exe** together with any **RushSuite-Setup-1.0.N-*.bin** files (keep them in the same folder) and run the .exe. The phone app is **RushSuite.apk**.

If a build fails, open the failed run, download **windows-build-logs** (Windows), or copy the red error text (Android), and send it to me.

Windows may say "Windows protected your PC" because the exe isn't code-signed. Click **More info → Run anyway**. On Android, allow "Install unknown apps" for the app you open the APK with.

### Optional: your own Android signing password

The workflow signs with `mobile/keystore/rushsuite.jks`, whose password is `rushsuite-release`. To use your own key, replace that file and add a repository secret named `KEYSTORE_PASSWORD`. Keep the same key forever, otherwise phones refuse to install updates.

## Build Windows on your own PC instead

Unzip to a short path such as `C:\RushSuite-src` and double-click **build.bat**. Options:

- `build.bat nollm` skips the 2.5 GB offline AI.
- `build.bat clone` adds voice cloning.

The app ends up at `dist\RushSuite\RushSuite.exe`.

## Notes

- **Office conversion on Windows:** Word/PowerPoint/Excel → PDF uses Microsoft Office if it's installed, otherwise the free LibreOffice.
- **Phone voices:** these come from Android's text-to-speech. For nicer voices, install them in Android Settings → Text-to-speech.
- **Where results are saved:** on the phone, in **Documents/RushSuite**, and every result has a Share button. On Windows, in **Documents\PDFRush** and **Documents\ReadRush**.
