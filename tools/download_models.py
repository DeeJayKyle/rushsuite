"""Download RushSuite's offline models (Read & Listen voices/speech/AI + PDF OCR).
Usage: python tools/download_models.py [--no-llm] [--clone]"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
code = subprocess.call([sys.executable, "-u", str(HERE / "download_models_read.py"), *sys.argv[1:]])
code2 = subprocess.call([sys.executable, "-u", str(HERE / "download_models_pdf.py")])
sys.exit(code or code2)
