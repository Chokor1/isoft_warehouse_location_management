// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt
//
// The shared location picker. Every surface that can carry a location uses this, so a
// row behaves the same whether it is on the locations board, a Stock Entry, a Delivery
// Note or the till.
//
// It asks the server which location should already be filled in and then gets out of
// the way: one candidate becomes a chip, several become a dropdown already sitting on
// the best answer, and nothing at all becomes an explanation instead of an empty box.

frappe.provide('isoft_warehouse_location_management');

isoft_warehouse_location_management.RESOLVER = 'isoft_warehouse_location_management.isoft_location_manager.location_resolver.resolve';
isoft_warehouse_location_management.RESOLVER_ONE = 'isoft_warehouse_location_management.isoft_location_manager.location_resolver.resolve_one';

// ----------------------------------------------------------------------
// module switch
// ----------------------------------------------------------------------
// Asked once per page load. With the module off nothing here does anything: no
// resolution calls, no location columns, no alerts.
// frappe.call hands back a *jQuery* promise, and this bench serves jQuery 1.9, whose
// deferreds have no `.catch` — that only arrived in jQuery 3. Chaining one throws, and
// it throws inside a promise, so the failure surfaces as console noise while the caller
// silently gets nothing. Every call is wrapped into a real promise here instead, once,
// so nothing downstream has to know which jQuery is underneath.
isoft_warehouse_location_management.promise = function (opts, fallback) {
	return new Promise((resolve) => {
		let settled = false;
		const done = (v) => { if (!settled) { settled = true; resolve(v); } };
		try {
			// the two-argument form of .then is the one every jQuery version has
			frappe.call(opts).then(
				(r) => done(r && r.message !== undefined ? r.message : fallback),
				() => done(fallback)
			);
		} catch (e) {
			done(fallback);
		}
	});
};

isoft_warehouse_location_management._status = null;
isoft_warehouse_location_management.status = function () {
	if (isoft_warehouse_location_management._status) return isoft_warehouse_location_management._status;
	isoft_warehouse_location_management._status = isoft_warehouse_location_management.promise(
		{ method: 'isoft_warehouse_location_management.isoft_location_manager.api.module_status' },
		{ enabled: false }
	);
	return isoft_warehouse_location_management._status;
};

isoft_warehouse_location_management.enabled = function (feature) {
	return isoft_warehouse_location_management.status().then((s) => !!(s.enabled && (!feature || s[feature])));
};

// Hide the location columns of a grid entirely when the module (or this integration)
// is off, so a switched-off module asks nothing of anyone.
isoft_warehouse_location_management.toggle_grid_locations = function (frm, table_field, location_fields, feature) {
	return isoft_warehouse_location_management.enabled(feature).then((on) => {
		const grid = frm.fields_dict[table_field] && frm.fields_dict[table_field].grid;
		if (!grid) return on;
		location_fields.forEach((f) => {
			try {
				grid.update_docfield_property(f, 'hidden', on ? 0 : 1);
				grid.update_docfield_property(f, 'reqd', 0);
			} catch (e) {
				/* field not on this form */
			}
		});
		frm.refresh_field(table_field);
		return on;
	});
};

// ----------------------------------------------------------------------
// enabled warehouses
// ----------------------------------------------------------------------
// Picking Settings names the warehouses this module runs in. Everywhere a warehouse is
// picked *for picking purposes*, that is the list — an empty setting means all of them.
isoft_warehouse_location_management._enabled_wh = null;
isoft_warehouse_location_management.enabled_warehouses = function () {
	if (isoft_warehouse_location_management._enabled_wh) return isoft_warehouse_location_management._enabled_wh;
	isoft_warehouse_location_management._enabled_wh = isoft_warehouse_location_management.promise(
		{ method: 'isoft_warehouse_location_management.isoft_location_manager.api.get_enabled_warehouses' }, []
	);
	return isoft_warehouse_location_management._enabled_wh;
};

/** A set_query handler restricted to the enabled leaf warehouses. */
isoft_warehouse_location_management.warehouse_query = function (frm, cache_key) {
	cache_key = cache_key || '_ip_enabled_wh';
	isoft_warehouse_location_management.enabled_warehouses().then((list) => {
		if (frm) frm[cache_key] = list;
	});
	return function () {
		const list = (frm && frm[cache_key]) || [];
		return { filters: list.length ? { name: ['in', list], is_group: 0 } : { is_group: 0 } };
	};
};

/** A set_query that offers only the locations that actually hold the item.
 *
 * Taking stock out must never list every shelf in the warehouse — it lists the shelves
 * the resolver would rank, so what the operator sees and what the system chose come
 * from one place. Putting stock away can go anywhere, so it lists all of them.
 *
 * get_ctx(doc, cdt, cdn) -> { warehouse, item_code, direction }
 */
isoft_warehouse_location_management.location_query = function (get_ctx) {
	return function (doc, cdt, cdn) {
		const c = (get_ctx && get_ctx(doc, cdt, cdn)) || {};
		return {
			query: 'isoft_warehouse_location_management.isoft_location_manager.location_resolver.location_query',
			filters: {
				warehouse: c.warehouse || '__none__',
				item_code: c.item_code || '',
				direction: c.direction || 'out',
			},
		};
	};
};

isoft_warehouse_location_management.fmt = function (n) {
	return format_number(flt(n), null, flt(n) % 1 ? 2 : 0);
};

// ----------------------------------------------------------------------
// server calls
// ----------------------------------------------------------------------
isoft_warehouse_location_management.resolve_locations = function (warehouse, item_codes, direction, qty_by_item) {
	const codes = (item_codes || []).filter(Boolean);
	if (!warehouse || !codes.length) return Promise.resolve({});
	return isoft_warehouse_location_management.enabled().then((on) => {
		if (!on) return {};
		return isoft_warehouse_location_management.promise({
			method: isoft_warehouse_location_management.RESOLVER,
			args: {
				warehouse: warehouse,
				items: JSON.stringify([...new Set(codes)]),
				direction: direction || 'out',
				qty_by_item: JSON.stringify(qty_by_item || {}),
			},
		}, {});
	});
};

