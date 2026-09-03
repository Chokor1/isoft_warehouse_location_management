// Copyright (c) 2026, ISOFT LDA
// Author: Abbass Chokor
// For license information, please see license.txt
// Isoft Location Manager — custom SPA: Dashboard, Warehouse Explorer, Requests Manager.

frappe.provide('isoft_warehouse_location_management');

isoft_warehouse_location_management.THEMES = {
	Blue: { p: '#2563eb', d: '#1e40af', a: '#3b82f6' },
	Green: { p: '#059669', d: '#047857', a: '#10b981' },
	Purple: { p: '#7c3aed', d: '#5b21b6', a: '#8b5cf6' },
	Orange: { p: '#ea580c', d: '#c2410c', a: '#f97316' },
	Slate: { p: '#475569', d: '#334155', a: '#64748b' },
	Dark: { p: '#0f172a', d: '#020617', a: '#334155' },
};

// Hide the Frappe desk chrome (top navbar + page head) while on this page, like Isoft
// Insights, so it renders as a standalone app. Restored automatically when leaving.
isoft_warehouse_location_management.CHROME = 'header.navbar, .navbar.sticky-top, .navbar.navbar-default.navbar-fixed-top, .navbar-expand-lg, .page-head';
isoft_warehouse_location_management.apply_chrome = function () {
	const route = (frappe.get_route_str && frappe.get_route_str()) || '';
	const standalone = route.indexOf('isoft-location-manager') !== -1;
	const $chrome = $(isoft_warehouse_location_management.CHROME);
	if (standalone) {
		$chrome.hide();
		$('.layout-main-location-wrapper').css('margin-top', '0');
		$('.page-container').css('padding-top', '0');
	} else {
		$chrome.show();
		$('.layout-main-location-wrapper').css('margin-top', '');
		$('.page-container').css('padding-top', '');
	}
};

frappe.pages['isoft-location-manager'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: 'Isoft Location Manager', single_column: true });
	$(wrapper).find('.page-body').addClass('full-width');
	frappe.pages['isoft-location-manager'].app = new isoft_warehouse_location_management.App(page);
	isoft_warehouse_location_management.apply_chrome();
	[100, 400, 900].forEach((t) => setTimeout(isoft_warehouse_location_management.apply_chrome, t));
	if (!isoft_warehouse_location_management._chrome_bound) {
		isoft_warehouse_location_management._chrome_bound = true;
		$(window).on('hashchange', isoft_warehouse_location_management.apply_chrome);
	}
};

frappe.pages['isoft-location-manager'].on_page_show = function () {
	isoft_warehouse_location_management.apply_chrome();
	const app = frappe.pages['isoft-location-manager'].app;
	if (app && app.ready) app.show(app.current);
};

frappe.pages['isoft-location-manager'].on_page_hide = function () {
	$(isoft_warehouse_location_management.CHROME).show();
	$('.layout-main-location-wrapper').css('margin-top', '');
	$('.page-container').css('padding-top', '');
};

