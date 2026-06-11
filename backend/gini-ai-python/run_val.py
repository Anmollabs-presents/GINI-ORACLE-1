import subprocess, sys, os, pathlib
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.chdir(os.path.dirname(os.path.abspath(__file__)))
env = os.environ.copy()
env["PYTHONUTF8"] = "1"
r = subprocess.run([sys.executable, "validate_local_intel.py"],
    capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
out = r.stdout + r.stderr
pathlib.Path("val_result.txt").write_text(out, encoding="utf-8")
print(out)
sys.exit(r.returncode)
