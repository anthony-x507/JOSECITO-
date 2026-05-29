#!/usr/bin/env python3
"""
DIGOS — REDIRECT (entrada deprecada)

Este archivo está deprecado y solo redirige al entry point real.
Usa 'python3 digos.py' en su lugar.
"""

import sys
import subprocess


def main():
    print("[DIGOS] ⚠️  main.py está deprecado. Redirigiendo a digos.py...", file=sys.stderr)
    cmd = [sys.executable, "digos.py"] + sys.argv[1:]
    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        print("[DIGOS] ❌ digos.py no encontrado. Asegúrate de estar en el directorio correcto.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()