isoft_warehouse_location_management.resolve_one = function (warehouse, item_code, direction, qty) {
	if (!warehouse || !item_code) return Promise.resolve(null);
	return isoft_warehouse_location_management.enabled().then((on) => {
		if (!on) return null;
		return isoft_warehouse_location_management.promise({
			method: isoft_warehouse_location_management.RESOLVER_ONE,
			args: {
				warehouse: warehouse,
				item_code: item_code,
				direction: direction || 'out',
				qty: qty || 0,
			},
		}, null);
	});
};

// ----------------------------------------------------------------------
// LocationControl — a self-resolving picker for one row
// ----------------------------------------------------------------------
// opts: { parent, direction, get_warehouse(), get_item(), get_qty(), on_change(value, res) }
isoft_warehouse_location_management.LocationControl = class LocationControl {
	constructor(opts) {
		this.opts = opts || {};
		this.direction = this.opts.direction || 'out';
		this.value = null;
		this.res = null;
		this.touched = false; // once the operator picks for themselves, stop overriding them
		this.$wrap = $('<div class="ip-locctl"></div>').appendTo(opts.parent);
		this.render_placeholder(__('Pick an item first'));
	}

	get_value() {
		return this.value || null;
	}

	set_value(value) {
		this.value = value || null;
		this.touched = true;
		this.render();
		return this;
	}

	/** Re-ask the server. Call on item change, warehouse change, or qty change. */
	refresh(force) {
		const warehouse = this.opts.get_warehouse && this.opts.get_warehouse();
		const item = this.opts.get_item && this.opts.get_item();
		if (!warehouse || !item) {
			this.res = null;
			this.value = null;
			this.render_placeholder(warehouse ? __('Pick an item first') : __('Pick a warehouse first'));
			return Promise.resolve(null);
		}
		if (force) this.touched = false;

		const qty = (this.opts.get_qty && flt(this.opts.get_qty())) || 0;
		this.render_placeholder(__('Finding location…'));
		return isoft_warehouse_location_management
			.resolve_one(warehouse, item, this.direction, qty)
			.then((res) => this.apply(res));
	}

	/** Feed in a resolution already fetched in bulk, avoiding a call per row. */
	apply(res) {
		this.res = res;
		if (res && !this.touched) this.value = res.location || null;
		this.render();
		if (this.opts.on_change) this.opts.on_change(this.value, res);
		return res;
	}

	// ------------------------------------------------------------------
	render_placeholder(text) {
		this.$wrap.empty().append($('<span class="ip-loc-hint"></span>').text(text));
	}

	render() {
		const res = this.res;
		this.$wrap.empty();
		if (!res) return this.render_placeholder(__('Pick an item first'));

		if (res.mode === 'none') return this.render_none(res);
		if (res.mode === 'locked' && !this.touched) return this.render_chip(res);
		return this.render_select(res);
	}

	// one candidate: show what was chosen, not a control asking to choose it
	render_chip(res) {
		const chip = $(`
			<button type="button" class="ip-loc-chip${res.is_unassigned ? ' is-unassigned' : ''}">
				<span class="ip-loc-code"></span>
				<span class="ip-loc-qty"></span>
			</button>`);
		chip.find('.ip-loc-code').text(res.location);
		chip.find('.ip-loc-qty').text(res.available ? isoft_warehouse_location_management.fmt(res.available) : '');
		chip.attr('title', res.reason || '');
		chip.on('click', () => {
			this.touched = true;
			this.render();
		});
		this.$wrap.append(chip);
		if (res.reason) {
			this.$wrap.append($('<span class="ip-loc-why"></span>').text(res.reason));
		}
	}

	render_select(res) {
		const $sel = $('<select class="ip-input ip-loc-select"></select>');
		$sel.append($('<option></option>').val('').text('—'));
		let matched = false;
		(res.candidates || []).forEach((c) => {
			const $o = $('<option></option>')
				.val(c.location)
				.text(`${c.location} · ${isoft_warehouse_location_management.fmt(c.qty)}${c.is_unassigned ? ' · ' + __('unassigned') : ''}`);
			if (c.location === this.value) {
				$o.prop('selected', true);
				matched = true;
			}
			$sel.append($o);
		});
		// a value chosen before the options were narrowed still has to stay visible
		if (this.value && !matched) {
			$sel.append($('<option></option>').val(this.value).text(`${this.value} · 0`).prop('selected', true));
		}
		$sel.on('change', () => {
			this.touched = true;
			this.value = $sel.val() || null;
			if (this.opts.on_change) this.opts.on_change(this.value, this.res);
		});
		this.$wrap.append($sel);

		if (res.mode === 'split' && res.split) this.render_split(res);
		else if (res.reason && res.mode === 'suggested') {
			this.$wrap.append($('<span class="ip-loc-why"></span>').text(res.reason));
		}
	}

	render_split(res) {
		const parts = (res.split || [])
			.map((p) => (p.short ? `${isoft_warehouse_location_management.fmt(p.qty)} ${__('short')}` : `${p.location} ${isoft_warehouse_location_management.fmt(p.qty)}`))
			.join('  +  ');
		const $s = $('<div class="ip-loc-split"></div>');
		$s.append($('<span class="ip-loc-split-label"></span>').text(__('Spread over')));
		$s.append($('<span class="ip-loc-split-plan"></span>').text(parts));
		if (this.opts.on_split) {
			const $btn = $('<button type="button" class="ip-loc-split-apply"></button>').text(__('Split rows'));
			$btn.on('click', () => this.opts.on_split(res.split, res));
			$s.append($btn);
		}
		this.$wrap.append($s);
	}

	render_none(res) {
		const $n = $('<span class="ip-loc-none"></span>').text(res.reason || __('Not in any location'));
		this.$wrap.append($n);
	}
};


// ----------------------------------------------------------------------
// Split editor — several shelves on ONE document line
// ----------------------------------------------------------------------
// A Sales Invoice or Delivery Note line is a fiscal record: SAFT-T, the e-invoicing
// payload and every print format count and total those rows. So a line picked off two
// shelves is never split into two lines — the split is stored on the row itself.
isoft_warehouse_location_management.ALLOCATION_FIELD = 'custom_location_allocation';

