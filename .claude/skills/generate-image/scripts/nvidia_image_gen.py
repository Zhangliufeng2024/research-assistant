#!/usr/bin/env python3
"""
Compatibility wrapper — delegates to unified generate_image.py.

For NVIDIA NIM, set IMAGE_API_KEY to your NVIDIA key (starts with "nvapi-").
The unified script auto-detects NVIDIA NIM from the key prefix.

This script is kept for backward compatibility. All image generation
now goes through generate_image.py with auto-detected provider.
"""

import sys
from pathlib import Path

# Import and delegate to the unified script
_here = Path(__file__).resolve().parent
_unified = _here / "generate_image.py"

if not _unified.exists():
    print("[ERROR] Unified image generator not found at:", _unified, file=sys.stderr)
    sys.exit(1)

# Run the unified script with the same arguments
if __name__ == "__main__":
    import runpy
    sys.argv[0] = str(_unified)
    runpy.run_path(str(_unified), run_name="__main__")
