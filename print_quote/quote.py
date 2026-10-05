# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn an upload into a priced quote: validate against the profile's limits, analyse each model,
estimate it (geometry, or the slicer when configured), store the files privately on a Print Quote
Request, and create the Lead + Quotation whose lines sum exactly to the estimate shown."""

from dataclasses import dataclass
from decimal import Decimal

import frappe
from frappe import _

from print_quote import geometry, pricing, slicer

BYTES_PER_MB = 1024 * 1024
LEAD_SOURCE = "Website"


@dataclass(frozen=True)
class Upload:
	filename: str
	data: bytes
	material: str
	colour: str
	quantity: int


def validate_upload(profile, upload):
	"""Raise a user-facing ValidationError if ``upload`` is outside the profile's limits."""
	if len(upload.data) > profile.max_file_mb * BYTES_PER_MB:
		frappe.throw(_("{0} is larger than {1} MB.").format(upload.filename, profile.max_file_mb))
	if not 1 <= upload.quantity <= profile.max_quantity:
		frappe.throw(
			_("Quantity for {0} must be between 1 and {1}.").format(upload.filename, profile.max_quantity)
		)
	if upload.material not in profile.material_names():
		frappe.throw(_("{0} is not offered here.").format(upload.material))
	colours = frappe.get_cached_doc("Print Material", upload.material).colour_options()
	if upload.colour and colours and upload.colour not in colours:
		frappe.throw(_("{0} is not available in {1}.").format(upload.material, upload.colour))


def estimate_upload(profile, upload):
	"""(mesh, PartEstimate, source) for one validated upload."""
	try:
		mesh = geometry.analyse(upload.filename, upload.data)
	except geometry.MeshError as e:
		frappe.throw(_("{0}: {1}").format(upload.filename, str(e)))
	if not mesh.fits(profile.build_volume()):
		frappe.throw(
			_("{0} ({1} mm) does not fit the printer's build volume.").format(
				upload.filename, " × ".join(f"{d:g}" for d in mesh.size_mm)
			)
		)
	sliced = slicer.slice_estimate(profile.slicer_path, profile.slicer_config, upload.filename, upload.data)
	material = frappe.get_cached_doc("Print Material", upload.material)
	part = pricing.estimate_part(mesh.volume_cm3, profile.rates(material), sliced)
	return mesh, part, "Slicer" if sliced else "Geometry"


def lead_for(contact, company):
	"""The open Lead for this email, or a new one."""
	name = frappe.db.get_value("Lead", {"email_id": contact["email"], "status": ["!=", "Converted"]})
	if name:
		return name
	lead = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": contact["contact_name"],
			"email_id": contact["email"],
			"mobile_no": contact.get("phone"),
			"company_name": contact.get("organization"),
			"source": LEAD_SOURCE if frappe.db.exists("Lead Source", LEAD_SOURCE) else None,
			"company": company,
		}
	)
	lead.insert(ignore_permissions=True)
	return lead.name


def quotation_lines(profile, request):
	"""Quotation item rows: each part at its marked-up unit price, plus setup fee and any shortfall
	to the minimum order, so the Quotation total equals pricing.request_total."""
	rows = [
		{
			"item_code": profile.item,
			"qty": f.quantity,
			"rate": float(pricing.marked_up(f.unit_price, profile.markup_percent)),
			"description": f"{f.file_name}: {f.material}{', ' + f.colour if f.colour else ''} "
			f"({f.size_x_mm:g} × {f.size_y_mm:g} × {f.size_z_mm:g} mm, ~{f.grams:g} g)",
		}
		for f in request.files
	]
	if profile.setup_fee:
		rows.append(
			{
				"item_code": profile.item,
				"qty": 1,
				"rate": float(profile.setup_fee),
				"description": _("Setup fee"),
			}
		)
	subtotal = sum(Decimal(str(r["rate"])) * r["qty"] for r in rows)
	shortfall = Decimal(str(profile.minimum_order or 0)) - subtotal
	if shortfall > 0:
		rows.append(
			{
				"item_code": profile.item,
				"qty": 1,
				"rate": float(pricing.money(shortfall)),
				"description": _("Minimum order adjustment"),
			}
		)
	return rows


def make_quotation(profile, request):
	quotation = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": "Lead",
			"party_name": request.lead,
			"company": profile.company,
			"order_type": "Sales",
			"items": quotation_lines(profile, request),
			"terms": _("Estimate from uploaded models; confirmed before printing."),
		}
	)
	if profile.quotation_series:
		quotation.naming_series = profile.quotation_series
	quotation.insert(ignore_permissions=True)
	if not profile.review_before_send:
		quotation.submit()
	return quotation


def create_request(profile_name, contact, uploads, notes=None):
	"""Validate, estimate and record a quote request; returns the saved Print Quote Request."""
	profile = frappe.get_doc("Print Quote Profile", profile_name)
	if not profile.enabled:
		frappe.throw(_("Quotes are not available right now."))
	if not 1 <= len(uploads) <= profile.max_files:
		frappe.throw(_("Upload between 1 and {0} files.").format(profile.max_files))
	rows = []
	for upload in uploads:
		validate_upload(profile, upload)
		mesh, part, source = estimate_upload(profile, upload)
		rows.append((upload, mesh, part, source))
	request = frappe.get_doc(
		{
			"doctype": "Print Quote Request",
			"profile": profile.name,
			"status": "Estimated",
			"notes": notes,
			**{k: contact.get(k) for k in ("contact_name", "email", "phone", "organization")},
			"files": [
				{
					"file_name": u.filename,
					"material": u.material,
					"colour": u.colour,
					"quantity": u.quantity,
					"triangles": m.triangles,
					"volume_cm3": m.volume_cm3,
					"size_x_mm": m.size_mm[0],
					"size_y_mm": m.size_mm[1],
					"size_z_mm": m.size_mm[2],
					"grams": float(p.grams),
					"hours": float(p.hours),
					"unit_price": float(p.unit_price),
					"estimate_source": s,
				}
				for u, m, p, s in rows
			],
		}
	)
	request.estimated_total = float(
		pricing.request_total(
			[(p.unit_price, u.quantity) for u, _m, p, _s in rows],
			profile.markup_percent,
			profile.setup_fee,
			profile.minimum_order,
		)
	)
	request.insert(ignore_permissions=True)
	for row, (upload, _m, _p, _s) in zip(request.files, rows, strict=True):
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": upload.filename,
				"content": upload.data,
				"is_private": 1,
				"attached_to_doctype": request.doctype,
				"attached_to_name": request.name,
			}
		)
		file.save(ignore_permissions=True)
		row.db_set("model_file", file.file_url)
	request.db_set("lead", lead_for(contact, profile.company))
	quotation = make_quotation(profile, request)
	request.db_set(
		{"quotation": quotation.name, "status": "Quoted" if quotation.docstatus == 1 else "Estimated"}
	)
	return request