isoft_warehouse_location_management.parse_allocation = function (value) {
	if (!value) return [];
	if (Array.isArray(value)) return value;
	try {
		const rows = JSON.parse(value);
		return Array.isArray(rows) ? rows : [];
	} catch (e) {
		return [];
	}
};

isoft_warehouse_location_management.describe_allocation = function (value) {
	const rows = isoft_warehouse_location_management.parse_allocation(value);
	if (!rows.length) return '';
	if (rows.length === 1) return rows[0].location;
	return rows.map((r) => `${r.location} ${isoft_warehouse_location_management.fmt(r.qty)}`).join('  +  ');
};

// Where a row says it was picked from, in words.
//
// A line that came off one location carries no split — the single location is on the row
// instead — so reading only the split field would show nothing for the ordinary case.
// This is the one answer both the grid cell and the row form show.
isoft_warehouse_location_management.picked_from = function (row) {
	return isoft_warehouse_location_management.describe_allocation(row[isoft_warehouse_location_management.ALLOCATION_FIELD])
		|| row.custom_from_location
		|| '';
};

// ----------------------------------------------------------------------
// Dividing a line across locations
// ----------------------------------------------------------------------
// One dialog, used everywhere a line can come off more than one shelf: the desk grids
// and the till both open this. It edits a plain list of {location, qty} and hands it
// back — it knows nothing about forms, child rows or Vue, which is what lets the same
// screen serve all of them.
//
// opts: { warehouse, item_code, qty, direction, current, readonly, title, on_apply }
//   current   [{location, qty}] already recorded, or empty to start from the suggestion
//   on_apply  (rows, primary) => void   rows is [] when it all comes off one shelf
isoft_warehouse_location_management.open_location_split = function (opts) {
	const warehouse = opts.warehouse;
	const item_code = opts.item_code;
	const line_qty = Math.abs(flt(opts.qty)) || 0;
	const readonly = !!opts.readonly;

	if (!warehouse) {
		frappe.msgprint(__('Set the warehouse first.'));
		return;
	}

	frappe.call({
		method: 'isoft_warehouse_location_management.isoft_location_manager.location_allocation.suggest',
		args: {
			warehouse, item_code, qty: line_qty,
			direction: opts.direction || 'out',
			preferred: opts.preferred || null,
		},
		freeze: true,
		callback: function (r) {
			const info = r.message || { rows: [], candidates: [] };
			const cands = info.candidates || [];

			// Every location that holds the item is a row from the start, in the order the
			// resolver would pick them — the item's declared pick location first, then by
			// name. Quantities are pre-filled from the plan, so the dialog opens balanced
			// and the only thing left to do is move numbers between rows. Nothing has to
			// be added by hand, which is why there is no "add location".
			const plan = {};
			(info.rows || []).forEach((x) => { plan[x.location] = flt(x.qty); });
			const given = isoft_warehouse_location_management.parse_allocation(opts.current);
			const chosen = {};
			given.forEach((x) => { chosen[x.location] = flt(x.qty); });

			let current = cands.map((c) => ({
				location: c.location,
				qty: given.length ? (chosen[c.location] || 0) : (plan[c.location] || 0),
			}));
			// A location recorded on the row but not holding anything is still shown, so a
			// stale or hand-made choice can be seen and corrected rather than vanishing.
			given.forEach((x) => {
				if (!cands.some((c) => c.location === x.location)) {
					current.push({ location: x.location, qty: flt(x.qty) });
				}
			});
			if (!current.length) current = (info.rows || []).slice();

			const d = new frappe.ui.Dialog({
				title: opts.title || __('Pick {0} from', [item_code]),
				size: 'large',
				fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
				primary_action_label: readonly ? null : __('Apply'),
				primary_action: readonly ? null : function () {
					const rows = collect().filter((x) => x.location && flt(x.qty) > 0);
					const sum = rows.reduce((a, x) => a + flt(x.qty), 0);
					if (Math.abs(sum - line_qty) > 0.001) {
						frappe.msgprint(
							__('The locations add up to {0} but the line is for {1}.',
								[isoft_warehouse_location_management.fmt(sum), isoft_warehouse_location_management.fmt(line_qty)])
						);
						return;
					}
					const seen = {};
					for (const x of rows) {
						if (seen[x.location]) {
							frappe.msgprint(__('Location {0} is listed twice.', [x.location]));
							return;
						}
						seen[x.location] = 1;
					}
					// the largest share becomes the row's single-value location, so a
					// screen that can only show one still shows the truest one
					const sorted = rows.slice().sort((a, b) => flt(b.qty) - flt(a.qty));
					d.hide();
					// every settled row carries its allocation, one location or several —
					// the field is the record, and a record written only sometimes is
					// not one anybody can read
					if (opts.on_apply) {
						opts.on_apply(rows, sorted.length ? sorted[0].location : null);
					}
				},
			});

			const $body = d.get_field('body').$wrapper;
			const esc = frappe.utils.escape_html;

			const render = () => {
				const sum = current.reduce((a, x) => a + flt(x.qty), 0);
				const diff = line_qty - sum;
				$body.html(`
					<div class="ip-split-head">
						<span>${esc(__('To place'))}</span>
						<b>${isoft_warehouse_location_management.fmt(line_qty)}${opts.uom ? ' ' + esc(opts.uom) : ''}</b>
						${opts.line ? `<span class="ip-split-uom">${esc(
							__('line is {0} {1}', [isoft_warehouse_location_management.fmt(opts.line.qty), opts.line.uom || '']))}</span>` : ''}
						<span class="ip-split-diff ${Math.abs(diff) < 0.001 ? 'ok' : 'off'}">
							${Math.abs(diff) < 0.001
								? esc(__('balanced'))
								: (diff > 0
									? esc(__('{0} still to place', [isoft_warehouse_location_management.fmt(diff)]))
									: esc(__('{0} too many', [isoft_warehouse_location_management.fmt(-diff)])))}
						</span>
					</div>
					<div class="ip-split-note">${esc(__(
						'The document line is never split — this only records which locations the goods came off.'))}</div>
					<table class="ip-split-table">
						<thead><tr>
							<th>${esc(__('Location'))}</th>
							<th style="width:130px">${esc(__('Qty'))}</th>
							<th style="width:120px">${esc(__('Available'))}</th>
							<th style="width:34px"></th>
						</tr></thead>
						<tbody>${current.map((x, i) => {
							const cand = (info.candidates || []).find((c) => c.location === x.location);
							const max = cand ? flt(cand.qty) : null;
							return `<tr data-i="${i}" class="${cand ? '' : 'ip-split-stale'}">
								<td>
									<span class="ip-split-loc">${esc(
										cand && cand.is_unassigned ? __('Not put away') : x.location)}</span>
									${cand && cand.is_unassigned
										? `<span class="ip-split-tag">${esc(__('loose'))}</span>` : ''}
									${cand ? '' : `<span class="ip-split-tag warn">${esc(__('holds none'))}</span>`}
									<input type="hidden" class="ip-split-sec" value="${esc(x.location)}">
								</td>
								<td><input type="number" class="ip-input ip-split-qty" step="any" min="0"
									${max === null ? '' : `max="${max}"`}
									value="${flt(x.qty)}" ${readonly ? 'disabled' : ''}></td>
								<td class="ip-split-avail">${cand ? isoft_warehouse_location_management.fmt(cand.qty) : '—'}</td>
								<td>${readonly || !flt(x.qty) ? '' : `<button class="ip-split-del" data-i="${i}"
									title="${esc(__('Take nothing from here'))}">&times;</button>`}</td>
							</tr>`; }).join('')}</tbody>
					</table>
					${readonly ? '' : `<div class="ip-split-actions">
						<button class="ip-split-auto">${esc(__('Fill automatically'))}</button>
					</div>`}
					${info.shortfall > 0.001
						? `<div class="ip-split-short">${esc(__('{0} is not on any location — it will stay in unassigned stock.',
							[isoft_warehouse_location_management.fmt(info.shortfall)]))}</div>` : ''}
				`);

				$body.find('.ip-split-sec, .ip-split-qty').on('change', () => { current = collect(); render(); });
				// clearing a row sets it to nothing rather than deleting it — the location
				// still holds stock, so it stays on screen ready to be used again
				$body.find('.ip-split-del').on('click', (e) => {
					current = collect();
					const i = $(e.currentTarget).data('i');
					if (current[i]) current[i].qty = 0;
					render();
				});
				$body.find('.ip-split-auto').on('click', () => {
					const auto = {};
					(info.rows || []).forEach((x) => { auto[x.location] = flt(x.qty); });
					current = collect().map((x) => ({ location: x.location, qty: auto[x.location] || 0 }));
					render();
				});
			};

			const collect = () => $body.find('tbody tr').map((_i, tr) => ({
				location: $(tr).find('.ip-split-sec').val() || '',
				qty: flt($(tr).find('.ip-split-qty').val()),
			})).get();

			render();
			d.show();

			// Frappe's expanded grid row (.form-in-grid) sits at z-index 1051 — one above
			// a bootstrap modal's 1050. A dialog opened from inside a row form therefore
			// renders *behind* the form that opened it. This one is opened from exactly
			// there, so it lifts itself, and its backdrop, over the top.
			d.$wrapper.addClass('ip-above-grid');
			d.$wrapper.on('shown.bs.modal.ipabove', () => {
				$('.modal-backdrop').not('#freeze').last().addClass('ip-above-grid-backdrop');
			});
		},
	});
};

