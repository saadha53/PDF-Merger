"""Check that the actual frozen application imports Qt and creates its window."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    executable = Path(sys.argv[1]).resolve(strict=True)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    process = subprocess.Popen([str(executable), "--smoke-test"], env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        result = process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        raise SystemExit("Packaged startup timed out (possibly a DLL error dialog).")
    if result:
        raise SystemExit(f"Packaged startup failed with exit code {result}.")
    print(f"Packaged startup passed: {executable}")


if __name__ == "__main__":
    main()
