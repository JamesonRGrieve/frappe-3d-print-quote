# SPDX-License-Identifier: AGPL-3.0-or-later
"""3D-print quote tests: mesh analysis on known solids (STL ASCII + binary, 3MF with units), the
pricing model, the slicer summary parser, and the full request → Lead → Quotation flow on the real
test DB (ERPNext fixtures)."""

import io
import struct
import zipfile
from decimal import Decimal

import frappe
from frappe.tests.utils import FrappeTestCase

from print_quote import geometry, pricing, slicer
from print_quote.quote import Upload, create_request

PROFILE = "_Test Print Profile"
MATERIAL = "_Test PLA"
SERVICE_ITEM = "_Test Print Service"

CUBE_VERTS = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_TRIS = [
	(0, 2, 1),
	(0, 3, 2),
	(4, 5, 6),
	(4, 6, 7),
	(0, 1, 5),
	(0, 5, 4),
	(1, 2, 6),
	(1, 6, 5),
	(2, 3, 7),
	(2, 7, 6),
	(3, 0, 4),
	(3, 4, 7),
]


def cube(side):
	return [tuple(tuple(c * side for c in CUBE_VERTS[i]) for i in tri) for tri in CUBE_TRIS]


def ascii_stl(triangles):
	lines = ["solid cube"]
	for tri in triangles:
		lines += [
			"facet normal 0 0 0",
			"outer loop",
			*(f"vertex {x} {y} {z}" for x, y, z in tri),
			"endloop",
			"endfacet",
		]
	return ("\n".join([*lines, "endsolid cube"]) + "\n").encode()


def binary_stl(triangles):
	body = b"".join(struct.pack("<12fH", 0, 0, 0, *[c for v in tri for c in v], 0) for tri in triangles)
	return b"\0" * 80 + struct.pack("<I", len(triangles)) + body


def three_mf(side, unit="millimeter"):
	verts = "".join(f'<vertex x="{x * side}" y="{y * side}" z="{z * side}"/>' for x, y, z in CUBE_VERTS)
	tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in CUBE_TRIS)
	model = (
		f'<?xml version="1.0"?><model unit="{unit}" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
		f'<resources><object id="1" type="model"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles>'
		'</mesh></object></resources><build><item objectid="1"/></build></model>'
	)
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as z:
		z.writestr("3D/3dmodel.model", model)
	return buffer.getvalue()


class TestGeometryPricing(FrappeTestCase):
	def test_stl_ascii_and_binary_cube(self):
		for data in (ascii_stl(cube(10)), binary_stl(cube(10))):
			mesh = geometry.analyse_stl(data)
			self.assertEqual((mesh.triangles, mesh.volume_cm3, mesh.size_mm), (12, 1.0, (10.0, 10.0, 10.0)))

	def test_winding_does_not_change_volume(self):
		flipped = [(a, c, b) for a, b, c in cube(20)]
		self.assertEqual(geometry.analyse_stl(ascii_stl(flipped)).volume_cm3, 8.0)

	def test_3mf_units(self):
		self.assertEqual(geometry.analyse_3mf(three_mf(10)).volume_cm3, 1.0)
		mesh = geometry.analyse_3mf(three_mf(1, unit="centimeter"))
		self.assertEqual((mesh.volume_cm3, mesh.size_mm), (1.0, (10.0, 10.0, 10.0)))

	def test_bad_models_rejected(self):
		for name, data in (
			("x.stl", b"not a model"),
			("x.3mf", b"PK not zip"),
			("x.obj", b"v 0 0 0"),
			("flat.stl", ascii_stl([((0, 0, 0), (1, 0, 0), (0, 1, 0))])),
		):
			with self.subTest(name=name), self.assertRaises(geometry.MeshError):
				geometry.analyse(name, data)

	def test_fits_any_orientation(self):
		mesh = geometry.Mesh(12, 1.0, (300.0, 10.0, 10.0))
		self.assertTrue(mesh.fits((10, 10, 300)))
		self.assertFalse(mesh.fits((250, 210, 210)))

	def test_pricing(self):
		rates = pricing.Rates(
			Decimal("1.25"), Decimal("0.10"), Decimal("0.4"), Decimal("10"), Decimal("3"), Decimal("1")
		)
		part = pricing.estimate_part(10, rates)  # 10 cm³ × 1.25 × 0.4 = 5 g; 0.5 h
		self.assertEqual(
			(part.grams, part.hours, part.unit_price), (Decimal("5.0"), Decimal("0.50"), Decimal("3.00"))
		)
		self.assertEqual(pricing.estimate_part(10, rates, slicer=(8, 2)).unit_price, Decimal("7.80"))
		self.assertEqual(pricing.request_total([(Decimal("3.00"), 2)], 10, 5, 0), Decimal("11.60"))
		self.assertEqual(pricing.request_total([(Decimal("3.00"), 1)], 0, 0, 25), Decimal("25.00"))

	def test_slicer_summary_parser(self):
		gcode = "G1 X0\n; filament used [g] = 12.34\n; estimated printing time (normal mode) = 1h 2m 30s\n"
		self.assertEqual(slicer.parse_gcode_summary(gcode), (12.34, round(1 + 2 / 60 + 30 / 3600, 3)))
		self.assertIsNone(slicer.parse_gcode_summary("G1 X0\n"))
		self.assertIsNone(slicer.slice_estimate(None, None, "x.stl", b""))