// Location balances are kept in the stock UOM, so a division must be expressed in it
// too — dividing the line UOM would not add up to the line the server checks against.
// Sales documents call it stock_qty, Stock Entry calls it transfer_qty, and a line sold
// in its stock UOM has neither.
isoft_warehouse_location_management.stock_qty_of = function (row) {
	return Math.abs(flt(row.stock_qty) || flt(row.transfer_qty) || flt(row.qty)) || 0;
};

// The desk wrapper: reads the child row, and writes the answer back onto it.
// opts: { frm, cdt, cdn, warehouse_field, qty_field, direction }
isoft_warehouse_location_management.open_split_dialog = function (opts) {
	const { frm, cdt, cdn, warehouse_field, direction } = opts;
	const row = locals[cdt] && locals[cdt][cdn];
	if (!row || !row.item_code) return;
	const stock_qty = isoft_warehouse_location_management.stock_qty_of(row);

	isoft_warehouse_location_management.open_location_split({
		warehouse: row[warehouse_field],
		item_code: row.item_code,
		qty: stock_qty,
		uom: row.stock_uom,
		line: (flt(row.conversion_factor) && flt(row.conversion_factor) !== 1)
			? { qty: Math.abs(flt(row.qty)), uom: row.uom } : null,
		direction: direction || 'out',
		// only a real division is carried in verbatim; a single stored location is a
		// preference for where to start, which the server drops if it holds nothing
		current: row[isoft_warehouse_location_management.ALLOCATION_FIELD] || null,
		preferred: row.custom_from_location || null,
		readonly: frm.doc.docstatus !== 0,
		on_apply: function (rows, primary) {
			frappe.model.set_value(cdt, cdn, isoft_warehouse_location_management.ALLOCATION_FIELD,
				rows.length ? JSON.stringify(rows) : null);
			frappe.model.set_value(cdt, cdn, 'custom_from_location', primary);
			frm.refresh_field('items');
		},
	});
};


// ----------------------------------------------------------------------
// Is there anything to divide?
// ----------------------------------------------------------------------
// Same rule as the till: dividing is only offered when the goods really are in more
// than one place. With a single location holding the lot there is no choice to make,
// and a control that can only ever do nothing is worse than no control.
//
// Answered per (warehouse, item) and cached on the form, so a grid of forty rows costs
// one round trip per warehouse rather than one per row.
isoft_warehouse_location_management.split_key = function (warehouse, item_code) {
	return (warehouse || '') + '\u0000' + (item_code || '');
};

