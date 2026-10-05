# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional refinement: slice the model with a headless PrusaSlicer/OrcaSlicer CLI and read its own
grams + print-time estimate from the G-code summary comments. Used only when a profile names a
slicer binary; any failure falls back to the geometric estimate. Bounded by a timeout."""

import re
import subprocess
import tempfile
from pathlib import Path

SLICE_TIMEOUT_SECONDS = 120
GRAMS = re.compile(r"^;\s*(?:total )?filament used \[g\]\s*=\s*([\d.]+)", re.M)
TIME = re.compile(r"^;\s*estimated printing time(?: \(normal mode\))?\s*=\s*(.+)$", re.M)
DURATION_PART = re.compile(r"(\d+)\s*([dhms])")
SECONDS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text):
	"""PrusaSlicer's "1d 2h 3m 4s" → hours (float)."""
	return sum(int(n) * SECONDS[u] for n, u in DURATION_PART.findall(text or "")) / 3600


def parse_gcode_summary(gcode_text):
	"""(grams, hours) from a G-code file's summary comments, or None if either is missing."""
	grams, time = GRAMS.search(gcode_text), TIME.search(gcode_text)
	if not (grams and time):
		return None
	return float(grams.group(1)), round(parse_duration(time.group(1)), 3)


def slice_estimate(slicer_path, config_path, filename, data):
	"""(grams, hours) from a real slice, or None (no slicer, timeout, failure, unparsable output)."""
	if not slicer_path:
		return None
	with tempfile.TemporaryDirectory(prefix="print_quote_") as tmp:
		model = Path(tmp) / Path(filename).name
		model.write_bytes(data)
		gcode = Path(tmp) / "out.gcode"
		command = [slicer_path, "--export-gcode", "--output", str(gcode), str(model)]
		if config_path:
			command[1:1] = ["--load", config_path]
		try:
			subprocess.run(command, capture_output=True, timeout=SLICE_TIMEOUT_SECONDS, check=True)
		except OSError, subprocess.SubprocessError:
			return None
		if not gcode.exists():
			return None
		return parse_gcode_summary(gcode.read_text(errors="replace"))
