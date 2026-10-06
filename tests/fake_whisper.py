"""Stands in for `python -m whisper` in tests: records its arguments and writes a captured JSON output.

FAKE_WHISPER_ARGV names a file to record the arguments in. FAKE_WHISPER_SKIP makes it behave like
Whisper does when transcribing one file raises: report on stdout, write nothing, exit 0.
FAKE_WHISPER_CRASH makes it die with a traceback on stderr, as when the model cannot load.
"""

import json
import os
import shutil
import sys
from pathlib import Path

SAMPLE = Path(__file__).parent / "fixtures" / "whisper_large_v3.json"

args = sys.argv[1:]
Path(os.environ["FAKE_WHISPER_ARGV"]).write_text(json.dumps(args))

if crash := os.environ.get("FAKE_WHISPER_CRASH"):
    print("Traceback (most recent call last):", file=sys.stderr)
    print('  File "whisper/__init__.py", line 150, in load_model', file=sys.stderr)
    print(crash, file=sys.stderr)
    sys.exit(1)

audio = Path(args[0])
if skip := os.environ.get("FAKE_WHISPER_SKIP"):
    print("Traceback (most recent call last):", file=sys.stderr)
    print(skip, file=sys.stderr)
    print(f"Skipping {audio} due to {skip}")
    sys.exit(0)

output_dir = Path(args[args.index("--output_dir") + 1])
shutil.copy(SAMPLE, output_dir / f"{audio.stem}.json")