isoft_warehouse_location_management.remember_choice = function (frm, warehouse, item_code, res) {
	if (!frm || !res) return;
	frm._ip_where = frm._ip_where || {};
	// the candidates themselves, not a yes/no — the same answer says where the item is
	// *and* whether there is anything to divide
	frm._ip_where[isoft_warehouse_location_management.split_key(warehouse, item_code)] = res.candidates || [];
};

/** Every location in this warehouse that holds the row's item, with what it holds. */
isoft_warehouse_location_management.where_is = function (frm, row, warehouse_field) {
	const cache = (frm && frm._ip_where) || {};
	return cache[isoft_warehouse_location_management.split_key(row[warehouse_field], row.item_code)] || null;
};

isoft_warehouse_location_management.can_divide = function (frm, row, warehouse_field) {
	// a division already recorded stays reachable, even if the stock has since moved
	// into one place — otherwise a wrong split could not be corrected
	if (isoft_warehouse_location_management.parse_allocation(row[isoft_warehouse_location_management.ALLOCATION_FIELD]).length > 1) return true;
	return (isoft_warehouse_location_management.where_is(frm, row, warehouse_field) || []).length > 1;
};

/** "01-01-AA 40 · 01-01-AB 25 · Not put away 368" */
isoft_warehouse_location_management.describe_where = function (candidates) {
	return (candidates || [])
		.map((c) => (c.is_unassigned ? __('Not put away') : (c.label || c.location))
			+ ' ' + isoft_warehouse_location_management.fmt(c.qty))
		.join('  ·  ');
};

// Fills that cache for every row on the form, in one call per warehouse.
// opts: { table_field, warehouse_field, direction, feature }
isoft_warehouse_location_management.load_split_hints = function (frm, opts) {
	const rows = (frm.doc[opts.table_field || 'items'] || []).filter(
		(r) => r.item_code && r[opts.warehouse_field]
	);
	if (!rows.length) return Promise.resolve({});

	const by_wh = {};
	rows.forEach((r) => {
		const wh = r[opts.warehouse_field];
		by_wh[wh] = by_wh[wh] || {};
		by_wh[wh][r.item_code] = (by_wh[wh][r.item_code] || 0) + isoft_warehouse_location_management.stock_qty_of(r);
	});

	return Promise.all(
		Object.keys(by_wh).map((wh) =>
			isoft_warehouse_location_management
				.resolve_locations(wh, Object.keys(by_wh[wh]), opts.direction || 'out', by_wh[wh])
				.then((res) => {
					Object.keys(res || {}).forEach((item) =>
						isoft_warehouse_location_management.remember_choice(frm, wh, item, res[item])
					);
				})
		)
	).then(() => frm._ip_where || {});
};

// ----------------------------------------------------------------------
// One click from the grid
// ----------------------------------------------------------------------
// The row form has the full button, but reaching it means expanding the row first.
// Dividing a line is common enough to deserve a single click, so the allocation column
// itself becomes the control: it reads as a summary and opens the dialog when clicked.
//
// opts: { table_field, cdt, warehouse_field, direction, feature }
isoft_warehouse_location_management.mount_grid_split = function (frm, opts) {
	const field = frm.fields_dict[opts.table_field || 'items'];
	const grid = field && field.grid;
	if (!grid || !grid.wrapper) return;

	const NS = '.ipgridsplit';
	const cell = '.grid-static-col[data-fieldname="' + isoft_warehouse_location_management.ALLOCATION_FIELD + '"]';
	const $grid = $(grid.wrapper);
	const $form = $(frm.wrapper);
	$grid.off(NS);
	$form.off('grid-row-render' + NS);

	isoft_warehouse_location_management.enabled(opts.feature).then((on) => {
		if (!on) return;

		// A location is a value first. It only becomes a control when the goods are
		// actually in more than one place — otherwise the cell is just where the line
		// was picked from, and inviting a click that leads nowhere is noise.
		const paint = ($row) => {
			const $cell = $row.find(cell);
			if (!$cell.length) return;
			const cdn = $row.attr('data-name');
			const row = cdn && locals[opts.cdt] && locals[opts.cdt][cdn];
			if (!row) return;
			const esc = frappe.utils.escape_html;
			const rows = isoft_warehouse_location_management.parse_allocation(row[isoft_warehouse_location_management.ALLOCATION_FIELD]);
			const summary = isoft_warehouse_location_management.picked_from(row);
			const editable = frm.doc.docstatus === 0
				&& isoft_warehouse_location_management.can_divide(frm, row, opts.warehouse_field);

			let html;
			if (!summary) {
				html = editable
					? '<span class="ip-pick ip-pick-cta">' + esc(__('Choose…')) + '</span>'
					: '<span class="ip-pick ip-pick-none">—</span>';
			} else if (rows.length > 1) {
				html = '<span class="ip-pick ip-pick-many' + (editable ? ' ip-pick-edit' : '') + '">'
					+ '<span class="ip-pick-n">' + rows.length + '</span>'
					+ '<span class="ip-pick-text">' + esc(summary) + '</span></span>';
			} else {
				html = '<span class="ip-pick' + (editable ? ' ip-pick-edit' : '') + '">'
					+ '<span class="ip-pick-text">' + esc(summary) + '</span></span>';
			}
			$cell.find('.static-area').html(html).attr(
				'title',
				editable ? __('Click to take this line from more than one location') : summary || ''
			);
		};

		// the cell owns the click, so it must not also toggle the row into edit mode
		$grid.on('click' + NS, cell, function (e) {
			const cdn = $(this).closest('.grid-row').attr('data-name');
			const row = cdn && locals[opts.cdt] && locals[opts.cdt][cdn];
            if (!row || !isoft_warehouse_location_management.can_divide(frm, row, opts.warehouse_field)) return;
			e.stopPropagation();
			e.preventDefault();
			isoft_warehouse_location_management.open_split_dialog({
				frm,
				cdt: opts.cdt,
				cdn,
				warehouse_field: opts.warehouse_field,
				direction: opts.direction,
			});
		});

		// frappe repaints grid rows constantly; this is the event it fires when it does
		$form.on('grid-row-render' + NS, (e, grid_row) => {
			if (!grid_row || grid_row.grid !== grid) return;
			paint($(grid_row.wrapper));
		});
		const repaint_all = () => $grid.find('.grid-row').each((_i, el) => paint($(el)));
		repaint_all();
		// knowing whether a line *could* be divided takes a round trip, so paint once
		// from what is already on the row and again once the answer is in
		isoft_warehouse_location_management.load_split_hints(frm, {
			table_field: opts.table_field,
			warehouse_field: opts.warehouse_field,
			direction: opts.direction,
		}).then(repaint_all);
	});
};

