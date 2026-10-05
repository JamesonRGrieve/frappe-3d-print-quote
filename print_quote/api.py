# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public endpoints for the quote widget. Uploads are accepted here, with this app's own checks
(extension, size, count, model validity) and a per-IP rate limit, rather than by enabling Frappe's
site-wide guest file uploads.

A visitor is the Guest user, who has no access to Lead or Quotation. ERPNext re-reads the Lead with
the session user's permissions while validating the Quotation (``get_lead_details``), so a
per-document ``ignore_permissions`` cannot reach it: the request is built as Administrator, inside
this boundary only, after the visitor's input has passed this app's own checks."""

import json
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from print_quote.quote import Upload, create_request

SUBMIT_LIMIT_PER_HOUR = 10
SECONDS_PER_HOUR = 3600
QUOTE_BUILDER_USER = "Administrator"


@contextmanager
def as_quote_builder():
	"""Run as the quote builder, always restoring the visitor's session user."""
	visitor = frappe.session.user
	frappe.set_user(QUOTE_BUILDER_USER)
	try:
		yield
	finally:
		frappe.set_user(visitor)


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
	result = request_quote(profile, contact, uploads, notes)
	frappe.db.commit()
	return result


def request_quote(profile, contact, uploads, notes=None):
	"""Build the request, Lead and Quotation for a visitor; return what the widget shows."""
	with as_quote_builder():
		request = create_request(profile, contact, uploads, notes)
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
