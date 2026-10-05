# SPDX-License-Identifier: AGPL-3.0-or-later
from . import __version__ as _version

app_name = "print_quote"
app_title = "3D Print Quote"
app_publisher = "Zephyrex Technologies Limited"
app_description = "3D-printing quotes for Frappe/ERPNext: STL/3MF upload, instant estimate, priced Quotation"
app_email = "jameson@zephyrex.ca"
app_license = "AGPL-3.0-or-later"
app_version = _version

required_apps = ["frappe", "erpnext"]
