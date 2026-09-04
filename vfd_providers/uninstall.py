"""Hand the VFD modules to csf_tz before this app is removed."""

import frappe
from frappe import _

MODULES = ("VFD Providers", "VFD Settings")
SUCCESSOR_APP = "csf_tz"


def before_uninstall():
	"""csf_tz ships the VFD doctypes now, so removing this app must not drop their tables.

	frappe.installer.remove_app deletes every DocType whose module belongs to the app being
	removed. csf_tz reassigns these two modules to itself, but only when its patches run. An
	operator who uninstalls before migrating would otherwise destroy the fiscal receipt history.
	"""
	if not is_successor_installed():
		refuse_to_drop_populated_modules()
		return

	for module in owned_modules():
		frappe.db.set_value("Module Def", module, "app_name", SUCCESSOR_APP, update_modified=False)
		print(f"Handing Module '{module}' over to {SUCCESSOR_APP}")


def is_successor_installed():
	return SUCCESSOR_APP in frappe.get_installed_apps()


def owned_modules():
	return frappe.get_all(
		"Module Def",
		filters={"name": ["in", MODULES], "app_name": "vfd_providers"},
		pluck="name",
	)


def refuse_to_drop_populated_modules():
	"""Stop the uninstall while it would still take live records with it."""
	populated = get_populated_doctypes()
	if not populated:
		return

	records = "<br>".join(f"{doctype}: {count} record(s)" for doctype, count in populated.items())
	frappe.throw(
		_(
			"Uninstalling vfd_providers would drop these tables, because csf_tz is not installed to take"
			" over the VFD Providers and VFD Settings modules:<br><br>{0}<br><br>"
			"Install csf_tz and run bench migrate first. It adopts both modules and the data survives."
		).format(records),
		title=_("VFD Data Would Be Lost"),
	)


def get_populated_doctypes():
	"""Map each DocType of the owned modules to its record count, skipping the empty ones."""
	modules = owned_modules()
	if not modules:
		return {}

	counts = {}
	for doctype in frappe.get_all("DocType", filters={"module": ["in", modules]}, pluck="name"):
		count = frappe.db.count(doctype)
		if count:
			counts[doctype] = count
	return counts