// Puts a "Pick from shelves…" button inside the expanded grid row, right under the
// split field — so the split is edited where the row is.
// opts: { frm, cdt, cdn, warehouse_field, qty_field, direction, feature }
// ----------------------------------------------------------------------
// The pick table
// ----------------------------------------------------------------------
// Where the item is, and how much of the line comes off each location — as one small
// table you type into. Nothing to open, nothing to click: the quantities are just moved
// between rows until they add up.
//
// It is built from plain data (candidates + the current allocation) and hands back the
// new allocation, so the desk row form and the till render the same thing.
//
// build({candidates, chosen, line_qty, uom, readonly}) -> html
isoft_warehouse_location_management.pick_table_html = function (o) {
	const esc = frappe.utils.escape_html;
	const fmt = isoft_warehouse_location_management.fmt;
	const cands = o.candidates || [];
	const chosen = o.chosen || {};
	const line = flt(o.line_qty);

	if (!cands.length) {
		return '<div class="ip-picktable ip-picktable-empty">'
			+ esc(__('Not on any location in this warehouse — it will stay unassigned.'))
			+ '</div>';
	}

	const placed = cands.reduce((a, c) => a + flt(chosen[c.location]), 0);
	const diff = line - placed;
	const state = Math.abs(diff) < 0.001 ? 'ok' : (diff > 0 ? 'short' : 'over');
	const note = state === 'ok'
		? __('all {0} placed', [fmt(line)])
		: (diff > 0 ? __('{0} still to place', [fmt(diff)]) : __('{0} too many', [fmt(-diff)]));

	const rows = cands.map((c) => {
		const qty = flt(chosen[c.location]);
		const name = c.is_unassigned ? __('Not put away') : (c.location_label || c.location);
		return '<tr data-location="' + esc(c.location) + '"'
			+ (c.is_unassigned ? ' class="ip-pt-loose"' : '') + '>'
			+ '<td class="ip-pt-loc">' + esc(name) + '</td>'
			+ '<td class="ip-pt-avail">' + esc(fmt(c.qty)) + '</td>'
			+ '<td class="ip-pt-qty">'
			+ (o.readonly
				? '<span>' + esc(fmt(qty)) + '</span>'
				: '<input type="number" class="ip-input ip-pt-input" step="any" min="0" max="'
					+ flt(c.qty) + '" value="' + (qty || '') + '" placeholder="0">')
			+ '</td></tr>';
	}).join('');

	return '<div class="ip-picktable">'
		+ '<table><thead><tr>'
		+ '<th>' + esc(__('Location')) + '</th>'
		+ '<th>' + esc(__('Available')) + '</th>'
		+ '<th>' + esc(__('Take')) + '</th>'
		+ '</tr></thead><tbody>' + rows + '</tbody></table>'
		+ '<div class="ip-pt-foot ip-pt-' + state + '">' + esc(note) + '</div>'
		+ '</div>';
};

/** What the resolver would do with this line, worked out from the candidates.
 *
 * The same walk as the server's `top_up`: start at the chosen location if one holds the
 * item, then take from each remaining candidate in order until the line is covered. It
 * is reproduced here so a row that has never been saved still opens on a real proposal
 * rather than a table of zeros — the server writes the same answer on save.
 */
isoft_warehouse_location_management.propose = function (candidates, qty, preferred) {
	const list = (candidates || []).slice();
	if (preferred) {
		const i = list.findIndex((c) => c.location === preferred);
		if (i > 0) list.unshift(list.splice(i, 1)[0]);
	}
	const rows = [];
	let left = flt(qty);
	for (const c of list) {
		if (left <= 0.000001) break;
		const take = Math.min(left, flt(c.qty));
		if (take <= 0.000001) continue;
		rows.push({ location: c.location, qty: take });
		left -= take;
	}
	return rows;
};

/** Read a rendered pick table back as an allocation. */
isoft_warehouse_location_management.pick_table_read = function ($scope) {
	return $scope.find('tbody tr').map((_i, tr) => ({
		location: $(tr).attr('data-location'),
		qty: flt($(tr).find('.ip-pt-input').val()),
	})).get().filter((r) => r.location && r.qty > 0);
};

