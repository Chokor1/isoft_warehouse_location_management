"""Why is POS not showing locations? Run on the site in question:

    cd ~/frappe-bench/sites && ../env/bin/python pos_diag.py <site> [item_code]

Checks every condition in order and stops being polite about the first one that fails.
"""
import sys
import frappe

site = sys.argv[1]
item = sys.argv[2] if len(sys.argv) > 2 else None
frappe.init(site=site); frappe.connect()

def line(label, value, good):
    print("  %-40s %-28s %s" % (label, value, "ok" if good else "<-- THIS"))

print("\n=== 1. is the app even here ===")
apps = frappe.get_installed_apps()
line("isoft_warehouse_location_management", "installed" if "isoft_warehouse_location_management" in apps else "NOT INSTALLED",
     "isoft_warehouse_location_management" in apps)
line("posawesome", "installed" if "posawesome" in apps else "NOT INSTALLED", "posawesome" in apps)

print("\n=== 2. is the POS integration switched on (per site) ===")
from isoft_warehouse_location_management.isoft_location_manager.api import setting
for f in ("enabled", "enable_pos", "allow_pick_from_unassigned"):
    v = setting(f)
    line("Picking Settings." + f, v, bool(v) or f == "allow_pick_from_unassigned")

print("\n=== 3. does the till's warehouse have locations ===")
for p in frappe.get_all("POS Profile", fields=["name", "warehouse", "disabled"]):
    if p.disabled:
        continue
    n = frappe.db.count("Warehouse Location", {"warehouse": p.warehouse, "is_active": 1, "is_unassigned": 0})
    line("POS Profile %s -> %s" % (p.name, p.warehouse), "%d active location(s)" % n, n > 0)

print("\n=== 4. is the item actually on a location in THAT warehouse ===")
if not item:
    print("     (pass an item code as the 2nd argument to check one)")
else:
    from isoft_warehouse_location_management.isoft_location_manager.doctype.location_stock.location_stock import (
        bin_qty, unassigned_qty)
    from isoft_warehouse_location_management.isoft_location_manager.pos_api import get_item_location_options
    for p in frappe.get_all("POS Profile", filters={"disabled": 0}, fields=["name", "warehouse"]):
        rows = frappe.db.sql("""select wl.location_code, ls.qty from `tabLocation Stock` ls
                                join `tabWarehouse Location` wl on wl.name = ls.location
                                where ls.warehouse=%s and ls.item_code=%s and ls.qty > 0""",
                             (p.warehouse, item))
        line("%s in %s" % (item, p.warehouse),
             ", ".join("%s=%s" % (c, q) for c, q in rows) or "on no location", bool(rows))
        line("   warehouse total / unassigned",
             "%s / %s" % (bin_qty(p.warehouse, item), unassigned_qty(p.warehouse, item)), True)
        res = get_item_location_options(p.warehouse, item, 1)
        line("   what the till would be sent",
             "%d option(s), default=%s" % (len(res.get("options") or []), res.get("default")),
             bool(res.get("options")))

print("\n=== 5. is the browser running the fork ===")
import os
vue = os.path.expanduser("~/frappe-bench/apps/posawesome/posawesome/public/js/posapp/components/pos/Invoice.vue")
has = os.path.exists(vue) and "isoft_warehouse_location_management" in open(vue, encoding="utf-8").read()
line("Invoice.vue calls the location API", "yes" if has else "NO - upstream posawesome", has)
# the .vue is compiled into the desk bundle, not served as-is
bundle = os.path.expanduser("~/frappe-bench/sites/assets/js/posapp.min.js")
if os.path.exists(bundle):
    built = "isoft_warehouse_location_management" in open(bundle, encoding="utf-8", errors="ignore").read()
    line("and the built bundle contains it",
         "yes" if built else "NO - run: bench build --app posawesome", built)
else:
    line("built bundle", "missing - run: bench build --app posawesome", False)
print()
