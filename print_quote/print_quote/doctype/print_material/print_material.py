# SPDX-License-Identifier: AGPL-3.0-or-later
from frappe.model.document import Document


class PrintMaterial(Document):
	def colour_options(self):
		return [c.strip() for c in (self.colours or "").splitlines() if c.strip()]
