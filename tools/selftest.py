"""RushSuite self-test: runs the Read & Listen and the PDF tools self-tests."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
print("########## Read & Listen ##########", flush=True)
a = subprocess.call([sys.executable, "-u", str(HERE / "selftest_read.py")])
print("\n########## PDF tools ##########", flush=True)
b = subprocess.call([sys.executable, "-u", str(HERE / "selftest_pdf.py")])
print("\nRushSuite self-test:", "ALL PASSED" if not (a or b) else "some checks failed (see above)", flush=True)
sys.exit(1 if (a or b) else 0)