isoft_warehouse_location_management.mount_split_button = function (opts) {
	const { frm, cdt, cdn, feature } = opts;
	const row = locals[cdt][cdn];
	if (!row) return;
	const grid_row = frm.fields_dict.items && frm.fields_dict.items.grid.grid_rows_by_docname[cdn];
	if (!grid_row || !grid_row.grid_form) return;

	const $wrapper = $(grid_row.grid_form.wrapper);
	$wrapper.find('.ip-split-mount').remove();

	isoft_warehouse_location_management.enabled(feature).then((on) => {
		if (!on) return;
		const $field = $wrapper.find('[data-fieldname="' + isoft_warehouse_location_management.ALLOCATION_FIELD + '"]').first();
		const $anchor = $field.length
			? $field
			: $wrapper.find('[data-fieldname="custom_from_location"]').first();
		if (!$anchor.length) return;

		const summary = isoft_warehouse_location_management.picked_from(row);
		// the stored value is JSON; nobody should have to read that to learn where the
		// goods came from, so the control shows the same words the grid does
		$field.find('.control-value, .like-disabled-input').first()
			.text(summary || __('not set'));

		// The table *is* the editor. Where the item is, and how much of the line comes off
		// each location, in one place you type into — no dropdown to open, no dialog to
		// click through, just quantities moved between rows until they add up.
		const readonly = frm.doc.docstatus !== 0;

		const apply = (rows) => {
			const kept = (rows || []).filter((r) => r.location && flt(r.qty) > 0);
			const sorted = kept.slice().sort((a, b) => flt(b.qty) - flt(a.qty));
			frappe.model.set_value(opts.cdt, opts.cdn, isoft_warehouse_location_management.ALLOCATION_FIELD,
				kept.length ? JSON.stringify(kept) : null);
			frappe.model.set_value(opts.cdt, opts.cdn, 'custom_from_location',
				sorted.length ? sorted[0].location : null);
			// the field above the table shows the same answer in words
			$field.find('.control-value, .like-disabled-input').first()
				.text(isoft_warehouse_location_management.picked_from(locals[opts.cdt][opts.cdn]) || __('not set'));
		};

		const offer = () => {
			$wrapper.find('.ip-pickinfo').remove();
			const where = isoft_warehouse_location_management.where_is(frm, row, opts.warehouse_field);
			if (where === null) return;                       // not asked yet

			const line_qty = isoft_warehouse_location_management.stock_qty_of(row);
			const stored = isoft_warehouse_location_management.parse_allocation(row[isoft_warehouse_location_management.ALLOCATION_FIELD]);
			const placed = stored.reduce((a, x) => a + flt(x.qty), 0);

			// An allocation that adds up is the answer. Anything else — a row that has
			// never been saved, or one whose quantity moved after it was settled — opens
			// on a fresh proposal, and that proposal is written onto the row, so the
			// table, the column in the grid and the saved document all say the same thing.
			let use = stored;
			if (!readonly && (!stored.length || Math.abs(placed - line_qty) > 0.001)) {
				use = isoft_warehouse_location_management.propose(where, line_qty, row.custom_from_location);
				apply(use);
			}
			const chosen = {};
			use.forEach((x) => { chosen[x.location] = flt(x.qty); });

			const $mount = $('<div class="ip-pickinfo">' + isoft_warehouse_location_management.pick_table_html({
				candidates: where,
				chosen: chosen,
				line_qty: line_qty,
				readonly: readonly,
			}) + '</div>');

			$mount.find('.ip-pt-input').on('change', function () {
				apply(isoft_warehouse_location_management.pick_table_read($mount));
				offer();
			});
			$anchor.after($mount);
		};
		offer();
		if (isoft_warehouse_location_management.where_is(frm, row, opts.warehouse_field) === null) {
			isoft_warehouse_location_management.load_split_hints(frm, {
				table_field: opts.table_field,
				warehouse_field: opts.warehouse_field,
				direction: opts.direction,
			}).then(offer);
		}
	});
};

// ----------------------------------------------------------------------
// Desk grid helper — resolve a location field on a child row of a real form
// ----------------------------------------------------------------------
// Fills the field in silently when there is exactly one answer, and explains itself
// in the row's description when there is more than one.
isoft_warehouse_location_management.resolve_grid_row = function (opts) {
	const { frm, cdt, cdn, item_field, warehouse_field, location_field, qty_field, direction,
		feature } = opts;
	const row = locals[cdt][cdn];
	if (!row) return Promise.resolve(null);

	const warehouse = row[warehouse_field];
	const item = row[item_field];
	if (!warehouse || !item) return Promise.resolve(null);

	return isoft_warehouse_location_management
		.enabled(feature)
		.then((on) => (on
			? isoft_warehouse_location_management.resolve_one(warehouse, item, direction || 'out',
				qty_field ? row[qty_field] : 0)
			: null))
		.then((res) => {
			if (!res) return null;
			// never overwrite a location the operator chose on purpose
			if (row[location_field]) return res;
			// The till never makes a cashier choose, and neither should this: whatever the
			// resolver leads with is filled in. A line that needs more than one location
			// still starts here — picking spills from the chosen one in resolver order —
			// so there is always a sensible answer to pre-select.
			isoft_warehouse_location_management.remember_choice(frm, warehouse, item, res);
			if (res.location && res.mode !== 'none') {
				frappe.model.set_value(cdt, cdn, location_field, res.location);
				if (res.mode === 'locked') {
					frappe.show_alert(
						{
							message: __('Row {0}: location {1} — {2}', [row.idx, res.location, res.reason]),
							indicator: 'blue',
						},
						4
					);
				}
			} else if (res.mode === 'none') {
				frappe.show_alert(
					{ message: __('Row {0}: {1}', [row.idx, res.reason]), indicator: 'orange' },
					5
				);
			}
			return res;
		});
};

