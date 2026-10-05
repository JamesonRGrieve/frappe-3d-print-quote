# SPDX-License-Identifier: AGPL-3.0-or-later
from decimal import Decimal

import frappe
from frappe import _
from frappe.model.document import Document

from print_quote.pricing import Rates


class PrintQuoteProfile(Document):
	def validate(self):
		if frappe.db.get_value("Item", self.item, "is_stock_item"):
			frappe.throw(_("The quotation item must be a non-stock (service) item."))
		if not self.throughput_g_per_h:
			frappe.throw(_("Throughput must be above zero."))

	def material_names(self):
		return [row.material for row in self.materials]

	def build_volume(self):
		return (self.build_x_mm, self.build_y_mm, self.build_z_mm)

	def rates(self, material):
		"""The pricing Rates for ``material`` (a Print Material) under this profile."""
		return Rates(
			density_g_cm3=Decimal(str(material.density)),
			price_per_gram=Decimal(str(material.price_per_gram)),
			fill_fraction=Decimal(str(self.fill_fraction or 0)) / 100,
			throughput_g_per_h=Decimal(str(self.throughput_g_per_h)),
			machine_rate_per_h=Decimal(str(self.machine_rate_per_h or 0)),
			per_part_fee=Decimal(str(self.per_part_fee or 0)),
		)
