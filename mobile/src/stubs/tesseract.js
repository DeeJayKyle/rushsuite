// Local test stub: pretends to OCR (the real tesseract.js is bundled in the Android build).
export async function createWorker() {
  return {
    async recognize(img) {
      const w = img.width || 1000, h = img.height || 1000;
      return { data: { text: 'Hello scanned world', words: [
        { text: 'Hello', bbox: { x0: w * 0.1, y0: h * 0.1, x1: w * 0.2, y1: h * 0.13 } },
        { text: 'scanned', bbox: { x0: w * 0.22, y0: h * 0.1, x1: w * 0.35, y1: h * 0.13 } },
        { text: 'world', bbox: { x0: w * 0.37, y0: h * 0.1, x1: w * 0.47, y1: h * 0.13 } }] } };
    },
    async terminate() {},
  };
}
