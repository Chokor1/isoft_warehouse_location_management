from . import __version__ as app_version

app_name = "isoft_warehouse_location_management"
app_title = "Isoft Location Manager"
app_publisher = "Abbass Chokor"
app_description = "Item location management inside ERPNext transactions"
app_icon = "octicon octicon-package"
app_color = "#0f766e"
app_email = "abbasschokor225@gmail.com"
app_license = "MIT"

# The Picking Sheet print format calls these.
jenv = {
	"methods": [
		"picking_sheet_lines:isoft_warehouse_location_management.isoft_location_manager.picking_sheet.picking_lines",
		"picking_sheet_header:isoft_warehouse_location_management.isoft_location_manager.picking_sheet.sheet_header",
	]
}

# ------------------------------------------------------------------
# Includes
# ------------------------------------------------------------------
# Navbar icon (role-gated) that links to the Isoft Location Manager dashboard.
app_include_css = "/assets/isoft_warehouse_location_management/css/isoft_warehouse_location_management.css"

app_include_js = [
	"/assets/isoft_warehouse_location_management/js/isoft_warehouse_location_management_icon.js",
	"/assets/isoft_warehouse_location_management/js/location_control.js",
	"/assets/isoft_warehouse_location_management/js/picking_sheet.js",
]

# Form customisation.
doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
	"Stock Entry": "public/js/stock_entry.js",
	"Delivery Note": "public/js/delivery_note.js",
	"Purchase Receipt": "public/js/purchase.js",
	"Purchase Invoice": "public/js/purchase.js",
}

# Mirror Stock Entry location picks into Location Stock Movements (cost-free).
doc_events = {
	"Stock Entry": {
		"validate": "isoft_warehouse_location_management.isoft_location_manager.stock_entry_hooks.validate",
		"before_submit": "isoft_warehouse_location_management.isoft_location_manager.stock_entry_hooks.before_submit",
		"on_submit": "isoft_warehouse_location_management.isoft_location_manager.stock_entry_hooks.on_submit",
		"on_cancel": "isoft_warehouse_location_management.isoft_location_manager.stock_entry_hooks.on_cancel",
	},
	# Documents that ship goods: capture the shelf, then mirror it. POS is included for
	# free, since a POS sale is a Sales Invoice that updates stock.
	"Delivery Note": {
		"validate": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.validate",
		"before_submit": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.before_submit",
		"on_submit": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.on_submit",
		"on_cancel": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.on_cancel",
	},
	"Sales Invoice": {
		"validate": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.validate",
		"before_submit": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.before_submit",
		"on_submit": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.on_submit",
		"on_cancel": "isoft_warehouse_location_management.isoft_location_manager.sales_hooks.on_cancel",
	},
	# Goods arriving: an optional put-away location, mirrored on submit. A purchase is
	# never refused over a location — a line left blank is unassigned stock.
	"Purchase Receipt": {
		"validate": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.validate",
		"before_submit": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.before_submit",
		"on_submit": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.on_submit",
		"on_cancel": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.on_cancel",
	},
	"Purchase Invoice": {
		"validate": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.validate",
		"before_submit": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.before_submit",
		"on_submit": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.on_submit",
		"on_cancel": "isoft_warehouse_location_management.isoft_location_manager.purchase_hooks.on_cancel",
	},
	# Every leaf warehouse owns an Unassigned Stock location from the moment it exists.
	"Warehouse": {
		"after_insert": "isoft_warehouse_location_management.isoft_location_manager.doctype.warehouse_location.warehouse_location.on_warehouse_insert",
	},
}

# ------------------------------------------------------------------
# Installation
# ------------------------------------------------------------------
after_install = "isoft_warehouse_location_management.isoft_location_manager.install.after_install"
after_migrate = "isoft_warehouse_location_management.isoft_location_manager.install.after_install"

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
fixtures = [
	{
		"doctype": "Role",
		"filters": [["role_name", "in", ["Location Manager"]]],
	},
]