// ----------------------------------------------------------------------
// Shared styles (the dashboard page carries its own, these cover desk forms too)
// ----------------------------------------------------------------------
$(document).ready(function () {
	if (document.getElementById('ip-location-control-css')) return;
	const css = `
	.ip-locctl { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-height: 28px; }
	.ip-loc-hint { font-size: 11.5px; color: var(--text-muted, #8d99a6); }
	.ip-loc-chip {
		display: inline-flex; align-items: center; gap: 6px;
		border: 1px solid var(--dark-border-color, #d1d8dd); border-radius: 4px;
		background: var(--control-bg, #f4f5f6); color: inherit;
		padding: 3px 9px; font-size: 12px; font-weight: 600; cursor: pointer;
	}
	.ip-loc-chip:hover { border-color: #0f766e; }
	.ip-loc-chip .ip-loc-qty { font-weight: 400; opacity: .65; font-variant-numeric: tabular-nums; }
	.ip-loc-chip.is-unassigned { border-style: dashed; font-weight: 500; }
	.ip-loc-why { font-size: 11px; color: var(--text-muted, #8d99a6); }
	.ip-loc-none { font-size: 11.5px; color: #b45309; }
	.ip-loc-split { display: flex; align-items: center; gap: 8px; flex-basis: 100%; font-size: 11.5px; }
	.ip-loc-split-label { color: var(--text-muted, #8d99a6); text-transform: uppercase; letter-spacing: .06em; font-size: 10px; }
	.ip-loc-split-plan { font-variant-numeric: tabular-nums; }
	.ip-loc-split-apply { border: 0; background: none; color: #0f766e; font-size: 11.5px; font-weight: 600; cursor: pointer; padding: 0; }
	.ip-loc-select { min-width: 150px; }
	.ip-split-head { display: flex; align-items: baseline; gap: 10px; font-size: 13px; margin-bottom: 4px; }
	.ip-split-head b { font-size: 18px; font-variant-numeric: tabular-nums; }
	.ip-split-diff { margin-left: auto; font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 3px; }
	.ip-split-diff.ok { color: #2f6b3c; background: rgba(47,107,60,.1); }
	.ip-split-diff.off { color: #b45309; background: rgba(180,83,9,.1); }
	.ip-split-note { font-size: 11.5px; color: var(--text-muted, #8d99a6); margin-bottom: 12px; }
	.ip-split-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.ip-split-table th { text-align: left; font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase;
		color: var(--text-muted, #8d99a6); padding: 6px 8px; border-bottom: 1px solid var(--dark-border-color, #d1d8dd); }
	.ip-split-table td { padding: 6px 8px; border-bottom: 1px solid var(--border-color, #ebeff2); }
	.ip-split-table .ip-input { width: 100%; }
	.ip-split-avail { font-variant-numeric: tabular-nums; color: var(--text-muted, #8d99a6); }
	.ip-split-loc { font-weight: 600; }
	.ip-split-tag { margin-left: 7px; font-size: 10px; text-transform: uppercase; letter-spacing: .05em;
		color: var(--text-muted, #8d99a6); }
	.ip-split-tag.warn { color: #b45309; }
	.ip-split-stale .ip-split-loc { color: #b45309; }
	.ip-split-del { border: 0; background: none; font-size: 17px; line-height: 1; color: var(--text-muted, #8d99a6); cursor: pointer; }
	.ip-split-del:hover { color: #9b2f2f; }
	.ip-split-actions { display: flex; gap: 14px; margin-top: 12px; }
	.ip-split-actions button { border: 0; background: none; color: #0f766e; font-size: 12.5px; font-weight: 600; cursor: pointer; padding: 0; }
	.ip-split-short { margin-top: 12px; font-size: 12px; color: #b45309; }
	.ip-split-mount { display: flex; align-items: center; gap: 10px; margin: -6px 0 10px; flex-wrap: wrap; }
	.ip-split-open { border: 1px solid var(--dark-border-color, #d1d8dd); background: var(--control-bg, #f4f5f6);
		border-radius: 4px; padding: 3px 10px; font-size: 12px; font-weight: 600; cursor: pointer; color: inherit; }
	.ip-split-open { display: inline-flex; align-items: center; gap: 6px; }
	.ip-split-open:hover { border-color: #0f766e; color: #0f766e; }
	.ip-split-open .fa { font-size: 11px; }
	.ip-split-why { font-size: 11.5px; color: var(--text-muted, #8d99a6); }
	.ip-split-uom { font-size: 11px; color: var(--text-muted, #8d99a6); margin-left: 8px; }

	/* above frappe's expanded grid row, which sits at 1051 */
	.modal.ip-above-grid { z-index: 1070; }
	.modal-backdrop.ip-above-grid-backdrop { z-index: 1065; }

	/* Where the item is, stated without anyone having to ask. */
	.ip-pickinfo { margin: -2px 0 12px; }

	/* the pick table: where it is, and how much of the line comes off each location */
	.ip-picktable { border: 1px solid var(--border-color, #ebeff2); border-radius: 5px;
		overflow: hidden; max-width: 420px; }
	.ip-picktable table { width: 100%; border-collapse: collapse; font-size: 12px; }
	.ip-picktable th { text-align: left; font-size: 10px; letter-spacing: .06em;
		text-transform: uppercase; color: var(--text-muted, #8d99a6); font-weight: 600;
		padding: 5px 9px; background: var(--control-bg, #f4f5f6);
		border-bottom: 1px solid var(--border-color, #ebeff2); }
	.ip-picktable th:nth-child(2), .ip-picktable td:nth-child(2) { text-align: right; width: 84px; }
	.ip-picktable th:nth-child(3), .ip-picktable td:nth-child(3) { width: 92px; }
	.ip-picktable td { padding: 4px 9px; border-bottom: 1px solid var(--border-color, #ebeff2); }
	.ip-picktable tr:last-child td { border-bottom: 0; }
	.ip-pt-loc { font-weight: 600; }
	.ip-pt-loose .ip-pt-loc { font-weight: 400; color: var(--text-muted, #8d99a6); }
	.ip-pt-avail { font-variant-numeric: tabular-nums; color: var(--text-muted, #8d99a6); }
	.ip-pt-qty .ip-pt-input { width: 100%; padding: 2px 6px; font-size: 12px; text-align: right;
		font-variant-numeric: tabular-nums; }
	.ip-pt-foot { padding: 5px 9px; font-size: 11px; background: var(--control-bg, #f4f5f6);
		border-top: 1px solid var(--border-color, #ebeff2); }
	.ip-pt-ok { color: #0f766e; }
	.ip-pt-short { color: #b45309; }
	.ip-pt-over { color: #9b2f2f; }
	.ip-picktable-empty { font-size: 11.5px; color: #b45309; border: 0; }

	/* The Picked From Location cell. A value first; a control only when the goods are
	   in more than one place. */
	.ip-pick { display: inline-flex; align-items: baseline; gap: 6px; max-width: 100%; }
	.ip-pick-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
		font-variant-numeric: tabular-nums; }
	.ip-pick-none { color: var(--text-muted, #8d99a6); }
	.ip-pick-edit { cursor: pointer; }
	.ip-pick-edit:hover .ip-pick-text { color: #0f766e; text-decoration: underline;
		text-decoration-style: dotted; text-underline-offset: 2px; }
	.ip-pick-cta { color: var(--text-muted, #8d99a6); cursor: pointer;
		border-bottom: 1px dashed currentColor; }
	.ip-pick-cta:hover { color: #0f766e; }
	.ip-pick-n { flex: none; min-width: 15px; height: 15px; line-height: 15px; text-align: center;
		border-radius: 8px; background: #0f766e; color: #fff; font-size: 9.5px; font-weight: 700;
		padding: 0 4px; }
	`;
	$('<style id="ip-location-control-css"></style>').text(css).appendTo(document.head);
});
