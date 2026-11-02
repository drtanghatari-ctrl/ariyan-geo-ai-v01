"""Entry point for the Windows .exe (PyInstaller)."""
import sys

from ariyan_win.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
