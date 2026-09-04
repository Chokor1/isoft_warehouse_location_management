# Isoft Location Manager

**Item location management** for ERPNext (v13) — inside the transaction, not beside it.

A **Warehouse Location** is a physical place inside a leaf warehouse: a shelf, a rack, a
bin. (ERPNext already owns a doctype called `Location` for assets, so these are
`Warehouse Location`.)

> **Naming.** The app was called *Isoft Picking*. The bench app and Python package are
> still `isoft_warehouse_location_management` — only the display name, the module and the desk route changed,
> so imports and asset paths (`/assets/isoft_warehouse_location_management/…`) are unaffected. Server methods
> live under `isoft_warehouse_location_management.isoft_location_manager.…`, and the old desk route
> `/app/isoft-picking` redirects to `/app/isoft-location-manager`.

## The idea

A warehouse's stock is a partition:

```
Bin.actual_qty  ==  sum(real location balances)  +  Unassigned Stock
```

Every leaf warehouse owns one system location, **Unassigned Stock**, whose quantity is
never stored — it is whatever the warehouse holds minus what the real locations hold. So
the moment the app is installed, every unit already in stock is accounted for, nothing
needs seeding, and putting stock away is simply a transfer out of it.

Location movements only ever *repartition* that total; they never change it, and they
never post a GL entry or a Stock Ledger Entry.

## Locations resolve themselves

Every surface that can carry a location calls one resolver, which answers: *for this
item, this warehouse, this direction — which location should already be filled in?*

| Mode | When | What the operator sees |
|---|---|---|
| `locked` | one answer | the location, as a chip. No choice to make. |
| `suggested` | several, one best | a dropdown already sitting on it, quantities shown |
| `split` | no single location covers the line | a proposed allocation, one click to split the row |
| `none` | nothing holds it here | why, and what to do about it |

**Taking stock out**: the locations holding the item (one → locked), then the ones that
cover the whole line, ordered by `pick_priority`, then the unassigned remainder.

The *field* offers the same set. A "pick from" Link never lists every location in the
warehouse — it lists the ones that actually hold that item, with their quantities, via
`location_resolver.location_query`. What the operator sees and what the system chose come
from one place. Put-away fields still offer every location, because stock can go
anywhere.

**Putting stock away**: the item's declared location for that warehouse → where it is
already kept → a location that receives its Item Group → the warehouse's default
receiving location → unassigned. Put-away never dead-ends.

Blank locations are resolved again server-side just before a Stock Entry is submitted,
so an unambiguous row is right whether or not anyone looked at it.

## One switch

`Picking Settings → Enable Isoft Location Manager` turns the whole module off. With it off nothing
is validated, nothing is mirrored, no field is required, the picking screens are closed
and the navbar icon disappears — stock documents behave exactly as if the app were not
installed. Location data is kept, so switching it back on resumes where you left off.

Cancellations are the one thing that still runs: a movement that exists is always
reversed, or the ledger would be left holding stock that has gone.

Each integration can also be switched off on its own:

| Setting | Covers |
|---|---|
| Locations on Stock Entry | receipts, issues, transfers, repacks |
| Locations on Delivery Note & Sales Invoice | shipping and stock-updating invoices |
| Locations in POS Awesome | POS sales, and the location shown at the till |

## Where stock leaves

Delivery Notes, stock-updating Sales Invoices and POS sales all drain `Bin.actual_qty`.
Each item row carries a location, resolved automatically — a cashier is never asked which
shelf a sale came off — and the pick is mirrored into a cost-free movement. Credit notes
run the other way, putting the goods back.

Because the sale is already a fact by the time it is mirrored, a location that cannot
cover it warns rather than blocks. **Warehouse → Check** lists any item whose locations
claim more than the warehouse holds, and corrects one with a recorded Stock Out.

## In POS Awesome

The till shows where each item is kept, next to its price and quantity — the one thing
worth knowing at the counter. Nothing is asked of the cashier: the location is decided on
submit by the same resolver the warehouse screens use.

## One line, several shelves

A Sales Invoice or Delivery Note line is a fiscal record: SAFT-T, the AGT e-invoicing
payload and every print format count and total those rows. So a line picked off two
shelves is **never split into two lines**. The split lives on the row instead:

```json
[{"location": "02-DEMO-A1", "qty": 100}, {"location": "02-DEMO-B1", "qty": 50}]
```

