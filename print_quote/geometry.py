# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mesh analysis for uploaded models (pure Python, no dependencies): STL (binary or ASCII) and 3MF.
Volume is the signed-tetrahedron sum over the triangles (exact for a closed mesh; the absolute value
is taken so face winding doesn't matter), plus the bounding box. Units: STL is unitless and is read as
millimetres (the slicer convention); 3MF honours its declared unit."""

import io
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

MAX_TRIANGLES = 2_000_000  # beyond this a model is refused rather than analysed (memory/CPU bound)
MAX_3MF_UNCOMPRESSED = 300 * 1024 * 1024  # zip-bomb guard
MM_PER_UNIT = {
	"micron": 0.001,
	"millimeter": 1.0,
	"centimeter": 10.0,
	"inch": 25.4,
	"foot": 304.8,
	"meter": 1000.0,
}


class MeshError(ValueError):
	"""The file is not a usable STL/3MF model (unreadable, empty, too large, or not closed)."""


@dataclass(frozen=True)
class Mesh:
	triangles: int
	volume_cm3: float
	size_mm: tuple  # (x, y, z) bounding-box extents

	def fits(self, build_volume_mm):
		"""True when the part fits the (x, y, z) build volume in some axis-aligned orientation."""
		return all(d <= b for d, b in zip(sorted(self.size_mm), sorted(build_volume_mm), strict=True))


def _accumulate(triangles):
	"""(count, volume mm³, bbox) from an iterable of ((x,y,z),(x,y,z),(x,y,z)) triangles."""
	count, six_volume = 0, 0.0
	lo, hi = [float("inf")] * 3, [float("-inf")] * 3
	for a, b, c in triangles:
		count += 1
		if count > MAX_TRIANGLES:
			raise MeshError(f"model has more than {MAX_TRIANGLES:,} triangles")
		six_volume += (
			a[0] * (b[1] * c[2] - b[2] * c[1])
			- a[1] * (b[0] * c[2] - b[2] * c[0])
			+ a[2] * (b[0] * c[1] - b[1] * c[0])
		)
		for v in (a, b, c):
			for i in range(3):
				lo[i] = min(lo[i], v[i])
				hi[i] = max(hi[i], v[i])
	if not count:
		raise MeshError("model has no triangles")
	return count, abs(six_volume) / 6.0, tuple(round(hi[i] - lo[i], 3) for i in range(3))


def _mesh(count, volume_mm3, size_mm, scale=1.0):
	volume_cm3 = volume_mm3 * scale**3 / 1000.0
	if volume_cm3 <= 0:
		raise MeshError("model encloses no volume (open or flat mesh)")
	return Mesh(count, round(volume_cm3, 4), tuple(round(d * scale, 3) for d in size_mm))


def _binary_stl(data):
	(count,) = struct.unpack_from("<I", data, 80)
	if 84 + count * 50 != len(data):
		raise MeshError("binary STL length does not match its triangle count")
	if count > MAX_TRIANGLES:
		raise MeshError(f"model has more than {MAX_TRIANGLES:,} triangles")

	def triangles():
		for i in range(count):
			v = struct.unpack_from("<9f", data, 84 + i * 50 + 12)
			yield (v[0:3], v[3:6], v[6:9])

	return _mesh(*_accumulate(triangles()))


def _ascii_stl(text):
	def triangles():
		vertices = []
		for line in text.splitlines():
			parts = line.split()
			if parts[:1] == ["vertex"]:
				vertices.append(tuple(float(p) for p in parts[1:4]))
				if len(vertices) == 3:
					yield tuple(vertices)
					vertices = []

	return _mesh(*_accumulate(triangles()))


def analyse_stl(data):
	"""Mesh for STL bytes (binary detected by its exact length, else parsed as ASCII)."""
	if len(data) >= 84 and 84 + struct.unpack_from("<I", data, 80)[0] * 50 == len(data):
		return _binary_stl(data)
	try:
		text = data.decode("ascii")
	except UnicodeDecodeError as e:
		raise MeshError("not a binary or ASCII STL file") from e
	if not text.lstrip().startswith("solid"):
		raise MeshError("not a binary or ASCII STL file")
	try:
		return _ascii_stl(text)
	except ValueError as e:
		if isinstance(e, MeshError):
			raise
		raise MeshError("malformed ASCII STL") from e


def analyse_3mf(data):
	"""Mesh for a 3MF package: every <object><mesh> in the 3D model part(s), in the declared unit."""
	try:
		package = zipfile.ZipFile(io.BytesIO(data))
	except zipfile.BadZipFile as e:
		raise MeshError("not a 3MF (zip) package") from e
	parts = [i for i in package.infolist() if i.filename.lower().endswith(".model")]
	if not parts:
		raise MeshError("3MF package has no 3D model part")
	if sum(i.file_size for i in parts) > MAX_3MF_UNCOMPRESSED:
		raise MeshError("3MF model part is too large")
	total_count, total_volume, lo, hi, scale = 0, 0.0, [float("inf")] * 3, [float("-inf")] * 3, 1.0
	for part in parts:
		try:
			root = ET.fromstring(package.read(part))
		except ET.ParseError as e:
			raise MeshError("malformed 3MF model XML") from e
		scale = MM_PER_UNIT.get(root.get("unit", "millimeter"), 1.0)
		for mesh in root.iter():
			if not mesh.tag.endswith("}mesh"):
				continue
			verts = [
				(float(v.get("x")), float(v.get("y")), float(v.get("z")))
				for v in mesh.iter()
				if v.tag.endswith("}vertex")
			]
			tris = (
				(verts[int(t.get("v1"))], verts[int(t.get("v2"))], verts[int(t.get("v3"))])
				for t in mesh.iter()
				if t.tag.endswith("}triangle")
			)
			count, volume, size = _accumulate(tris)
			total_count += count
			total_volume += volume
			for i in range(3):
				lo[i] = min(lo[i], min(v[i] for v in verts))
				hi[i] = max(hi[i], max(v[i] for v in verts))
	if not total_count:
		raise MeshError("3MF package contains no mesh")
	return _mesh(total_count, total_volume, tuple(hi[i] - lo[i] for i in range(3)), scale)


def analyse(filename, data):
	"""Mesh for an uploaded model, by extension (.stl / .3mf)."""
	name = (filename or "").lower()
	if name.endswith(".stl"):
		return analyse_stl(data)
	if name.endswith(".3mf"):
		return analyse_3mf(data)
	raise MeshError("only .stl and .3mf files can be quoted")
