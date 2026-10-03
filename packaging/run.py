"""Entry point for the standalone app files built with PyInstaller (double-click to open leadhound)."""
import sys

from leadhound.cli import main

if __name__ == "__main__":
    sys.exit(main())