`custom_from_location` keeps the largest share, so anything reading a single value still
gets a sensible one, and the location movement carries a line per location — a movement
is internal, so its shape is nobody else's business.

Normally the resolver settles this on its own. See
[Dividing a line across locations](#dividing-a-line-across-locations) for making the
division by hand.

## Four screens, one job

`/app/isoft-location-manager` is about where things are kept, and nothing else:

| | |
|---|---|
| **Dashboard** | how much of the warehouse is put away, which locations are doing the work, and whether the ledger still balances |
| **Locations** | the board: a column per location, drag to re-shelve, edit what a location holds, the unassigned bar along the bottom |
| **Ledger** | every movement that touched a location, by warehouse, location and item |
| **Settings** | the module switch, integrations, enabled warehouses |

Preparation requests, stock entries and material requests are **not** screens here — those
are ERPNext documents and belong on ERPNext's own forms, which this app already
customises with location fields.

Everywhere a warehouse is picked for picking purposes — the scope selector, New Location,
the Warehouse Location form, movements — the list is the **enabled warehouses** from
Picking Settings. An empty setting means all of them.

## The Locations board

`/app/isoft-location-manager → Locations` does one job: manage where things are kept. A column per
location, an item card per holding, and the unassigned bar along the bottom. Drag a card
between columns to re-shelve it, click a quantity to say what a shelf really holds.

Stock health — anything claiming more than the warehouse holds — lives on the
**Dashboard**, where the rest of the figures are.

## The ledger

One document line becomes one ledger line per end it names, so a transfer reads as an
**out** on the shelf it left and an **in** on the shelf it reached. Filter by location and
those two columns become relative to it. Every line says what caused it — the Stock Entry,
Delivery Note, Sales Invoice or preparation request — and clicking through opens it.

## The dashboard

One question at the top: **how much of this warehouse is actually on a location** — as a
percentage of units, with the item counts behind it (fully put away / partly / not at
all). Then four figures that a location manager can act on:

- **locations**, and how many are standing empty
- **movements this week**, split by Stock In / Out / Transfer
- **over capacity** — locations holding more than they declare
- **items with no declared location** — nothing says where they belong

Below that, the two locations lists that answer "where is the work": **holding the most**
(with fill percentage where a capacity is set) and **busiest this week** by movement
count. **Location Health** closes it — anything claiming more than the warehouse holds.

There are no document counts here. Preparation requests and material requests are
ERPNext's business, not this app's.

## Zones

A **Warehouse Zone** groups the locations of one warehouse — an aisle, a cold room, a
returns corner. It is an organising layer only: stock lives in a location, never in a
zone, so a warehouse that never defines one behaves exactly as it did before, and
nothing about picking changes when zones appear.

Zone codes are unique inside their warehouse (`01-Z-FRONT`), a zone cannot take a
location from another warehouse, and unassigned stock is never part of one. Deleting a
zone **unfiles** its locations; it never touches them or their stock.

Manage them from `Locations → Zones`, set one on a location in its editor, or drag a
location tile onto another zone in the Layout view. Filing is not a stock movement.

## Two ways to read a warehouse

`Locations` has a view switch:

| | |
|---|---|
| **Contents** (default) | what every location holds, item by item — the working view |
| **Layout** | the zones and locations themselves: units, item count, fill against capacity, type. No item lists. |

Layout is the map you use when you are organising the place rather than working it. Both
views take a drop from the unassigned bar, so stock can be put away from either; in
Layout a location tile can also be dragged into another zone. The two gestures do not
collide — carrying an item card, a zone stops offering itself as a target. Both views group by zone —
but only once at least one zone exists, so a warehouse that ignores them sees no change.

## Deleting a location

The trash icon beside the pencil, in either view. It confirms first, and the
confirmation says what will happen rather than just asking: how many items the location
holds, how much, and that all of it returns to unassigned stock.

**Nothing is destroyed.** The goods stay in the warehouse; they simply stop being claimed
by a location, which is what unassigned stock *is* — the remainder the partition does not
account for. So the warehouse total does not move, and the stock can be put away again
from the bar at the bottom of the board. The emptying is recorded as an ordinary
re-shelving, so the ledger shows where it went.

The ledger keeps every movement that ever named the location. History is not rewritten
when a location is retired.

Unassigned stock itself cannot be deleted — it is derived, so there is nothing there to
delete. An item that named the location as its pick location has that cleared.

## Editing a location

The pencil on a column opens what that location **holds**, not what it is called: every
item with its quantity, how much of it is promised to an open request, and how much of it
is still loose in the warehouse.

Change a quantity and the difference is re-shelved — lower it and the remainder returns
to unassigned stock, raise it and it comes from there. **All to unassigned** empties a
line in one click. Nothing on that screen can invent or destroy stock; a quantity the
warehouse cannot cover is reported per item and the other lines still apply.

Each line also carries a **Pick from here** toggle: outgoing stock of that item is taken
from this location first, whenever it holds any. One location holds the role per
warehouse, so setting it here clears it wherever it was before.

It feeds the resolver, so it applies to **every transaction in that warehouse** — Stock
Entry, Delivery Note, Sales Invoice and POS alike. A declared pick location leads the
ranking, but only while it actually holds something: a preference is not a reason to pick
from an empty shelf.

There is deliberately no put-away equivalent. See below.

Each line has two ways out, and they are not the same thing:

- **All to unassigned** sets the quantity to zero. The stock goes back to unassigned, but
  the line stays — that is how a location remembers an item belongs there.
- the **trash** takes the item off the location altogether. The stock goes back the same
  way, and then the line goes too, so the location stops listing it. For when the memory
  is the thing to be rid of: the item was put on the wrong shelf, or is not kept there
  any more.

Either way nothing is destroyed and the warehouse total does not move. Removing an item
also clears it as that location's pick location, since a location can hardly be where an
item is picked from once it no longer holds it.

The location's own description and active flag live at the bottom of the same dialog.


## What the row records

Every settled row carries its allocation, whether the goods came off one location or
five — the field *is* the record, and one written only some of the time is not one
anybody can read. It is also what the location movement is built from, so the two always
agree. It is written **on save**, not only at submit, so a draft already says where each
line will be taken from.

An allocation that no longer adds up to its line (because the quantity was edited after
it was settled) is not a decision to respect — it is a leftover, and it is recomputed.

**Stock going out must say where it came from.** `Settings → Require a location when stock
leaves` refuses a line unless every unit of it is traceable to a location. It is about
quantity, not choice: how many locations hold the item makes no difference — one or five,
both pass. Whether it ever bites is decided by *Allow picking from unassigned stock*: while
that is on the remainder counts as somewhere, so almost any line can be accounted for;
switch it off and this becomes the rule that stops goods leaving before anyone has put them
away.

**Arrivals can be barred from being placed at all.** `Picking Settings → Choose a Location
When Stock Arrives`, switched off, means goods always land in unassigned stock however the
document was filled in — for the location manager to distribute afterwards from the board.
Nothing is refused: the receiver did nothing wrong, and the location column simply
disappears from Purchase Receipt, Purchase Invoice and the Stock Entry target side.

**Stock coming in is always chosen by hand, and never required.** Nothing fills a
put-away location automatically — not on a Purchase Receipt, not on the target side of a
Stock Entry, not on a return. Where something goes is a decision somebody makes standing
at the shelf, and guessing would put stock on a location nobody visited. A line left
blank is not a missing answer: the goods are in the warehouse and not yet on a location,
which is exactly what unassigned stock means. Put them away later from the dock, when
they are actually on the shelf.

That asymmetry is the whole rule: **picking is a lookup, putting away is a decision.**

## Dividing a line across locations

A line bigger than one location is normally settled by the resolver: a chosen location is
where picking *starts*, and the rest spills from there. When that is not what happened —
the assistant knows the goods came off two specific places — the division can be made by
hand.

One field says where a line came from: **Picked From Location**. It reads as a location
(`01-01-AB`) when the goods came off one, and as the division (`01-01-AA 2 + 01-01-AB 3`)
when they came off several. The underlying `custom_from_location` link is still written
and still read by everything that wants a single value, but it is hidden — two fields for
one fact is worse than one, and they can disagree.

Open a line and the answer is a small table — **Location · Available · Take** — one row
per location that holds the item, already filled in with the resolver's proposal and
adding up to the line. Nothing to open and nothing to click: quantities are typed
straight into it and moved between rows until the footer says *all N placed*. A line
that only comes from one place needs no attention at all.

The desk row form and the till show the same table. From the grid, the **Picked From
Location** column still opens the same thing in a dialog, for when the row is not
expanded. At the till it is the split icon beside the Location
box, which shows a dot when a division is recorded.

**The desk and the till behave identically.** A location is always pre-selected — whatever
the resolver leads with, in every mode, so nobody is ever made to choose. And dividing is
only offered when there is something to divide. The control appears when the item is
actually in more than one place in that warehouse — two locations, or one location and a
loose remainder. On the desk that answer is fetched once per warehouse per form, so a
grid of forty rows costs one round trip, not forty — and the same answer is spelled
out under the field as **In this warehouse: 01-01-AA 40 · 01-01-AB 25 · Not put away
368**, so where the goods are takes no clicking to find out. The POS item form says
the same thing in the same words. When a single location holds the lot there is no choice
to make, and a control that can only ever do nothing is worse than no control. An
existing division always stays reachable, even if the stock has since moved into one
place, so a wrong split can still be corrected.

What it records:

- The document line is **never split** (see above).
- The division is stored as JSON on the row (`custom_location_allocation`) and is
  **honoured, not recomputed**: once set by hand, nothing overwrites it.
- Quantities are in the **stock UOM**, because that is the unit location balances are
  kept in. When the line is sold in another unit the dialog says so.
- A division that no longer adds up to the line is dropped rather than shipped wrong.

## The Picking Sheet

A shipment is prepared by somebody who did not type it. They need one page — what to
fetch, how much, and from which location — and nothing else. **Picking Sheet** on a
Delivery Note, Sales Invoice or Stock Entry opens exactly that, ready to print, with the
company logo and two signature lines.

No prices, no customer terms, no tax. The person walking the racks does not need them,
and a document full of things they must ignore is a document they will stop reading.

The button appears only when there is something to pick: the module is on, the document
really takes stock out, and it does so from a warehouse this app runs in. A Stock Entry
that only receives has nothing to fetch, so it gets no button; a transfer out of an
enabled warehouse does.

It is built from the same allocation the ledger is built from, so the sheet and the stock
movement can never disagree. A line that comes off three locations is still one line,
with three places named under it.

## Import and export

`Import / Export` is two things: bringing a warehouse in, and taking it out. What each one
acts on is chosen inside it. A warehouse is described in three layers, which depend on
each other in this order:

| | |
|---|---|
| **Zones** | the parts a warehouse is divided into. First, because a location can name one |
| **Locations** | the shelves, racks and bins. A zone named here must already exist |
| **Stock on locations** | what sits where |

**One workbook carries all three.** Tick the layers, get one file with a sheet each; send
one file back and every sheet in it is recognised by its own header, checked together, and
applied in the order above — so a workbook holding zones *and* the locations that name them
lands in one go, whichever order the sheets happen to be in.

**A file is checked in full before any of it is written.** Every problem is reported with
its row number and what was actually in the cell — *"row 5: capacity is not a number
(ten)"*, *"row 4: 02 - Loja Viana has no zone NOPE — import the zones first"*. One bad row anywhere and the
whole workbook lands nowhere — including the sheets that would have been fine. A
half-imported warehouse is worse than an unimported one, because re-running it would
double the quantities and nobody could tell what had already landed.

Quantities are read the way spreadsheets write them, so `1 234,50` and `1,234.50` both
mean the same number, and `ten` is a complaint rather than a zero. Stock cannot be placed
beyond what the warehouse holds, counting what is already on locations the file does not
mention.

Importing stock is not a stock movement: the difference comes from, or goes back to,
unassigned stock, exactly as the board does it, and the ledger records it.

**Export** returns what is there now in exactly the workbook the importer accepts — edit
it and send it back. Unassigned stock is never exported, because it is derived;
re-importing it would turn a remainder into a claim.

The workbook explains itself, because a sheet that has to be explained in a separate email
is a sheet that comes back wrong. Required columns are marked `*` in the header, the
header row is frozen and filterable, columns are wide enough to read, quantities are
formatted as numbers, **Location Type** is a dropdown of the real options and quantities
refuse a negative — and a second sheet, *How to fill this in*, says what every column
means and what happens when a row is wrong.

A `.csv` is accepted too. Somebody will always send one, and refusing it teaches them
nothing. Headers are matched loosely — case, spaces and the `*` are all ignored — so a
sheet that has been through someone's hands still lands.

## The unassigned dock

Unassigned stock is usually the largest thing in a warehouse — 813 items in one shop
here — so it gets a permanent bar across the bottom of the explorer rather than a capped
column. The bar always shows the count and total; clicking it raises the panel, which is
searchable and paged.

Drag a card straight onto a location to put it away — every column it can land in is
outlined the moment the card lifts — or use **Put away** for a dialog that asks the
location and quantity. Either way it is a Stock In out of the pool: no stock
entry, no accounting.

The bar costs one aggregate query and 139 bytes while it is shut — it shows a count and
a total, and fetching forty rows with their names to render one number was most of what
made it feel slow. Rows arrive only when it is opened, once.

Three details make it work rather than get in the way: it is pinned to the viewport, not
parked at the end of a long board; its height is measured so opening and closing follow
the same curve; and it **tucks itself out of sight the moment a card is dragged**, because
the shelves behind it are what the card is being aimed at. For the same reason there is
no backdrop — dimming the drop target would fight the whole point. Escape or × closes it.

## The warehouse board

In the explorer's kanban view, **drag an item card onto another location** to re-shelve
it, and **click a quantity** to say what that shelf actually holds. Lower it and the
difference returns to unassigned stock; raise it and the difference is taken from
unassigned — which is what stops a shelf from ever claiming more than the warehouse has.

Neither needs a Stock Entry or any accounting. Moving between two locations of the same
warehouse changes nothing about real stock; it is a re-shelving, and a Location Stock
Movement is the whole record of it.

## What's in the box

- **Warehouse Location** — code, type (Storage / Pick Face / Bulk / Staging / Quarantine),
  `pick_priority`, capacity, barcode, default-receiving flag, and an Item Group put-away
  rule. Named `<warehouse prefix>-<code>`, so every shop can label its racking the way
  the racking is actually labelled.
- **Location Stock** — the balance per (warehouse, location, item). Unique-indexed and
  updated with a single atomic statement, so concurrent submits cannot lose a delta.
- **Location Stock Movement** — Stock In / Stock Out / Transfer, submittable. Cost-free.
  A cancellation can never be blocked by stock that has since moved on.

- **Item → Default Locations** — where an item is put away in each warehouse.
- **Dashboard** (`/app/isoft-location-manager`) — warehouse explorer with the unassigned column
  and a one-click put-away, distribute and stock-transaction panels, requests, logs, and
  the locations-vs-real-stock check.

## A note on client scripts

`location_control.js` ships in `app_include_js` and is cached by the browser against
Frappe's build version. Every doctype script therefore treats its helpers as optional:
a `set_query` goes through a local fallback rather than calling into the shared file
directly, because throwing inside a form's `setup` would take that ERPNext form down.
An app that adds a field must never be able to break the document it is added to.

## Install

```bash
bench get-app isoft_warehouse_location_management   # or place under apps/
bench --site <site> install-app isoft_warehouse_location_management
bench --site <site> migrate
bench build --app isoft_warehouse_location_management
```

`migrate` creates the Unassigned Stock location for every leaf warehouse and moves
existing locations onto warehouse-scoped names.

## Who sees what

Nothing about access is configured inside this app.

**Who can open it** is the *Location Manager* role — assigned on the User like any other
role. That is the only role this app defines.

**Everyone else keeps working.** Locations still appear, and can still be chosen, on the
documents they already use: Sales Invoice, Delivery Note, Stock Entry, Purchase Receipt
and the till. None of that needs a role — a salesperson has to be able to say where the
goods came off without being given the keys to reorganise the warehouse. `Warehouse
Location` is readable by everyone and writable only by a Location Manager.

**What a manager sees** is their ERPNext *User Permissions* for Warehouse, narrowed to
the warehouses enabled in Settings. A manager with no warehouse permission sees every
enabled warehouse.

*Settings* is System Manager only. Every switch there is on or off **for the whole
site** — never per item or per location. A rule that holds for some items and not others
is a rule nobody can state, let alone rely on.

## Settings

`Picking Settings` (System Manager) — role assignment, enabled warehouses, theme, plus:

- **Enable Isoft Location Manager** — the master switch, plus one flag per integration
- **Stock Validation** — Block / Warn / Off for location availability
- **Resolve Locations Automatically** — fill blank locations in on submit
- **Allow Picking From Unassigned Stock** — turn off once a warehouse is fully put away

Rebuild the POS bundle after installing, so the till picks up the location column:

```bash
bench build --app posawesome
```

#### License

MIT