class TestQuoteRequest(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Item", SERVICE_ITEM):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": SERVICE_ITEM,
					"item_name": "3D printing",
					"item_group": "_Test Item Group",
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert()
		if not frappe.db.exists("Print Material", MATERIAL):
			frappe.get_doc(
				{
					"doctype": "Print Material",
					"material_name": MATERIAL,
					"print_process": "FDM",
					"density": 1.25,
					"price_per_gram": 0.10,
					"colours": "Black\nWhite",
				}
			).insert()
		if not frappe.db.exists("Print Quote Profile", PROFILE):
			frappe.get_doc(
				{
					"doctype": "Print Quote Profile",
					"profile_name": PROFILE,
					"enabled": 1,
					"company": "_Test Company",
					"item": SERVICE_ITEM,
					"materials": [{"material": MATERIAL}],
					"fill_fraction": 40,
					"throughput_g_per_h": 10,
					"machine_rate_per_h": 3,
					"per_part_fee": 1,
					"setup_fee": 5,
					"minimum_order": 0,
					"markup_percent": 10,
					"max_file_mb": 1,
					"max_quantity": 5,
					"max_files": 3,
					"build_x_mm": 250,
					"build_y_mm": 210,
					"build_z_mm": 210,
				}
			).insert()

	def tearDown(self):
		frappe.db.rollback()

	contact = {"contact_name": "Test Buyer", "email": "pq-buyer@example.com"}

	def test_request_creates_lead_and_matching_quotation(self):
		cube10 = ascii_stl(cube(21.5443469))  # ≈ 10 cm³ → 5 g, 0.5 h → 3.00 per part
		request = create_request(
			PROFILE, self.contact, [Upload("bracket.stl", cube10, MATERIAL, "Black", 2)], "PETG ok"
		)
		self.assertEqual(request.status, "Estimated")  # review before send → draft quotation
		row = request.files[0]
		self.assertAlmostEqual(row.volume_cm3, 10.0, places=2)
		self.assertEqual((row.estimate_source, row.unit_price), ("Geometry", 3.0))
		self.assertTrue(frappe.db.get_value("File", {"file_url": row.model_file}, "is_private"))
		self.assertEqual(request.estimated_total, 11.6)  # 2 × 3.00 × 1.10 + 5 setup
		quotation = frappe.get_doc("Quotation", request.quotation)
		self.assertEqual(
			(quotation.docstatus, quotation.quotation_to, quotation.party_name), (0, "Lead", request.lead)
		)
		self.assertEqual(quotation.net_total, request.estimated_total)
		self.assertEqual(frappe.db.get_value("Lead", request.lead, "email_id"), "pq-buyer@example.com")
		again = create_request(PROFILE, self.contact, [Upload("b.stl", cube10, MATERIAL, "", 1)])
		self.assertEqual(again.lead, request.lead)  # same open Lead reused

	def test_limits_are_enforced(self):
		ok = ascii_stl(cube(10))
		for upload in (
			Upload("a.stl", ok, "Nylon", "", 1),  # material not offered
			Upload("a.stl", ok, MATERIAL, "Purple", 1),  # colour not offered
			Upload("a.stl", ok, MATERIAL, "", 6),  # quantity above max
			Upload("a.stl", b"x" * (2 * 1024 * 1024), MATERIAL, "", 1),  # above 1 MB
			Upload("a.stl", ascii_stl(cube(260)), MATERIAL, "", 1),  # too big for the printer
			Upload("a.step", ok, MATERIAL, "", 1),
		):  # unsupported format
			with self.subTest(
				upload=upload.filename + upload.material + upload.colour + str(upload.quantity)
			):
				with self.assertRaises(frappe.ValidationError):
					create_request(PROFILE, self.contact, [upload])
		with self.assertRaises(frappe.ValidationError):
			create_request(
				PROFILE, self.contact, [Upload("a.stl", ok, MATERIAL, "", 1)] * 4
			)  # too many files

	def test_minimum_order_is_a_quotation_line(self):
		frappe.db.set_value("Print Quote Profile", PROFILE, {"minimum_order": 50, "setup_fee": 0})
		request = create_request(
			PROFILE, self.contact, [Upload("a.stl", ascii_stl(cube(10)), MATERIAL, "", 1)]
		)
		quotation = frappe.get_doc("Quotation", request.quotation)
		self.assertEqual((request.estimated_total, quotation.net_total), (50.0, 50.0))
