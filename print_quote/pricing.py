# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pricing model (pure, unit-tested). Per part:

	grams      = volume_cm3 × density × fill_fraction      (shells + infill as a fraction of solid)
	hours      = grams ÷ throughput_g_per_h                  (material throughput of the process)
	unit price = grams × price_per_gram + hours × machine_rate + per_part_fee

A request total is Σ(unit × qty) × (1 + markup) + setup_fee, never below the minimum order. A
slicer estimate (grams, hours), when available, replaces the geometric one for that part."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value):
	return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Rates:
	density_g_cm3: Decimal
	price_per_gram: Decimal
	fill_fraction: Decimal
	throughput_g_per_h: Decimal
	machine_rate_per_h: Decimal
	per_part_fee: Decimal


@dataclass(frozen=True)
class PartEstimate:
	grams: Decimal
	hours: Decimal
	unit_price: Decimal


def estimate_part(volume_cm3, rates, slicer=None):
	"""Estimate one part; ``slicer`` = (grams, hours) from a real slice overrides the geometry."""
	if slicer:
		grams, hours = Decimal(str(slicer[0])), Decimal(str(slicer[1]))
	else:
		grams = Decimal(str(volume_cm3)) * rates.density_g_cm3 * rates.fill_fraction
		hours = grams / rates.throughput_g_per_h if rates.throughput_g_per_h else Decimal(0)
	unit = grams * rates.price_per_gram + hours * rates.machine_rate_per_h + rates.per_part_fee
	return PartEstimate(
		grams.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
		hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
		money(unit),
	)


def request_total(lines, markup_percent, setup_fee, minimum_order):
	"""Total for [(unit_price, qty)], with markup, setup fee and the minimum order applied."""
	subtotal = sum((Decimal(str(unit)) * int(qty) for unit, qty in lines), Decimal(0))
	total = subtotal * (1 + Decimal(str(markup_percent or 0)) / 100) + Decimal(str(setup_fee or 0))
	return money(max(total, Decimal(str(minimum_order or 0))))


def marked_up(unit_price, markup_percent):
	"""A line's unit price with markup applied (so Quotation lines sum to the quoted total)."""
	return money(Decimal(str(unit_price)) * (1 + Decimal(str(markup_percent or 0)) / 100))
