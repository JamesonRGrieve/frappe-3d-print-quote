# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public endpoints for the quote widget. Uploads are accepted here, with this app's own checks
(extension, size, count, model validity) and a per-IP rate limit, rather than by enabling Frappe's
site-wide guest file uploads."""

import json

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from print_quote.quote import Upload, create_request

SUBMIT_LIMIT_PER_HOUR = 10
SECONDS_PER_HOUR = 3600


@frappe.whitelist(allow_guest=True)
def get_profile(profile):
	"""What the widget offers: materials (with colours) and the upload limits."""
	doc = frappe.get_doc("Print Quote Profile", profile)
	if not doc.enabled:
		raise frappe.DoesNotExistError
	materials = []
	for name in doc.material_names():
		m = frappe.get_cached_doc("Print Material", name)
		if m.enabled:
			materials.append(
				{
					"name": m.name,
					"process": m.print_process,
					"colours": m.colour_options(),
					"description": m.description,
				}
			)
	return {
		"materials": materials,
		"max_file_mb": doc.max_file_mb,
		"max_files": doc.max_files,
		"max_quantity": doc.max_quantity,
		"accept": [".stl", ".3mf"],
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=SUBMIT_LIMIT_PER_HOUR, seconds=SECONDS_PER_HOUR)
def submit(profile, contact_name, email, parts, phone=None, organization=None, notes=None):
	"""Multipart upload: form fields + files named in ``parts`` (JSON list of
	{"field", "material", "colour", "quantity"}). Returns the estimate."""
	files = frappe.request.files
	uploads = []
	for part in json.loads(parts):
		upload = files.get(part.get("field") or "")
		if not upload:
			frappe.throw(_("A file is missing from the upload."))
		uploads.append(
			Upload(
				filename=upload.filename,
				data=upload.stream.read(),
				material=part.get("material"),
				colour=part.get("colour") or "",
				quantity=int(part.get("quantity") or 1),
			)
		)
	contact = {"contact_name": contact_name, "email": email, "phone": phone, "organization": organization}
	request = create_request(profile, contact, uploads, notes)
	frappe.db.commit()
	company, review = frappe.db.get_value("Print Quote Profile", profile, ["company", "review_before_send"])
	return {
		"request": request.name,
		"estimated_total": request.estimated_total,
		"currency": frappe.get_cached_value("Company", company, "default_currency"),
		"review": bool(review),
		"parts": [
			{
				"file": f.file_name,
				"material": f.material,
				"quantity": f.quantity,
				"grams": f.grams,
				"size_mm": [f.size_x_mm, f.size_y_mm, f.size_z_mm],
			}
			for f in request.files
		],
	}