isoft_warehouse_location_management.App = class {
	constructor(page) {
		this.page = page;
		this.ready = false;
		this.current = 'dashboard';
		this.ctx = {};
		this.scope = localStorage.getItem('ip_scope') || '';
		this.whMode = 'explorer';
		this.$body = $('<div class="ip-root"></div>').appendTo(page.main);
		this.boot();
	}

	api(method, args) {
		return frappe
			.call({ method: 'isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager.' + method, args: args || {} })
			.then((r) => r.message);
	}

	boot() {
		this.api('get_context').then((ctx) => {
			this.ctx = ctx || {};
			this.warehouses = ctx.warehouses || [];
			this.wmap = {};
			this.warehouses.forEach((w) => (this.wmap[w.name] = w));
			this.apply_theme();
			this.render_shell();
			this.ready = true;
			this.show('dashboard');
		});
	}

	apply_theme() {
		// Single fixed accent; light/dark comes from Frappe's own theme (data-theme on <html>).
		const t = isoft_warehouse_location_management.THEMES.Blue;
		const r = document.documentElement;
		r.style.setProperty('--ip-primary', t.p);
		r.style.setProperty('--ip-primary-dark', t.d);
		r.style.setProperty('--ip-accent', t.a);
	}

	// ------------------------------------------------------------------ shell
	wh_depth(name) {
		let depth = 0, cur = this.wmap[name];
		while (cur && cur.parent_warehouse && this.wmap[cur.parent_warehouse]) {
			depth++; cur = this.wmap[cur.parent_warehouse];
		}
		return depth;
	}

	warehouse_options(selected, all_label) {
		let html = `<option value="">${frappe.utils.escape_html(all_label || 'All my warehouses')}</option>`;
		this.warehouses.forEach((w) => {
			const pad = '&nbsp;&nbsp;'.repeat(this.wh_depth(w.name));
			const tag = w.is_group ? ' •' : '';
			html += `<option value="${frappe.utils.escape_html(w.name)}" ${w.name === selected ? 'selected' : ''}>${pad}${frappe.utils.escape_html(w.warehouse_name || w.name)}${tag}</option>`;
		});
		return html;
	}

	render_shell() {
		const tabs = [
			{ key: 'dashboard', label: 'Dashboard', icon: 'fa-tachometer' },
			{ key: 'warehouse', label: 'Locations', icon: 'fa-th-large' },
			{ key: 'ledger', label: 'Ledger', icon: 'fa-list' },
		];
		if (this.ctx.is_admin) tabs.push({ key: 'settings', label: 'Settings', icon: 'fa-cog' });
		const tabs_html = tabs
			.map((t) => `<button class="ip-tab" data-view="${t.key}"><i class="fa ${t.icon}"></i> ${t.label}</button>`)
			.join('');

		this.$body.html(`
			<div class="ip-bar">
				<div class="ip-brand">
					<div class="ip-brand-logo">${this.logo_svg()}</div>
					<div><div class="ip-brand-title">Isoft Location Manager</div>
					<div class="ip-brand-sub">Warehouse Preparation</div></div>
				</div>
				<div class="ip-scope">
					<i class="fa fa-filter"></i>
					<select class="ip-input ip-scope-select">${this.warehouse_options(this.scope)}</select>
				</div>
				<div class="ip-tabs">${tabs_html}</div>
			</div>
			<div class="ip-content"></div>`);

		this.$content = this.$body.find('.ip-content');
		this.$body.find('.ip-tab').on('click', (e) => this.show($(e.currentTarget).data('view')));
		this.$body.find('.ip-scope-select').on('change', (e) => {
			this.scope = e.target.value;
			localStorage.setItem('ip_scope', this.scope);
			this.show(this.current);
		});
	}

	logo_svg() {
		return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
			<circle cx="6" cy="4.5" r="2.3"/><path d="M6 6.8 V13"/><path d="M6 13 L4.2 18.5 M6 13 L7.8 18.5"/>
			<path d="M6 8.4 L10.5 9.2 M6 10.6 L10.5 13.4"/><rect x="10.5" y="8.5" width="7" height="6.6" rx="1"/><path d="M10.5 11.8 H17.5"/></svg>`;
	}

	set_active() {
		this.$body.find('.ip-tab').removeClass('active');
		this.$body.find(`.ip-tab[data-view="${this.current}"]`).addClass('active');
		// scope selector is relevant on dashboard/warehouse/requests, not settings
		this.$body.find('.ip-scope').toggle(this.current !== 'settings');
	}

	show(view) {
		this.current = view;
		this.set_active();
		// the dock is mounted on the body so it can pin to the viewport — that means it
		// has to be taken down deliberately when the view changes
		this.teardown_dock();
		this.$content.html('<div class="ip-loading"><div class="ip-spin"></div></div>');
		if (view === 'dashboard') this.dashMode === 'check' ? this.render_check_panel() : this.render_dashboard();
		else if (view === 'warehouse') this.render_warehouse();
		else if (view === 'ledger') this.render_ledger();
		else if (view === 'settings') this.render_settings();
	}

	// ------------------------------------------------------------------ DASHBOARD
	render_dashboard() {
		if (this.dashMode === 'check') return this.render_check_panel();
		const esc = frappe.utils.escape_html;
		this.$content.html('<div class="ip-loading"><div class="ip-spin"></div></div>');

		this.api('get_dashboard_stats', { warehouse: this.scope }).then((d) => {
			const pct = Math.round(d.coverage);

			this.$content.html(`
				<div class="ip-location-title">Put away ${this.scope_label()}</div>

				<div class="ip-card ip-fade ip-cover" style="--i:0">
					<div class="ip-cover-head">
						<div>
							<div class="ip-cover-pct">${pct}<span>%</span></div>
							<div class="ip-cover-cap">${esc(__('of the units here are on a location'))}</div>
						</div>
						<div class="ip-cover-nums">
							<div><label>${esc(__('On a location'))}</label>
								<b>${format_number(d.units_shelved)}</b></div>
							<div><label>${esc(__('Still loose'))}</label>
								<b class="loose">${format_number(d.units_loose)}</b></div>
						</div>
					</div>
					<div class="ip-cover-bar">
						<span class="ip-seg-fill done" style="width:${pct}%"></span>
						<span class="ip-seg-fill todo" style="width:${100 - pct}%"></span>
					</div>
					<div class="ip-cover-legend">
						<span><i class="dot done"></i>${esc(__('{0} items fully put away', [d.items_shelved]))}</span>
						<span><i class="dot part"></i>${esc(__('{0} partly', [d.items_partial]))}</span>
						<span><i class="dot todo"></i>${esc(__('{0} not at all', [d.items_loose]))}</span>
					</div>
				</div>

				<div class="ip-kpis">
					${this.tile('fa-map-marker', d.locations, __('locations'),
						d.locations_empty ? __('{0} empty', [d.locations_empty]) : __('all holding stock'), 'blue')}
					${this.tile('fa-exchange', d.moves_7d, __('movements this week'),
						Object.entries(d.moves_by_type || {}).map((e) => e[0] + ' ' + e[1]).join(' · ') || __('nothing moved'), 'blue')}
					${this.tile(d.locations_over ? 'fa-warning' : 'fa-check-circle', d.locations_over,
						__('over capacity'),
						d.locations_over ? __('holding more than declared') : __('all within capacity'),
						d.locations_over ? 'amber' : 'green')}
					<div class="ip-kpi ip-kpi-${d.homeless_items ? 'amber' : 'green'} ip-fade ip-click" data-dock="1" style="--i:3">
						<div class="ip-kpi-icon"><i class="fa fa-home"></i></div>
						<div><div class="ip-kpi-value">${d.homeless_items}</div>
						<div class="ip-kpi-label">${esc(__('items with no declared location'))}</div>
						<div class="ip-kpi-sub">${esc(__('nothing says where they belong'))}</div></div>
					</div>
				</div>

				<div class="ip-dash-two">
					<div class="ip-card ip-fade" style="--i:4">
						<div class="ip-card-head"><h3>${esc(__('Holding the most'))}</h3></div>
						${(d.busiest || []).length ? `<table class="ip-table ip-mini"><tbody>${
							d.busiest.map((b) => `<tr data-loc="${esc(b.location)}">
								<td><span class="ip-led-loc-cell">${esc(b.label)}</span></td>
								<td class="ip-muted">${esc(__('{0} item(s)', [b.items]))}</td>
								<td class="ip-num"><b>${format_number(b.qty)}</b></td>
								<td class="ip-num ip-muted">${b.fill === null ? '' : Math.round(b.fill) + '% ' + esc(__('full'))}</td>
							</tr>`).join('')}</tbody></table>`
							: `<div class="ip-mini-empty">${esc(__('Nothing is on a location yet.'))}</div>`}
					</div>
					<div class="ip-card ip-fade" style="--i:5">
						<div class="ip-card-head"><h3>${esc(__('Busiest this week'))}</h3></div>
						${(d.active_locations || []).length ? `<table class="ip-table ip-mini"><tbody>${
							d.active_locations.map((a) => `<tr>
								<td><span class="ip-led-loc-cell">${esc(a.location)}</span></td>
								<td class="ip-num"><b>${a.moves}</b></td>
								<td class="ip-muted">${esc(__('movement(s)'))}</td>
							</tr>`).join('')}</tbody></table>`
							: `<div class="ip-mini-empty">${esc(__('Nothing has moved in the last week.'))}</div>`}
					</div>
				</div>

				<div class="ip-location-title">${esc(__('Location Health'))}</div>
				<div class="ip-kpis"><div class="ip-health"></div></div>`);

			// The partition should always balance. When it stops, this is where it shows.
			this.api('get_drift', { warehouse: this.scope }).then((rows) => {
				const n = (rows || []).length;
				this.$content.find('.ip-health').replaceWith(`
					<div class="ip-kpi ip-kpi-${n ? 'amber' : 'green'} ip-fade ip-click" data-check="1" style="--i:0">
						<div class="ip-kpi-icon"><i class="fa ${n ? 'fa-balance-scale' : 'fa-check-circle'}"></i></div>
						<div><div class="ip-kpi-value">${n}</div>
						<div class="ip-kpi-label">${esc(n
							? __('items claiming more than the warehouse holds')
							: __('every location balance matches real stock'))}</div></div>
					</div>`);
				this.$content.find('[data-check]').on('click', () => {
					this.dashMode = 'check';
					this.show('dashboard');
				});
			});

			this.$content.find('[data-loc]').on('click', () => this.show('warehouse'));
			this.$content.find('[data-dock]').on('click', () => {
				localStorage.setItem('ip_dock_open', '1');
				this.show('warehouse');
			});
		});
	}

	tile(icon, value, label, sub, cls) {
		const esc = frappe.utils.escape_html;
		return `<div class="ip-kpi ip-kpi-${cls} ip-fade" style="--i:0">
			<div class="ip-kpi-icon"><i class="fa ${icon}"></i></div>
			<div><div class="ip-kpi-value">${esc(String(value))}</div>
			<div class="ip-kpi-label">${esc(label)}</div>
			<div class="ip-kpi-sub">${esc(sub)}</div></div>
		</div>`;
	}

	scope_label() {
		if (!this.scope) return '<span class="ip-scope-chip">All my warehouses</span>';
		const w = this.wmap[this.scope];
		const grp = w && w.is_group ? ' (incl. children)' : '';
		return `<span class="ip-scope-chip">${frappe.utils.escape_html((w && w.warehouse_name) || this.scope)}${grp}</span>`;
	}

	// ------------------------------------------------------------------ WAREHOUSE EXPLORER
	// Two ways to read the same warehouse:
	//   Contents — what is on every location (the default: stock is the point)
	//   Layout   — the zones and locations themselves, without the stock detail
	// Layout is the map you use when you are organising the place rather than working it.
	render_warehouse() {
		const esc = frappe.utils.escape_html;
		const search = this.whSearch || '';
		const view = this.locView || (this.locView = 'contents');
		this.$content.html(`
			<div class="ip-toolbar">
				${this.ctx.can_manage ? `
					<button class="ip-btn ip-btn-primary ip-new-location"><i class="fa fa-plus"></i> New Location</button>
					<button class="ip-btn ip-zones-btn"><i class="fa fa-th-large"></i> ${esc(__('Zones'))}</button>
` : ''}
				<div class="ip-viewtoggle" role="group" aria-label="${esc(__('View'))}">
					<button class="ip-vt${view === 'contents' ? ' on' : ''}" data-view="contents"
						title="${esc(__('Show what each location holds'))}"><i class="fa fa-cubes"></i> ${esc(__('Contents'))}</button>
					<button class="ip-vt${view === 'layout' ? ' on' : ''}" data-view="layout"
						title="${esc(__('Show the zones and locations only'))}"><i class="fa fa-map-o"></i> ${esc(__('Layout'))}</button>
				</div>
				<select class="ip-input ip-zone-filter"><option value="">${esc(__('All zones'))}</option></select>
				<div class="ip-search"><i class="fa fa-search"></i>
					<input class="ip-input ip-wh-search" placeholder="Search item or location…" value="${esc(search)}"></div>
			</div>
			<div class="ip-explorer"><div class="ip-loading"><div class="ip-spin"></div></div></div>`);

		const $wrap = this.$content.find('.ip-explorer');
		const load = () => {
			this.api('get_locations_with_items', { warehouse: this.scope, search: this.whSearch || '' }).then((secs) => {
				if (!secs.length) {
					$wrap.html(`<div class="ip-empty-lg"><i class="fa fa-inbox"></i>
						<div>${esc(__('No locations here yet.'))}</div>
						<div class="ip-muted" style="font-size:12px;margin-top:6px">${esc(
							__('Create one, then put stock away from the bar below.'))}</div></div>`);
					return;
				}
				this.allSecs = secs;
				this.paint_locations($wrap);
			});
		};
		// zones are cheap and rarely change, so the filter is filled once per visit
		this.api('get_zones', { warehouse: this.scope }).then((zones) => {
			this.zones = zones || [];
			const $sel = this.$content.find('.ip-zone-filter');
			this.zones.forEach((z) => $sel.append(
				`<option value="${esc(z.name)}"${z.name === this.zoneFilter ? ' selected' : ''}>${
					esc(z.zone_name || z.zone_code)}</option>`));
			if (this.zoneFilter && !this.zones.some((z) => z.name === this.zoneFilter)) {
				this.zoneFilter = '';
			}
			$sel.append(`<option value="__none__"${this.zoneFilter === '__none__' ? ' selected' : ''}>${
				esc(__('Not in a zone'))}</option>`);
		});
		load();

		this.$content.find('.ip-vt').on('click', (e) => {
			this.locView = $(e.currentTarget).data('view');
			this.render_warehouse();
		});
		this.$content.find('.ip-zone-filter').on('change', (e) => {
			this.zoneFilter = e.target.value;
			if (this.allSecs) this.paint_locations($wrap); else load();
		});
		this.$content.find('.ip-zones-btn').on('click', () => this.zones_dialog());

		let t;
		this.$content.find('.ip-wh-search').on('input', (e) => {
			this.whSearch = e.target.value;
			clearTimeout(t); t = setTimeout(load, 220);
		});
		// the dock lives alongside the board, not inside it — it survives searches and
		// view switches, and it is the one place unassigned stock is shown
		if (this.ctx.is_preparer || this.ctx.can_manage) this.render_unassigned_dock();

		this.$content.find('.ip-new-location').on('click', () => this.create_locations_dialog());
	}

	// ---- reconciliation, reached from the Dashboard ----
	// The partition should always balance. It stops balancing when stock leaves through
	// a document the app does not mirror, so this is the page that says whether the
	// location ledger can still be trusted.
	render_check_panel() {
		const esc = frappe.utils.escape_html;
		this.$content.html(`
			<div class="ip-panel ip-fade" style="--i:0">
				<div class="ip-panel-head">
					<button class="ip-back" title="${__('Back')}"><i class="fa fa-arrow-left"></i></button>
					<div class="ip-panel-title">${__('Locations vs Real Stock')}</div>
				</div>
				<div class="ip-panel-body"><div class="ip-loading"><div class="ip-spin"></div></div></div>
			</div>`);
		this.$content.find('.ip-back').on('click', () => { this.dashMode = null; this.show('dashboard'); });

		const load = () => this.api('get_drift', { warehouse: this.scope }).then((rows) => {
			const $b = this.$content.find('.ip-panel-body');
			if (!rows.length) {
				$b.html(`<div class="ip-empty-lg"><i class="fa fa-check-circle"></i>
					<div>${esc(__('Every location balance matches real stock.'))}</div></div>`);
				return;
			}
			$b.html(`
				<div class="ip-muted" style="margin-bottom:12px">${esc(__(
					'{0} item(s) where the locations claim more than the warehouse holds. This happens when stock ' +
					'leaves on a document that never named a location — correcting one posts a Stock Out so the ' +
					'change is on the record.', [rows.length]))}</div>
				<table class="ip-table"><thead><tr>
					<th>${esc(__('Item'))}</th><th>${esc(__('Warehouse'))}</th>
					<th class="ip-num">${esc(__('Locations claim'))}</th>
					<th class="ip-num">${esc(__('Really there'))}</th>
					<th class="ip-num">${esc(__('Over'))}</th><th></th></tr></thead>
				<tbody>${rows.map((r) => `<tr>
					<td><div class="ip-ti-code">${esc(r.item_code)}</div>
						<div class="ip-ti-name">${esc(r.item_name || '')}</div></td>
					<td>${esc(r.warehouse)}</td>
					<td class="ip-num">${format_number(r.assigned)}</td>
					<td class="ip-num">${format_number(r.bin_qty)}</td>
					<td class="ip-num" style="color:#b45309;font-weight:700">${format_number(r.over_claimed)}</td>
					<td><button class="ip-btn ip-btn-light ip-fix" data-item="${esc(r.item_code)}"
						data-wh="${esc(r.warehouse)}">${esc(__('Correct'))}</button></td>
				</tr>`).join('')}</tbody></table>`);

			$b.find('.ip-fix').on('click', (e) => {
				const $btn = $(e.currentTarget);
				frappe.confirm(
					__('Write {0} down to what the warehouse actually holds?', [$btn.data('item')]),
					() => this.api('clear_drift', { warehouse: $btn.data('wh'), item_code: $btn.data('item') })
						.then((r) => {
							frappe.show_alert({
								message: __('Corrected by {0}', [format_number(r.corrected)]),
								indicator: 'green',
							});
							load();
						})
				);
			});
		});
		load();
	}

	leaf_scope() {
		const w = this.wmap[this.scope];
		return this.scope && w && !w.is_group ? this.scope : '';
	}

	create_locations_dialog() {
		const d = new frappe.ui.Dialog({
			title: __('Create Locations'),
			size: 'large',
			fields: [
				{ fieldtype: 'Link', fieldname: 'warehouse', label: __('Warehouse'), options: 'Warehouse', reqd: 1,
					default: this.leaf_scope(),
					// only warehouses Isoft Location Manager is switched on for
					get_query: () => {
						const names = (this.warehouses || []).filter((w) => !w.is_group).map((w) => w.name);
						return { filters: names.length ? { name: ['in', names] } : { is_group: 0 } };
					} },
				{ fieldtype: 'HTML', fieldname: 'editor' },
			],
			primary_action_label: __('Create'),
			primary_action: (v) => {
				const rows = [];
				const seen = {};
				$w.find('.ip-loc-row').each(function () {
					const code = ($(this).find('.sc-code').val() || '').trim();
					if (!code || seen[code]) return;
					seen[code] = 1;
					rows.push({ location_code: code, description: ($(this).find('.sc-desc').val() || '').trim() || null });
				});
				if (!v.warehouse) { frappe.msgprint(__('Select a warehouse.')); return; }
				if (!rows.length) { frappe.msgprint(__('Add at least one location code.')); return; }
				this.api('create_locations', { warehouse: v.warehouse, rows: JSON.stringify(rows) }).then((res) => {
					d.hide();
					let msg = __('{0} location(s) created', [res.created]);
					if (res.skipped && res.skipped.length) msg += ' · ' + __('skipped (existing): {0}', [res.skipped.join(', ')]);
					frappe.show_alert({ message: msg, indicator: res.created ? 'green' : 'orange' });
					this.show('warehouse');
				});
			},
		});

		const $w = d.get_field('editor').$wrapper;
		$w.html(`
			<div class="ip-loc-tools">
				<div class="ip-muted" style="font-size:12px;margin-right:auto">${__('Add one or more locations, or import a CSV.')}</div>
				<button type="button" class="btn btn-xs btn-default ip-loc-tpl"><i class="fa fa-download"></i> ${__('Template')}</button>
				<label class="btn btn-xs btn-default" style="margin:0;cursor:pointer"><input type="file" accept=".csv,.txt" class="ip-loc-file" hidden><i class="fa fa-upload"></i> ${__('Import CSV')}</label>
			</div>
			<div class="ip-loc-head"><span class="h-code">${__('Location Code')}</span><span class="h-desc">${__('Description')}</span><span class="h-del"></span></div>
			<div class="ip-loc-rows"></div>
			<button type="button" class="ip-btn ip-btn-light ip-add-sec" style="margin-top:4px"><i class="fa fa-plus"></i> ${__('Add location')}</button>`);

		const addRow = (code, desc) => {
			const $r = $(`<div class="ip-loc-row">
				<input class="ip-input sc-code" placeholder="${__('e.g. A-01')}">
				<input class="ip-input sc-desc" placeholder="${__('Description (optional)')}">
				<button type="button" class="ip-row-del" title="${__('Remove')}"><i class="fa fa-times"></i></button>
			</div>`).appendTo($w.find('.ip-loc-rows'));
			if (code) $r.find('.sc-code').val(code);
			if (desc) $r.find('.sc-desc').val(desc);
			$r.find('.ip-row-del').on('click', () => { if ($w.find('.ip-loc-row').length > 1) $r.remove(); else { $r.find('input').val(''); } });
		};

		$w.find('.ip-add-sec').on('click', () => addRow());
		$w.find('.ip-loc-tpl').on('click', () =>
			this._download_csv('locations-template.csv', ['location_code', 'description'], ['A-01', 'Aisle A - Shelf 1']));
		$w.find('.ip-loc-file').on('change', async (e) => {
			const text = await this._read_file(e.currentTarget);
			e.currentTarget.value = '';
			if (!text) return;
			const parsed = this._parse_csv(text)
				.map((o) => ({ code: o.location_code || o.code || '', desc: o.description || '' }))
				.filter((o) => o.code);
			if (!parsed.length) { frappe.msgprint(__('No location codes found in the file.')); return; }
			// drop an initial empty row, then append imported ones
			const $first = $w.find('.ip-loc-row').first();
			if ($first.length && !($first.find('.sc-code').val() || '').trim()) $first.remove();
			parsed.forEach((o) => addRow(o.code, o.desc));
			frappe.show_alert({ message: __('{0} row(s) imported — review and Create', [parsed.length]), indicator: 'blue' });
		});

		addRow();
		d.show();
	}

	// ------------------------------------------------------------------
	// What one location holds
	// ------------------------------------------------------------------
	// Editing a shelf is editing its contents, not its label. Every change here is a
	// re-shelving inside the same warehouse: lower a line and the difference goes back
	// to unassigned stock, raise it and it comes from there. Nothing on this screen can
	// invent or destroy stock.
	// ---- CSV helpers (client-side) ----
	_download_csv(filename, headers, sample) {
		const enc = (v) => (/[",\n]/.test(v) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
		const lines = [headers.join(',')];
		if (sample) lines.push(sample.map(enc).join(','));
		const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
		URL.revokeObjectURL(url);
	}

	_parse_csv(text) {
		text = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
		const rows = []; let field = '', row = [], inq = false;
		for (let i = 0; i < text.length; i++) {
			const c = text[i];
			if (inq) {
				if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inq = false; }
				else field += c;
			} else if (c === '"') inq = true;
			else if (c === ',') { row.push(field); field = ''; }
			else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
			else field += c;
		}
		if (field.length || row.length) { row.push(field); rows.push(row); }
		const header = (rows.shift() || []).map((h) => h.trim().toLowerCase().replace(/\s+/g, '_'));
		return rows.filter((r) => r.some((c) => (c || '').trim() !== '')).map((r) => {
			const o = {}; header.forEach((h, i) => (o[h] = (r[i] || '').trim())); return o;
		});
	}

	_read_file(input) {
		return new Promise((res, rej) => {
			const f = input && input.files && input.files[0];
			if (!f) { res(null); return; }
			const fr = new FileReader();
			fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsText(f);
		});
	}

	// ------------------------------------------------------------------
	// What one location holds
	// ------------------------------------------------------------------
	// Editing a shelf is editing its contents, not its label. Every change here is a
	// re-shelving inside the same warehouse: lower a line and the difference goes back
	// to unassigned stock, raise it and it comes from there. Nothing on this screen can
	// invent or destroy stock.
	location_edit_dialog(sec) {
		if (!sec) return;
		const esc = frappe.utils.escape_html;
		const name = sec.location || sec.name;

		const d = new frappe.ui.Dialog({
			title: __('Location {0}', [sec.location_code || name]),
			size: 'large',
			fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
			primary_action_label: __('Apply'),
			primary_action: () => apply(),
		});
		const $body = d.get_field('body').$wrapper;
		let contents = null;
		let zone_options = [];

		const rows_html = () => (contents.items || []).map((it) => `
			<tr data-item="${esc(it.item_code)}">
				<td>
					<div class="ip-ti-code">${esc(it.item_code)}</div>
					<div class="ip-ti-name">${esc(it.item_name || '')}</div>
				</td>
				<td style="width:150px">
					<input type="number" class="ip-input ip-loc-qty" step="any" min="0"
						value="${flt(it.qty)}" data-was="${flt(it.qty)}">
					<div class="ip-loc-hint">${esc(__('{0} loose in the warehouse', [format_number(it.loose)]))}</div>
				</td>
				<td style="width:186px">
					<div class="ip-loc-defaults">
						<button type="button" class="ip-loc-def${it.default_out ? ' on' : ''}" data-dir="out"
							title="${esc(it.out_elsewhere
								? __('Pick from here instead of {0}', [it.out_elsewhere])
								: __('Take stock of this item from here first'))}">
							<i class="fa fa-sign-out"></i> ${esc(__('Pick from here'))}</button>
					</div>
					<button class="ip-loc-return" type="button"
						${flt(it.qty) <= 0 ? 'disabled' : ''}>${esc(__('All to unassigned'))}</button>
				</td>
			</tr>`).join('');

		const render = () => {
			const loc = contents.location;
			if (contents.is_unassigned) {
				$body.html(`<div class="ip-empty-lg"><i class="fa fa-inbox"></i>
					<div>${esc(__('Unassigned stock is whatever is left over.'))}</div>
					<div class="ip-muted" style="font-size:12px;margin-top:6px">${esc(
						__('It is calculated, not stored — manage it from the bar at the bottom of the board.'))}</div></div>`);
				d.get_primary_btn().hide();
				return;
			}
			$body.html(`
				<div class="ip-loc-head">
					<div><label>${esc(__('Warehouse'))}</label><div>${esc(loc.warehouse)}</div></div>
					<div><label>${esc(__('Type'))}</label><div>${esc(loc.location_type || '—')}</div></div>
					<div><label>${esc(__('Holding'))}</label>
						<div class="ip-loc-total">${format_number(contents.total_qty)}</div></div>
				</div>
				${contents.items.length ? `
					<table class="ip-table ip-loc-table">
						<thead><tr>
							<th>${esc(__('Item'))}</th>
							<th>${esc(__('This location holds'))}</th>
							<th>${esc(__('Pick location'))}</th>
						</tr></thead>
						<tbody>${rows_html()}</tbody>
					</table>
					<div class="ip-loc-note">${esc(__(
						'Lower a quantity and the difference returns to unassigned stock. Raise it and it is taken from there — so a location can never claim more than the warehouse holds.'))}</div>`
					: `<div class="ip-empty-lg"><i class="fa fa-inbox"></i>
						<div>${esc(__('Nothing is kept here yet.'))}</div>
						<div class="ip-muted" style="font-size:12px;margin-top:6px">${esc(
							__('Drag an item onto this column, or use Put away on the bar below.'))}</div></div>`}
				<div class="ip-loc-settings">
					<label>${esc(__('Description'))}
						<input class="ip-input ip-loc-desc" value="${esc(loc.description || '')}"></label>
					<label>${esc(__('Zone'))}
						<select class="ip-input ip-loc-zone">
							<option value="">${esc(__('Not in a zone'))}</option>
							${zone_options.map((z) => `<option value="${esc(z.name)}"${
								z.name === (loc.zone || '') ? ' selected' : ''}>${
								esc(z.zone_name || z.zone_code)}</option>`).join('')}
						</select></label>
					<label class="ip-check"><input type="checkbox" class="ip-loc-active"
						${loc.is_active ? 'checked' : ''}> ${esc(__('Active'))}</label>
				</div>`);

			$body.find('.ip-loc-return').on('click', (e) => {
				const $row = $(e.currentTarget).closest('tr');
				$row.find('.ip-loc-qty').val(0);
			});

			// Only picking has a declared location. Where something is put away is decided
			// at the shelf by whoever is holding it, so there is nothing to declare.
			$body.find('.ip-loc-def').on('click', (e) => {
				const $btn = $(e.currentTarget);
				const dir = $btn.data('dir');
				const item = $btn.closest('tr').data('item');
				const on = $btn.hasClass('on') ? 0 : 1;
				this.api('set_item_default_location', {
					item_code: item, warehouse: contents.location.warehouse,
					location: name, direction: dir, on: on,
				}).then(() => {
					// the role belongs to one location at a time, so re-read rather than guess
					this.api('get_location_contents', { location: name }).then((r) => {
						if (!r) return;
						const keep = collect();
						contents = r;
						render();
						keep.forEach((c) => $body.find(`tr[data-item="${c.item_code}"] .ip-loc-qty`).val(c.qty));
					});
					frappe.show_alert({
						message: on ? __('Picked from here first') : __('Pick location cleared'),
						indicator: 'blue',
					});
				});
			});
		};

		const collect = () => $body.find('tbody tr').map((_i, tr) => {
			const $tr = $(tr);
			const was = flt($tr.find('.ip-loc-qty').data('was'));
			const now = flt($tr.find('.ip-loc-qty').val());
			return Math.abs(now - was) < 0.000001
				? null
				: { item_code: $tr.data('item'), qty: now };
		}).get().filter(Boolean);

		const apply = () => {
			const changes = collect();
			const desc = $body.find('.ip-loc-desc').val();
			const active = $body.find('.ip-loc-active').is(':checked') ? 1 : 0;

			// filing a location under a zone is not a stock movement, so it rides along
			// with the other settings rather than being its own gesture
			const zone = $body.find('.ip-loc-zone').val() || '';
			const was_zone = (contents.location && contents.location.zone) || '';
			const save_settings = () => this.api('update_location', {
				name, description: desc, is_active: active,
			}).then(() => (zone === was_zone
				? null
				: this.api('set_location_zone', { locations: JSON.stringify([name]), zone: zone })
					.then((r) => {
						((r && r.problems) || []).forEach((msg) =>
							frappe.msgprint({ message: msg, indicator: 'orange' }));
					})));

			if (!changes.length) {
				save_settings().then(() => {
					d.hide();
					frappe.show_alert({ message: __('Saved'), indicator: 'green' });
					this.show('warehouse');
				});
				return;
			}

			this.api('apply_location_contents', { location: name, rows: JSON.stringify(changes) })
				.then((r) => {
					if (!r) return;
					(r.problems || []).forEach((p) => frappe.msgprint({
						title: __('{0} could not be changed', [p.item_code]),
						message: p.message, indicator: 'orange',
					}));
					const moved = (r.applied || []).length;
					if (moved) {
						frappe.show_alert({
							message: __('{0} item(s) re-shelved', [moved]), indicator: 'green',
						});
					}
					return save_settings();
				})
				.then(() => { d.hide(); this.show('warehouse'); });
		};

		this.api('get_location_contents', { location: name }).then((r) => {
			if (!r) return;
			contents = r;
			// the zones offered are the ones in this location's own warehouse
			return this.api('get_zones', { warehouse: r.location && r.location.warehouse, with_counts: 0 })
				// a missing or odd reply must not blank the editor — the zone picker is the
				// least important thing in it
				.then((zs) => { zone_options = Array.isArray(zs) ? zs : []; render(); });
		});
		d.show();
	}

	// ---- CSV helpers (client-side) ----
	_download_csv(filename, headers, sample) {
		const enc = (v) => (/[",\n]/.test(v) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v));
		const lines = [headers.join(',')];
		if (sample) lines.push(sample.map(enc).join(','));
		const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
		URL.revokeObjectURL(url);
	}

	_parse_csv(text) {
		text = (text || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
		const rows = []; let field = '', row = [], inq = false;
		for (let i = 0; i < text.length; i++) {
			const c = text[i];
			if (inq) {
				if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inq = false; }
				else field += c;
			} else if (c === '"') inq = true;
			else if (c === ',') { row.push(field); field = ''; }
			else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
			else field += c;
		}
		if (field.length || row.length) { row.push(field); rows.push(row); }
		const header = (rows.shift() || []).map((h) => h.trim().toLowerCase().replace(/\s+/g, '_'));
		return rows.filter((r) => r.some((c) => (c || '').trim() !== '')).map((r) => {
			const o = {}; header.forEach((h, i) => (o[h] = (r[i] || '').trim())); return o;
		});
	}

	_read_file(input) {
		return new Promise((res, rej) => {
			const f = input && input.files && input.files[0];
			if (!f) { res(null); return; }
			const fr = new FileReader();
			fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsText(f);
		});
	}

	// ---- which locations are on screen, and in what shape ----
	// Zone grouping is the same in both views: it is how the warehouse is described,
	// not a property of one of them.
	filtered_locations() {
		const all = this.allSecs || [];
		if (!this.zoneFilter) return all;
		if (this.zoneFilter === '__none__') return all.filter((s) => !s.zone);
		return all.filter((s) => s.zone === this.zoneFilter);
	}

	// Locations grouped into zones, in display order, with the unfiled ones last —
	// "not in a zone" is a real state to see, not an error to hide.
	group_by_zone(secs) {
		const groups = new Map();
		secs.forEach((s) => {
			const key = s.zone || '';
			if (!groups.has(key)) {
				groups.set(key, {
					zone: s.zone || '',
					label: s.zone ? (s.zone_name || s.zone_code || s.zone) : __('Not in a zone'),
					seq: s.zone ? (s.zone_seq || 0) : 1e9,
					warehouse: s.warehouse,
					locations: [],
				});
			}
			groups.get(key).locations.push(s);
		});
		return Array.from(groups.values()).sort((a, b) => a.seq - b.seq
			|| String(a.label).localeCompare(String(b.label)));
	}

	paint_locations($wrap) {
		const secs = this.filtered_locations();
		if (!secs.length) {
			$wrap.html(`<div class="ip-empty-lg"><i class="fa fa-filter"></i>
				<div>${frappe.utils.escape_html(__('No locations match this filter.'))}</div></div>`);
			return;
		}
		if (this.locView === 'layout') this.render_layout($wrap, secs);
		else this.render_kanban($wrap, secs);
	}

	// ------------------------------------------------------------------ LAYOUT VIEW
	// The map of the place: zones, the locations in them, and how full each one is.
	// No item lists — this is the view for organising the warehouse, and a wall of
	// stock detail is exactly what gets in the way of that.
	render_layout($wrap, secs) {
		const esc = frappe.utils.escape_html;
		const manage = this.ctx.can_manage;
		const groups = this.group_by_zone(secs);

		$wrap.html(`<div class="ip-layout">${groups.map((g) => {
			const units = g.locations.reduce((a, s) => a + flt(s.total_qty), 0);
			const empty = g.locations.filter((s) => !flt(s.total_qty)).length;
			return `
			<section class="ip-zone${g.zone ? '' : ' ip-zone-unfiled'}" data-zone="${esc(g.zone)}"
				data-wh="${esc(g.warehouse)}">
				<header class="ip-zone-head">
					<div class="ip-zone-title">${esc(g.label)}</div>
					<div class="ip-zone-meta">${esc(__('{0} location(s)', [g.locations.length]))} ·
						${format_number(units)} ${esc(__('units'))}${
						empty ? ' · ' + esc(__('{0} empty', [empty])) : ''}</div>
				</header>
				<div class="ip-zone-body">${g.locations.map((s) => {
					const fill = flt(s.max_qty) > 0
						? Math.min(100, Math.round((flt(s.total_qty) / flt(s.max_qty)) * 100))
						: null;
					return `
					<div class="ip-tile${flt(s.total_qty) ? '' : ' is-empty'}${manage ? ' ip-tile-move' : ''}"
						${manage ? 'draggable="true"' : ''}
						data-location="${esc(s.location)}" data-wh="${esc(s.warehouse)}">
						<div class="ip-tile-top">
							<span class="ip-tile-code">${esc(s.location_code || s.location)}</span>
							${manage ? `<button class="ip-tile-edit" data-sec="${esc(s.location)}"
								title="${esc(__('Edit this location'))}"><i class="fa fa-pencil"></i></button>` : ''}
						</div>
						${s.location_name && s.location_name !== s.location_code
							? `<div class="ip-tile-name">${esc(s.location_name)}</div>` : ''}
						<div class="ip-tile-stats">
							<span class="ip-tile-qty">${format_number(s.total_qty)}</span>
							<span class="ip-tile-items">${esc(__('{0} item(s)', [s.item_count]))}</span>
						</div>
						${fill === null ? '' : `<div class="ip-tile-bar" title="${esc(
							__('{0} of {1}', [format_number(s.total_qty), format_number(s.max_qty)]))}">
							<span style="width:${fill}%" class="${fill >= 100 ? 'over' : ''}"></span></div>`}
						${s.location_type ? `<div class="ip-tile-type">${esc(s.location_type)}</div>` : ''}
					</div>`; }).join('')}</div>
			</section>`; }).join('')}</div>`);

		$wrap.find('.ip-tile-edit').on('click', (e) => {
			e.stopPropagation();
			const name = $(e.currentTarget).data('sec');
			this.location_edit_dialog((this.allSecs || []).find((x) => x.location === name));
		});
		if (manage) {
			this.bind_zone_dnd($wrap);
			this.bind_tile_drops($wrap);
		}
	}

	// Dragging a location tile onto another zone re-files it. Filing is not a stock
	// movement — the goods do not move, only the way the warehouse is described.
	// Layout view carries two different drags, and they must not be confused:
	//   a location tile onto a zone   — re-file the location (bind_zone_dnd)
	//   an item card onto a tile      — put that stock away there (this)
	// The first is a local `dragging`; the second is `this._drag`, set by the shared
	// drag source, which is what the unassigned dock hands over. Checking the right one
	// is the whole difference between the two gestures.
	bind_tile_drops($wrap) {
		const droppable = ($tile) =>
			this._drag
			&& $tile.data('wh') === this._drag.warehouse
			&& $tile.data('location') !== this._drag.from;

		$wrap.find('.ip-tile').on('dragover', (e) => {
			const $tile = $(e.currentTarget);
			if (!droppable($tile)) return;
			e.preventDefault();
			e.stopPropagation();          // the zone underneath must not claim it too
			$tile.addClass('is-drop-target');
		});
		$wrap.find('.ip-tile').on('dragleave', (e) => $(e.currentTarget).removeClass('is-drop-target'));
		$wrap.find('.ip-tile').on('drop', (e) => {
			const $tile = $(e.currentTarget);
			$tile.removeClass('is-drop-target');
			if (!droppable($tile)) return;
			e.preventDefault();
			e.stopPropagation();
			this.ask_move(this._drag, $tile.data('location'));
			this._drag = null;
			$('.ip-col, .ip-tile').removeClass('is-drop-target can-drop');
		});
	}

	bind_zone_dnd($wrap) {
		let dragging = null;
		$wrap.find('.ip-tile-move').on('dragstart', (e) => {
			dragging = {
				location: $(e.currentTarget).data('location'),
				warehouse: $(e.currentTarget).data('wh'),
			};
			$(e.currentTarget).addClass('is-dragging');
			(e.originalEvent.dataTransfer || {}).effectAllowed = 'move';
			try { e.originalEvent.dataTransfer.setData('text/plain', dragging.location); } catch (err) { /* Safari */ }
			$wrap.find('.ip-zone').each(function () {
				if ($(this).data('wh') === dragging.warehouse) $(this).addClass('can-drop');
			});
		});
		$wrap.find('.ip-tile-move').on('dragend', (e) => {
			$(e.currentTarget).removeClass('is-dragging');
			$wrap.find('.ip-zone').removeClass('can-drop is-drop-target');
		});
		$wrap.find('.ip-zone').on('dragover', (e) => {
			if (!dragging || $(e.currentTarget).data('wh') !== dragging.warehouse) return;
			if (this._drag) return;      // an item card is being carried, not a location
			e.preventDefault();
			$(e.currentTarget).addClass('is-drop-target');
		});
		$wrap.find('.ip-zone').on('dragleave', (e) => $(e.currentTarget).removeClass('is-drop-target'));
		$wrap.find('.ip-zone').on('drop', (e) => {
			e.preventDefault();
			const $zone = $(e.currentTarget);
			$wrap.find('.ip-zone').removeClass('can-drop is-drop-target');
			if (!dragging) return;
			const target = $zone.data('zone') || '';
			const moved = dragging; dragging = null;
			const sec = (this.allSecs || []).find((x) => x.location === moved.location);
			if (sec && (sec.zone || '') === target) return;
			this.api('set_location_zone', { locations: JSON.stringify([moved.location]), zone: target })
				.then((r) => {
					if (!r) return;
					(r.problems || []).forEach((p) => frappe.msgprint({ message: p, indicator: 'orange' }));
					if (r.moved) {
						frappe.show_alert({
							message: target
								? __('{0} filed under {1}', [moved.location, $zone.find('.ip-zone-title').text()])
								: __('{0} taken out of its zone', [moved.location]),
							indicator: 'blue',
						});
					}
					this.render_warehouse();
				});
		});
	}

	// ------------------------------------------------------------------ ZONE MANAGER
	zones_dialog() {
		const esc = frappe.utils.escape_html;
		const d = new frappe.ui.Dialog({
			title: __('Zones'),
			size: 'large',
			fields: [{ fieldtype: 'HTML', fieldname: 'body' }],
		});
		const $body = d.get_field('body').$wrapper;
		const warehouses = Object.keys(this.wmap || {}).filter((w) => !(this.wmap[w] || {}).is_group);
		let zones = [];

		const render = () => {
			$body.html(`
				<div class="ip-zone-note">${esc(__(
					'A zone groups the locations of one warehouse — an aisle, a cold room, a returns corner. It changes how the warehouse reads, never where stock is picked from.'))}</div>
				<table class="ip-table ip-zone-table">
					<thead><tr>
						<th style="width:110px">${esc(__('Code'))}</th>
						<th>${esc(__('Name'))}</th>
						<th style="width:180px">${esc(__('Warehouse'))}</th>
						<th style="width:80px">${esc(__('Order'))}</th>
						<th style="width:96px">${esc(__('Locations'))}</th>
						<th style="width:40px"></th>
					</tr></thead>
					<tbody>${zones.length ? zones.map((z) => `
						<tr data-name="${esc(z.name)}">
							<td><b>${esc(z.zone_code)}</b></td>
							<td><input class="ip-input ip-z-name" value="${esc(z.zone_name || '')}"></td>
							<td class="ip-muted">${esc(z.warehouse)}</td>
							<td><input type="number" class="ip-input ip-z-seq" value="${cint(z.sequence)}"></td>
							<td class="ip-muted">${esc(__('{0} filed', [cint(z.location_count)]))}</td>
							<td><button class="ip-z-del" title="${esc(__('Delete'))}">&times;</button></td>
						</tr>`).join('') : `<tr><td colspan="6" class="ip-muted" style="padding:14px">${
							esc(__('No zones yet. Add the first one below.'))}</td></tr>`}</tbody>
				</table>
				<div class="ip-zone-new">
					<input class="ip-input ip-z-code" placeholder="${esc(__('Code e.g. FRONT'))}" style="width:130px">
					<input class="ip-input ip-z-label" placeholder="${esc(__('Name e.g. Front Aisle'))}">
					<select class="ip-input ip-z-wh">${warehouses.map((w) =>
						`<option value="${esc(w)}"${w === this.scope ? ' selected' : ''}>${esc(w)}</option>`).join('')}</select>
					<button class="ip-btn ip-btn-primary ip-z-add"><i class="fa fa-plus"></i> ${esc(__('Add zone'))}</button>
				</div>`);

			$body.find('.ip-z-add').on('click', () => {
				const code = ($body.find('.ip-z-code').val() || '').trim();
				if (!code) { frappe.msgprint(__('Give the zone a code.')); return; }
				this.api('save_zone', {
					warehouse: $body.find('.ip-z-wh').val(),
					zone_code: code,
					zone_name: $body.find('.ip-z-label').val() || '',
				}).then((r) => { if (r) load(); });
			});

			$body.find('.ip-z-name, .ip-z-seq').on('change', (e) => {
				const $tr = $(e.currentTarget).closest('tr');
				const z = zones.find((x) => x.name === $tr.data('name'));
				if (!z) return;
				this.api('save_zone', {
					name: z.name, warehouse: z.warehouse, zone_code: z.zone_code,
					zone_name: $tr.find('.ip-z-name').val(),
					sequence: cint($tr.find('.ip-z-seq').val()),
				}).then(() => frappe.show_alert({ message: __('Saved'), indicator: 'green' }));
			});

			$body.find('.ip-z-del').on('click', (e) => {
				const $tr = $(e.currentTarget).closest('tr');
				const z = zones.find((x) => x.name === $tr.data('name'));
				if (!z) return;
				frappe.confirm(
					cint(z.location_count)
						? __('Delete zone {0}? Its {1} location(s) stay exactly as they are — they just stop being filed under it.',
							[z.zone_name || z.zone_code, cint(z.location_count)])
						: __('Delete zone {0}?', [z.zone_name || z.zone_code]),
					() => this.api('delete_zone', { name: z.name }).then(() => load())
				);
			});
		};

		const load = () => this.api('get_zones', { warehouse: this.scope }).then((r) => {
			zones = r || [];
			render();
			this.zones = zones;
		});

		load();
		d.onhide = () => this.render_warehouse();
		d.show();
	}

	render_kanban($wrap, secs) {
		const esc = frappe.utils.escape_html;
		const movable = this.ctx.is_preparer;
		// A warehouse that has never defined a zone should not suddenly grow a header
		// saying so, so the grouping only appears once there is something to group by.
		const zoned = (this.zones || []).length > 0;
		const column = (s, i) => {
			const count = s.item_count != null ? s.item_count : s.items.length;
			const hidden = count - (s.listed != null ? s.listed : s.items.length);
			return `
			<div class="ip-col ip-fade${s.is_unassigned ? ' ip-col-unassigned' : ''}"
				style="--i:${i}" data-location="${esc(s.location)}" data-wh="${esc(s.warehouse)}">
				<div class="ip-col-head">
					<div class="ip-col-title">${esc(s.is_unassigned ? __('Unassigned Stock') : (s.location_code || s.location))}</div>
					<div class="ip-col-tools">
						<span class="ip-col-count">${count}</span>
						${this.ctx.can_manage
							? `<button class="ip-col-edit" data-sec="${esc(s.location)}" title="${esc(__('Edit this location'))}"><i class="fa fa-pencil"></i></button>`
							: ''}
					</div>
				</div>
				<div class="ip-col-sub">${esc(s.warehouse)} · ${format_number(s.total_qty)} units${
					s.is_unassigned ? ' · <span class="ip-col-tag">' + esc(__('not put away yet')) + '</span>' : ''}</div>
				<div class="ip-col-body">
					${s.items.length ? s.items.map((it) => `
						<div class="ip-cardlet${movable ? ' ip-draggable' : ''}"
							${movable ? 'draggable="true"' : ''}
							data-item="${esc(it.item_code)}" data-qty="${flt(it.qty)}">
							<div class="ip-cardlet-main">
								<div class="ip-cardlet-code">${esc(it.item_code)}</div>
								<div class="ip-cardlet-name">${esc(it.item_name || '')}</div>
							</div>
							<div class="ip-cardlet-qty${movable && !s.is_unassigned ? ' ip-editable' : ''}"
								title="${movable && !s.is_unassigned ? esc(__('Click to set what this shelf holds')) : ''}"
								>${format_number(it.qty)}</div>
						</div>`).join('') : `<div class="ip-col-empty">${esc(s.is_unassigned ? __('Everything here is put away') : __('Empty'))}</div>`}
					${hidden > 0 ? `<div class="ip-col-more">${esc(__('+ {0} more item(s) — search to narrow', [hidden]))}</div>` : ''}
				</div>
			</div>`; };

		if (!zoned) {
			$wrap.html(`<div class="ip-kanban">${secs.map(column).join('')}</div>`);
		} else {
			const groups = this.group_by_zone(secs);
			$wrap.html(`<div class="ip-zoned">${groups.map((g) => `
				<section class="ip-zonerow${g.zone ? '' : ' ip-zone-unfiled'}">
					<header class="ip-zonerow-head">
						<span class="ip-zonerow-title">${esc(g.label)}</span>
						<span class="ip-zonerow-meta">${esc(__('{0} location(s)', [g.locations.length]))}</span>
					</header>
					<div class="ip-kanban">${g.locations.map(column).join('')}</div>
				</section>`).join('')}</div>`);
		}

		$wrap.find('.ip-col-edit').on('click', (e) => {
			e.stopPropagation();
			const name = $(e.currentTarget).data('sec');
			this.location_edit_dialog(secs.find((x) => x.location === name));
		});
		if (movable) this.bind_board($wrap);
	}

	// ------------------------------------------------------------------
	// The board: drag a card to another shelf, or click a quantity to set it.
	// ------------------------------------------------------------------
	// Both are the same thing underneath — a re-shelving inside one warehouse. Nothing
	// leaves, nothing arrives, so there is no Stock Entry and no accounting: what a
	// shelf holds changes, and the difference is unassigned stock.
	// Both the board and the unassigned dock hand cards to the same gesture, so the drag
	// state lives on the app rather than inside either binder.
	bind_drag_source($scope, get_context) {
		$scope.find('.ip-draggable').on('dragstart', (e) => {
			const $card = $(e.currentTarget);
			this._drag = get_context($card);
			$card.addClass('is-dragging');
			(e.originalEvent.dataTransfer || {}).effectAllowed = 'move';
			try { e.originalEvent.dataTransfer.setData('text/plain', this._drag.item); } catch (err) { /* Safari */ }
			// light up everywhere it can land, rather than waiting to be hovered — a card
			// dragged out of the unassigned bar should not have to be guessed at
			const d = this._drag;
			// both views can receive it: a column in Contents, a location tile in Layout
			$('.ip-col, .ip-tile').each(function () {
				const $c = $(this);
				if ($c.data('wh') === d.warehouse && $c.data('location') !== d.from) {
					$c.addClass('can-drop');
				}
			});
		});
		$scope.find('.ip-draggable').on('dragend', (e) => {
			$(e.currentTarget).removeClass('is-dragging');
			$('.ip-col, .ip-tile').removeClass('is-drop-target can-drop');
		});
	}

	bind_board($wrap) {
		this.bind_drag_source($wrap, ($card) => {
			const $col = $card.closest('.ip-col');
			return {
				item: $card.data('item'),
				qty: flt($card.data('qty')),
				from: $col.data('location'),
				warehouse: $col.data('wh'),
			};
		});

		const droppable = (dragged, $col) =>
			dragged &&
			$col.data('wh') === dragged.warehouse &&
			$col.data('location') !== dragged.from;

		$wrap.find('.ip-col').on('dragover', (e) => {
			const $col = $(e.currentTarget);
			if (!droppable(this._drag, $col)) return;
			e.preventDefault();
			$col.addClass('is-drop-target');
		});
		// dragging within the board should also tuck the dock out of the way
		$wrap.find('.ip-draggable')
			.on('dragstart', () => this.$dock && this.$dock.addClass('is-tucked'))
			.on('dragend', () => this.$dock && this.$dock.removeClass('is-tucked'));
		$wrap.find('.ip-col').on('dragleave', (e) => $(e.currentTarget).removeClass('is-drop-target'));

		$wrap.find('.ip-col').on('drop', (e) => {
			e.preventDefault();
			const $col = $(e.currentTarget);
			$col.removeClass('is-drop-target');
			if (!droppable(this._drag, $col)) return;
			this.ask_move(this._drag, $col.data('location'));
			this._drag = null;
			$('.ip-col').removeClass('is-drop-target can-drop');
		});

		$wrap.find('.ip-cardlet-qty.ip-editable').on('click', (e) => {
			e.stopPropagation();
			const $qty = $(e.currentTarget);
			const $card = $qty.closest('.ip-cardlet');
			const $col = $card.closest('.ip-col');
			this.edit_section_qty({
				warehouse: $col.data('wh'),
				location: $col.data('location'),
				item: $card.data('item'),
				qty: flt($card.data('qty')),
			});
		});
	}

	// ------------------------------------------------------------------
	// The unassigned dock
	// ------------------------------------------------------------------
	// Everything the warehouse holds that is not yet on a shelf. It is derived, not
	// stored, so it is always right — and it is usually the largest thing in the
	// warehouse, so it gets a permanent handle pinned to the bottom of the screen
	// rather than a capped column.
	//
	// Three things make it feel right: it is fixed to the viewport (not parked at the
	// end of a long board), it animates on a measured height so open and close take the
	// same path, and it tucks itself away the moment you drag a card out — otherwise it
	// would be covering the shelves you are aiming for.
	render_unassigned_dock() {
		$('.ip-dock').remove();
		const esc = frappe.utils.escape_html;
		const open = localStorage.getItem('ip_dock_open') === '1';

		// Deliberately no backdrop: the board behind the dock is where cards are dropped,
		// so dimming it — let alone blocking it — would fight the whole point.
		const $dock = $(`
			<div class="ip-dock${open ? ' is-open' : ''}" role="region"
				aria-label="${esc(__('Unassigned stock'))}">
				<button class="ip-dock-handle" type="button" aria-expanded="${open}">
					<span class="ip-dock-grip" aria-hidden="true"></span>
					<span class="ip-dock-label">
						<span class="ip-dock-title">${esc(__('Unassigned Stock'))}</span>
						<span class="ip-dock-scope"></span>
					</span>
					<span class="ip-dock-count"><span class="ip-dock-items">—</span></span>
					<span class="ip-dock-hint">
						<span class="when-shut">${esc(__('not on a shelf yet — click to open'))}</span>
						<span class="when-open">${esc(__('press Esc to close'))}</span>
					</span>
					<span class="ip-dock-chev" aria-hidden="true"><i class="fa fa-chevron-up"></i></span>
				</button>
				<div class="ip-dock-panel">
					<div class="ip-dock-inner">
						<div class="ip-dock-tools">
							<div class="ip-search ip-dock-searchbox"><i class="fa fa-search"></i>
								<input class="ip-input ip-dock-search" placeholder="${esc(__('Search item…'))}"></div>
							<div class="ip-dock-tip"><i class="fa fa-hand-rock-o"></i>
								${esc(__('Drag an item onto a location to put it away'))}</div>
							<button class="ip-dock-close" type="button" title="${esc(__('Close'))}">&times;</button>
						</div>
						<div class="ip-dock-scroll"><div class="ip-loading"><div class="ip-spin"></div></div></div>
					</div>
				</div>
			</div>`).appendTo(document.body);

		this.$dock = $dock;
		$('body').addClass('ip-has-dock');
		const $scroll = $dock.find('.ip-dock-scroll');
		this.dock = { start: 0, search: '', rows: [], open: open };

		// --- keep it aligned to the page, not to the window ---
		const place = () => {
			const el = this.$body && this.$body[0];
			if (!el) return;
			const r = el.getBoundingClientRect();
			$dock.css({ left: Math.round(r.left) + 'px', width: Math.round(r.width) + 'px' });
		};
		place();
		$(window).off('resize.ipdock').on('resize.ipdock', frappe.utils.debounce(place, 120));

		// --- height is measured, so opening and closing follow the same curve ---
		const measure = () => {
			const inner = $dock.find('.ip-dock-inner')[0];
			if (!inner) return 0;
			const max = Math.round(window.innerHeight * 0.52);
			return Math.min(inner.scrollHeight, max);
		};
		const sync_height = () => {
			$dock[0].style.setProperty(
				'--ip-dock-h', ($dock.hasClass('is-open') ? measure() : 0) + 'px'
			);
		};
		this._dock_sync = sync_height;

		const set_open = (want) => {
			$dock.toggleClass('is-open', want);
			$dock.find('.ip-dock-handle').attr('aria-expanded', want);
			localStorage.setItem('ip_dock_open', want ? '1' : '0');
			this.dock.open = want;
			if (want && !this.dock.rows.length) load();
			else sync_height();
			if (want) setTimeout(() => $dock.find('.ip-dock-search').focus(), 260);
		};

		const render_rows = () => {
			const single_wh = !!this.leaf_scope();
			const cards = this.dock.rows.map((it, i) => `
				<div class="ip-dock-card ip-draggable" draggable="true" style="--i:${Math.min(i, 7)}"
					data-item="${esc(it.item_code)}" data-qty="${flt(it.qty)}" data-wh="${esc(it.warehouse)}">
					<div class="ip-dock-card-main">
						<div class="ip-dock-card-code">${esc(it.item_code)}</div>
						<div class="ip-dock-card-name">${esc(it.item_name || '')}</div>
						${single_wh ? '' : `<div class="ip-dock-card-wh">${esc(it.warehouse)}</div>`}
					</div>
					<div class="ip-dock-card-side">
						<div class="ip-dock-card-qty">${format_number(it.qty)}<span>${esc(it.stock_uom || '')}</span></div>
						<button class="ip-dock-put" type="button">${esc(__('Put away'))}</button>
					</div>
				</div>`).join('');

			$scroll.html(cards
				? `<div class="ip-dock-cards">${cards}</div>${this.dock.has_more
					? `<button class="ip-dock-more" type="button">${esc(__('Load more'))}</button>` : ''}`
				: `<div class="ip-dock-empty"><i class="fa fa-check-circle"></i>
					<div>${esc(this.dock.search
						? __('Nothing loose matches “{0}”.', [this.dock.search])
						: __('Everything here is on a shelf.'))}</div></div>`);

			this.bind_drag_source($scroll, ($card) => ({
				item: $card.data('item'),
				qty: flt($card.data('qty')),
				from: null,                       // out of unassigned: a put-away, not a transfer
				warehouse: $card.data('wh'),
			}));
			// Get out of the way of the locations the card is being aimed at — but not
			// until the next tick.
			//
			// The card being dragged lives inside this dock, and tucking it applies a
			// transform that shifts the card most of the way off screen. Doing that
			// synchronously inside `dragstart` moves the drag source out from under the
			// pointer before the browser has taken its drag image, and Chrome responds by
			// abandoning the drag: no dragover, no drop, nothing. Dragging between two
			// locations was unaffected precisely because those cards are not in the dock.
			$scroll.find('.ip-draggable')
				.on('dragstart', () => setTimeout(() => $dock.addClass('is-tucked'), 0))
				.on('dragend', () => $dock.removeClass('is-tucked'));

			$scroll.find('.ip-dock-put').on('click', (e) => {
				e.stopPropagation();
				const $card = $(e.currentTarget).closest('.ip-dock-card');
				this.ask_putaway({
					item: $card.data('item'),
					qty: flt($card.data('qty')),
					warehouse: $card.data('wh'),
				});
			});
			$scroll.find('.ip-dock-more').on('click', () => load(true));
			sync_height();
		};

		const load = (append) => {
			if (!append) { this.dock.start = 0; this.dock.rows = []; }
			// a shut bar shows a count and a total — fetching forty rows with their
			// names to render one number is most of what made this feel slow
			const shut = !$dock.hasClass('is-open');
			return this.api('get_unassigned', {
				warehouse: this.scope,
				search: this.dock.search,
				start: this.dock.start,
				limit: 40,
				counts_only: shut ? 1 : 0,
			}).then((r) => {
				if (!r) return;
				if (!r.counts_only) {
					this.dock.rows = append ? this.dock.rows.concat(r.items || []) : (r.items || []);
					this.dock.start = this.dock.rows.length;
					this.dock.has_more = r.has_more;
				}
				$dock.find('.ip-dock-items').text(
					__('{0} items · {1} units', [r.total_items, format_number(r.total_qty)])
				);
				$dock.toggleClass('is-empty', !r.total_items);
				$dock.find('.ip-dock-scope').text(this.scope || __('All warehouses'));
				if (this.dock.open) render_rows(); else sync_height();
			});
		};

		$dock.find('.ip-dock-handle').on('click', () => set_open(!$dock.hasClass('is-open')));
		$dock.find('.ip-dock-close').on('click', (e) => { e.stopPropagation(); set_open(false); });
		$(document).off('keydown.ipdock').on('keydown.ipdock', (e) => {
			if (e.key === 'Escape' && $dock.hasClass('is-open')) set_open(false);
		});

		let t;
		$dock.find('.ip-dock-search').on('input', (e) => {
			this.dock.search = e.target.value;
			clearTimeout(t);
			t = setTimeout(() => load(), 250);
		});
		$dock.find('.ip-dock-search').on('click', (e) => e.stopPropagation());

		// the count is worth showing even while the panel is shut; rows come with it only
		// when it is already open, so opening it never fetches twice
		load();
	}

	teardown_dock() {
		$('.ip-dock').remove();
		$(window).off('resize.ipdock');
		$(document).off('keydown.ipdock');
		$('body').removeClass('ip-has-dock');
		this.$dock = null;
	}

	ask_putaway(ctx) {
		const esc = frappe.utils.escape_html;
		const d = new frappe.ui.Dialog({
			title: __('Put away {0}', [ctx.item]),
			fields: [
				{
					fieldtype: 'HTML', fieldname: 'note',
					options: `<div class="ip-move-note">${esc(__(
						'{0} loose in {1}. Putting it on a shelf is re-shelving — no stock entry, no accounting.',
						[format_number(ctx.qty), ctx.warehouse]))}</div>`,
				},
				{
					fieldtype: 'Link', fieldname: 'location', label: __('Location'),
					options: 'Warehouse Location', reqd: 1,
					get_query: () => ({
						filters: { warehouse: ctx.warehouse, is_active: 1, is_unassigned: 0 },
					}),
				},
				{ fieldtype: 'Float', fieldname: 'qty', label: __('Quantity'), default: ctx.qty, reqd: 1 },
			],
			primary_action_label: __('Put away'),
			primary_action: (values) => {
				const qty = flt(values.qty);
				if (qty <= 0 || qty > ctx.qty + 0.000001) {
					frappe.msgprint(__('Enter between 0 and {0}.', [format_number(ctx.qty)]));
					return;
				}
				d.hide();
				this.api('move_between_locations', {
					warehouse: ctx.warehouse,
					item_code: ctx.item,
					from_location: null,
					to_location: values.location,
					qty: qty,
				}).then((r) => {
					if (!r) return;
					frappe.show_alert({
						message: __('Put {0} away in {1}', [format_number(qty), values.location]),
						indicator: 'green',
					});
					this.show('warehouse');
				});
			},
		});
		d.show();
	}

	ask_move(dragged, to_location) {
		const from_label = dragged.from || __('Unassigned');
		const d = new frappe.ui.Dialog({
			title: dragged.from ? __('Move {0}', [dragged.item]) : __('Put away {0}', [dragged.item]),
			fields: [
				{
					fieldtype: 'HTML', fieldname: 'note',
					options: `<div class="ip-move-note">${frappe.utils.escape_html(
						__('{0} → {1}. Re-shelving inside one warehouse: no stock entry, no accounting.',
							[from_label, to_location]))}</div>`,
				},
				{
					fieldtype: 'Float', fieldname: 'qty', label: __('Quantity'),
					default: dragged.qty, reqd: 1,
					description: __('{0} on that shelf', [format_number(dragged.qty)]),
				},
			],
			primary_action_label: __('Move'),
			primary_action: (values) => {
				const qty = flt(values.qty);
				if (qty <= 0 || qty > dragged.qty + 0.000001) {
					frappe.msgprint(__('Enter between 0 and {0}.', [format_number(dragged.qty)]));
					return;
				}
				d.hide();
				this.api('move_between_locations', {
					warehouse: dragged.warehouse,
					item_code: dragged.item,
					from_location: dragged.from || null,
					to_location: to_location,
					qty: qty,
				}).then((r) => {
					if (!r) return;
					frappe.show_alert({
						message: dragged.from
							? __('Moved {0} to {1}', [format_number(qty), to_location])
							: __('Put {0} away in {1}', [format_number(qty), to_location]),
						indicator: 'green',
					});
					this.show('warehouse');
				});
			},
		});
		d.show();
	}

	edit_section_qty(ctx) {
		const d = new frappe.ui.Dialog({
			title: __('{0} on {1}', [ctx.item, ctx.location]),
			fields: [
				{
					fieldtype: 'Float', fieldname: 'qty', label: __('This shelf holds'),
					default: ctx.qty, reqd: 1,
				},
				{
					fieldtype: 'HTML', fieldname: 'note',
					options: `<div class="ip-move-note">${frappe.utils.escape_html(
						__('Lower it and the difference goes back to unassigned stock. Raise it and the ' +
							'difference is taken from unassigned — so a shelf can never claim more than the ' +
							'warehouse actually holds.'))}</div>`,
				},
			],
			primary_action_label: __('Set'),
			primary_action: (values) => {
				d.hide();
				this.api('set_location_qty', {
					warehouse: ctx.warehouse,
					item_code: ctx.item,
					location: ctx.location,
					qty: flt(values.qty),
				}).then((r) => {
					if (!r) return;
					const moved = flt(r.changed);
					frappe.show_alert({
						message: moved === 0
							? __('Unchanged')
							: (moved > 0
								? __('Took {0} from unassigned', [format_number(moved)])
								: __('Returned {0} to unassigned', [format_number(-moved)])),
						indicator: moved === 0 ? 'blue' : 'green',
					});
					this.show('warehouse');
				});
			},
		});
		d.show();
	}

	// ------------------------------------------------------------------ LOGS
	// ------------------------------------------------------------------ LEDGER
	// Every movement that touched a location, by warehouse, location and item. A
	// document line becomes one ledger line per end it names, so a transfer reads as an
	// out on the shelf it left and an in on the shelf it reached.
	render_ledger() {
		const esc = frappe.utils.escape_html;
		this.ledger = this.ledger || { location: '', item: '', start: 0, rows: [] };

		this.$content.html(`
			<div class="ip-toolbar">
				<select class="ip-input ip-led-loc" style="min-width:220px">
					<option value="">${esc(__('All locations'))}</option>
				</select>
				<div class="ip-search"><i class="fa fa-search"></i>
					<input class="ip-input ip-led-item" placeholder="${esc(__('Item code…'))}"
						value="${esc(this.ledger.item || '')}"></div>
				<div class="ip-led-note ip-muted"></div>
			</div>
			<div class="ip-card ip-fade" style="--i:0"><div class="ip-ledwrap">
				<div class="ip-loading"><div class="ip-spin"></div></div></div></div>`);

		const $wrap = this.$content.find('.ip-ledwrap');
		const $sel = this.$content.find('.ip-led-loc');

		this.api('get_ledger_locations', { warehouse: this.scope }).then((locs) => {
			(locs || []).forEach((l) => {
				const label = l.is_unassigned
					? __('Unassigned Stock') + ' — ' + l.warehouse
					: (l.location_code + (l.location_name && l.location_name !== l.location_code
						? ' · ' + l.location_name : ''));
				$sel.append(`<option value="${esc(l.name)}"${l.name === this.ledger.location ? ' selected' : ''}>${esc(label)}</option>`);
			});
		});

		const render = () => {
			const focused = !!this.ledger.location;
			if (!this.ledger.rows.length) {
				$wrap.html(`<div class="ip-empty-lg"><i class="fa fa-list"></i>
					<div>${esc(__('Nothing has moved here yet.'))}</div></div>`);
				return;
			}
			$wrap.html(`
				<table class="ip-table ip-ledger">
					<thead><tr>
						<th>${esc(__('When'))}</th>
						<th>${esc(__('Item'))}</th>
						${focused ? `<th class="ip-num">${esc(__('In'))}</th><th class="ip-num">${esc(__('Out'))}</th>`
							: `<th class="ip-num">${esc(__('Qty'))}</th>`}
						<th>${esc(__('From'))}</th><th>${esc(__('To'))}</th>
						<th>${esc(__('Because of'))}</th>
					</tr></thead>
					<tbody>${this.ledger.rows.map((r) => {
						const loc = (name, loose) => name
							? `<span class="ip-led-loc-cell${loose ? ' is-loose' : ''}">${esc(loose ? __('Unassigned') : name)}</span>`
							: '<span class="ip-muted">—</span>';
						return `<tr>
							<td class="ip-led-when">${esc(frappe.datetime.str_to_user(r.posting_date))}
								<span>${esc(r.posting_time || '')}</span></td>
							<td><div class="ip-ti-code">${esc(r.item_code)}</div>
								<div class="ip-ti-name">${esc(r.item_name || '')}</div></td>
							${focused
								? `<td class="ip-num ip-led-in">${r.direction === 'in' ? format_number(r.qty) : ''}</td>
								   <td class="ip-num ip-led-out">${r.direction === 'out' ? format_number(r.qty) : ''}</td>`
								: `<td class="ip-num">${format_number(r.qty)}</td>`}
							<td>${loc(r.source, r.source_loose)}</td>
							<td>${loc(r.target, r.target_loose)}</td>
							<td>${r.reference
								? `<span class="ip-led-ref" data-dt="${esc(r.reference.doctype)}" data-dn="${esc(r.reference.name)}">${esc(r.reference.name)}</span>
								   <div class="ip-muted" style="font-size:10.5px">${esc(r.reference.doctype)}</div>`
								: `<span class="ip-muted">${esc(r.entry_type)}</span>`}</td>
						</tr>`; }).join('')}</tbody>
				</table>
				${this.ledger.has_more ? `<button class="ip-btn ip-btn-light ip-led-more" style="margin:14px auto 0;display:block">${esc(__('Load more'))}</button>` : ''}`);

			$wrap.find('.ip-led-ref').on('click', (e) => {
				const $t = $(e.currentTarget);
				frappe.set_route('Form', $t.data('dt'), $t.data('dn'));
			});
			$wrap.find('.ip-led-more').on('click', () => load(true));
		};

		const load = (append) => {
			if (!append) { this.ledger.start = 0; this.ledger.rows = []; }
			this.api('get_ledger', {
				warehouse: this.scope,
				location: this.ledger.location || '',
				item_code: this.ledger.item || '',
				start: this.ledger.start,
				limit: 60,
			}).then((r) => {
				if (!r) return;
				this.ledger.rows = append ? this.ledger.rows.concat(r.rows || []) : (r.rows || []);
				this.ledger.start = this.ledger.rows.length;
				this.ledger.has_more = r.has_more;
				this.$content.find('.ip-led-note').text(
					this.ledger.location
						? __('In and Out are relative to {0}.', [this.ledger.location])
						: __('{0} movement line(s)', [this.ledger.rows.length + (r.has_more ? '+' : '')])
				);
				render();
			});
		};

		$sel.on('change', (e) => { this.ledger.location = e.target.value; load(); });
		let t;
		this.$content.find('.ip-led-item').on('input', (e) => {
			this.ledger.item = e.target.value.trim();
			clearTimeout(t); t = setTimeout(() => load(), 300);
		});
		load();
	}

	// ------------------------------------------------------------------ SETTINGS
	render_settings() {
		this.api('get_settings').then((s) => {
			const val_opts = ['Block', 'Warn', 'Off'].map((v) =>
				`<option value="${v}" ${v === s.stock_validation ? 'selected' : ''}>${v}</option>`).join('');
			this.$content.html(`
				<div class="ip-card ip-fade" style="--i:0"><div class="ip-card-head"><h3>General</h3></div>
					<div class="ip-form-grid">
						<label>Real-Stock Validation<select id="ip-validation" class="ip-input">${val_opts}</select></label>
						<label>Default Warehouse<select id="ip-warehouse" class="ip-input">${this.warehouse_options(s.default_warehouse, '— none —')}</select></label>
					</div>
					<div class="ip-muted" style="font-size:12px;margin-top:6px">${__('Light / dark mode follows your Frappe theme setting.')}</div></div>
				<div class="ip-card ip-fade" style="--i:1"><div class="ip-card-head"><h3>Enabled Warehouses</h3></div>
					<div class="ip-muted" style="font-size:12px;margin-bottom:8px">${__('Only these warehouses (and their children) are used by Isoft Location Manager. Leave empty to enable all.')}</div>
					<div class="ip-access-note">
						<b>${__('Who can use Isoft Location Manager')}</b> ${__('is the Location Manager role, assigned on the User like any other role. Everyone else keeps working normally: locations still appear on the documents they already use.')}<br>
						<b>${__('What they see')}</b> ${__('is their User Permissions for Warehouse, narrowed to the warehouses below. A user with no warehouse permission sees every enabled warehouse.')}
					</div>
					<div id="ip-enabled"></div></div>
				<div class="ip-save-bar"><button class="ip-btn ip-btn-primary" id="ip-save"><i class="fa fa-save"></i> Save Settings</button></div>`);
			this.enabled_ctrl = this._link_table('ip-enabled', s.enabled_warehouses, 'Warehouse', __('Select a warehouse'), { is_group: 0 });
			this.$content.find('#ip-save').on('click', () => this._save_settings());
		});
	}

	_link_table(mountId, values, doctype, placeholder, filters, addLabel) {
		const $mount = this.$content.find('#' + mountId);
		const $rows = $('<div class="ip-utable-rows"></div>').appendTo($mount);
		const rows = [];
		const addRow = (val) => {
			const $r = $(`<div class="ip-urow"><div class="c-user"></div>
				<button class="ip-row-del" title="${__('Remove')}"><i class="fa fa-times"></i></button></div>`).appendTo($rows);
			const ctrl = frappe.ui.form.make_control({
				parent: $r.find('.c-user')[0],
				df: { fieldtype: 'Link', fieldname: 'v', options: doctype, placeholder: placeholder,
					get_query: () => ({ filters: filters || {} }) },
				render_input: true,
			});
			if (val) ctrl.set_value(val);
			const rec = { $r, ctrl };
			rows.push(rec);
			$r.find('.ip-row-del').on('click', () => { rec.$r.remove(); const i = rows.indexOf(rec); if (i >= 0) rows.splice(i, 1); });
		};
		(values || []).forEach(addRow);
		$(`<button class="ip-btn ip-btn-light ip-uadd"><i class="fa fa-plus"></i> ${addLabel || __('Add')}</button>`)
			.appendTo($mount).on('click', () => addRow(''));
		return { get_values: () => [...new Set(rows.map((r) => r.ctrl.get_value()).filter(Boolean))] };
	}

	_save_settings() {
		this.api('save_settings', {
			stock_validation: this.$content.find('#ip-validation').val(),
			default_warehouse: this.$content.find('#ip-warehouse').val(),
			enabled_warehouses: JSON.stringify(this.enabled_ctrl.get_values() || []),
		}).then(() => {
			frappe.show_alert({ message: __('Settings saved'), indicator: 'green' });
		});
	}

	// ------------------------------------------------------------------ util
	status_pill(status) {
		const map = { Requested: 'blue', 'In Progress': 'amber', Prepared: 'green', Cancelled: 'grey' };
		return `<span class="ip-pill ${map[status] || 'grey'}">${status}</span>`;
	}

};
