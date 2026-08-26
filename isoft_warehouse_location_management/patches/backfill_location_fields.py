# Copyright (c) 2026, ISOFT LDA
# Author: Abbass Chokor
#
# Second half of the Section -> Location rename.
#
# The doctype renames have to happen BEFORE the model sync, or the sync would build a
# second, empty set of doctypes beside the real data. The *field* renames have to happen
# AFTER it, because Frappe's `rename_field` copies values into a column that the sync has
# not created yet — run early it just prints "not found" and does nothing.
#
# So this patch carries the values across, removes the columns and custom fields left
# behind, and re-points the indexes at their new column names.

import frappe

FIELDS = [
	("Warehouse Location", "section_code", "location_code"),
	("Warehouse Location", "section_name", "location_name"),
	("Warehouse Location", "section_type", "location_type"),
	("Warehouse Location", "section_details", "putaway_rules_section"),
	("Location Stock", "section", "location"),
	("Location Stock Movement Item", "source_section", "source_location"),
	("Location Stock Movement Item", "target_section", "target_location"),
	("Delivery Preparation Request Item", "section", "location"),
	("Stock Entry Detail", "custom_from_section", "custom_from_location"),
	("Stock Entry Detail", "custom_to_section", "custom_to_location"),
	("Stock Entry Detail", "custom_section_allocation", "custom_location_allocation"),
	("Delivery Note Item", "custom_from_section", "custom_from_location"),
	("Delivery Note Item", "custom_section_allocation", "custom_location_allocation"),
	("Sales Invoice Item", "custom_from_section", "custom_from_location"),
	("Sales Invoice Item", "custom_section_allocation", "custom_location_allocation"),
	("Warehouse", "custom_section_prefix", "custom_location_prefix"),
]

STALE_CUSTOM_FIELDS = [
	("Stock Entry Detail", "custom_from_section"),
	("Stock Entry Detail", "custom_to_section"),
	("Stock Entry Detail", "custom_section_allocation"),
	("Delivery Note Item", "custom_from_section"),
	("Delivery Note Item", "custom_section_allocation"),
	("Sales Invoice Item", "custom_from_section"),
	("Sales Invoice Item", "custom_section_allocation"),
	("Warehouse", "custom_section_prefix"),
	("Item", "custom_picking_section_break"),
	("Item", "custom_default_sections"),
]

INDEXES = [
	("tabLocation Stock", "unique_location_item", True, ["warehouse", "location", "item_code"]),
	("tabLocation Stock", "wh_item_index", False, ["warehouse", "item_code"]),
	("tabWarehouse Location", "unique_warehouse_code", True, ["warehouse", "location_code"]),
	("tabDelivery Preparation Request Item", "location_item_index", False, ["location", "item_code"]),
]

# an index still naming the old column pins that column in place
LEGACY_INDEXES = [
	("tabLocation Stock", "unique_location_item"),
	("tabLocation Stock", "unique_section_item"),
	("tabWarehouse Location", "unique_warehouse_code"),
	("tabDelivery Preparation Request Item", "location_item_index"),
	("tabDelivery Preparation Request Item", "section_item_index"),
]


def execute():
	moved = 0
	for doctype, old, new in FIELDS:
		moved += _carry_over(doctype, old, new)

	for doctype, fieldname in STALE_CUSTOM_FIELDS:
		_drop_custom_field(doctype, fieldname)

	# an index naming the old column pins that column in place, so the keys go first
	for table, name in LEGACY_INDEXES:
		_drop_index(table, name)
	for doctype, old, _new in FIELDS:
		_drop_column(doctype, old)
	_rebuild_indexes()
	frappe.clear_cache()
	frappe.db.commit()
	print("Isoft Location Manager: carried {0} column(s) over to their location names".format(moved))


# ======================================================================
def _columns(doctype):
	try:
		return {c[0] for c in frappe.db.sql("show columns from `tab{0}`".format(doctype))}
	except Exception:
		return set()


def _carry_over(doctype, old, new):
	cols = _columns(doctype)
	if old not in cols or new not in cols:
		return 0
	# only fill what the sync left empty, so re-running this can never clobber real edits
	frappe.db.sql(
		"""update `tab{0}` set `{1}` = `{2}`
		where ifnull(`{1}`, '') = '' and ifnull(`{2}`, '') != ''""".format(doctype, new, old)
	)
	return 1


def _drop_custom_field(doctype, fieldname):
	name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname}, "name")
	if not name:
		return
	frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)


def _drop_column(doctype, column):
	cols = _columns(doctype)
	if column not in cols:
		return
	# a column Frappe no longer knows about is a trap for the next person reading the table
	try:
		frappe.db.sql("alter table `tab{0}` drop column `{1}`".format(doctype, column))
	except Exception:
		frappe.log_error(
			title="Isoft Location Manager: dropping stale column failed",
			message="{0}.{1}".format(doctype, column),
		)


def _drop_index(table, name):
	try:
		if frappe.db.sql("show index from `{0}` where Key_name = %s".format(table), name):
			frappe.db.sql("alter table `{0}` drop index `{1}`".format(table, name))
	except Exception:
		frappe.log_error(
			title="Isoft Location Manager: dropping legacy index failed", message="{0}.{1}".format(table, name)
		)


def _rebuild_indexes():
	"""Point the indexes at the new column names; the old ones went with the columns."""
	for table, name, unique, cols in INDEXES:
		try:
			existing = frappe.db.sql(
				"show index from `{0}` where Key_name = %s".format(table), name, as_dict=True
			)
			have = [r["Column_name"] for r in sorted(existing, key=lambda r: r["Seq_in_index"])]
			if have == cols:
				continue
			if existing:
				frappe.db.sql("alter table `{0}` drop index `{1}`".format(table, name))
			frappe.db.sql(
				"alter table `{0}` add {1} `{2}` ({3})".format(
					table,
					"unique" if unique else "index",
					name,
					", ".join("`{0}`".format(c) for c in cols),
				)
			)
		except Exception:
			frappe.log_error(
				title="Isoft Location Manager: index rebuild failed", message="{0}.{1}".format(table, name)
			)
