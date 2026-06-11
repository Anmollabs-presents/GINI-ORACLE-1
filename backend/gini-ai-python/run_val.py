import subprocess, sys, os, pathlib
os.chdir(os.path.dirname(os.path.abspath(__file__)))
r = subprocess.run([sys.executable, "validate_local_intel.py"],
    capture_output=True, text=True, timeout=60)
out = r.stdout + r.stderr
pathlib.Path("val_result.txt").write_text(out, encoding="utf-8")
print(out[-4000:])
sys.exit(r.returncode)
