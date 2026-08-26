// Navbar shortcut to the Isoft Location Manager dashboard.
// Rendered only for users who can access picking (role-gated server-side).
(function () {
	'use strict';

	// The desk route moved when the app was renamed. Anyone holding an old bookmark
	// lands on /app/isoft-picking and would otherwise see "not found".
	function followOldRoute() {
		const route = frappe.get_route && frappe.get_route();
		if (route && route[0] === 'isoft-picking') {
			frappe.set_route('isoft-location-manager');
		}
	}

	function initPickingIcon() {
		if (document.getElementById('iwlm-nav-navbar')) return;

		frappe.call({
			method: 'isoft_warehouse_location_management.isoft_location_manager.page.isoft_location_manager.isoft_location_manager.can_access_picking',
			callback: function (r) {
				if (!r || !r.message) return;
				if (document.getElementById('iwlm-nav-navbar')) return;

				const icon = `
					<li class='nav-item dropdown dropdown-notifications dropdown-mobile iwlm-nav-icon'
						title="Isoft Location Manager" aria-label="Isoft Location Manager">
						<a href="/app/isoft-location-manager" class="iwlm-nav-button" id="iwlm-nav-navbar"
							target="_blank" rel="noopener"
							onclick="window.open('/app/isoft-location-manager', '_blank'); return false;">
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
								stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<circle cx="6" cy="4.5" r="2.3"></circle>
								<path d="M6 6.8 V13"></path>
								<path d="M6 13 L4.2 18.5 M6 13 L7.8 18.5"></path>
								<path d="M6 8.4 L10.5 9.2 M6 10.6 L10.5 13.4"></path>
								<rect x="10.5" y="8.5" width="7" height="6.6" rx="1"></rect>
								<path d="M10.5 11.8 H17.5"></path>
							</svg>
						</a>
					</li>`;

				const $navbarList = $('header.navbar > .container > .navbar-collapse > ul');
				if ($navbarList.length) {
					$navbarList.prepend(icon);
				}

				if (!document.getElementById('iwlm-nav-icon-styles')) {
					$('head').append(`
						<style id="iwlm-nav-icon-styles">
							.iwlm-nav-button {
								display: flex; align-items: center; justify-content: center;
								width: 40px; height: 40px; margin-top: 4px;
								background: linear-gradient(135deg, #2dd4bf 0%, #0f766e 100%);
								color: #fff; text-decoration: none; border-radius: 50%;
								transition: all 0.3s ease; position: relative; overflow: hidden;
								box-shadow: 0 2px 8px rgba(13, 148, 136, 0.4);
							}
							.iwlm-nav-button:hover {
								background: linear-gradient(135deg, #14b8a6 0%, #0d5c56 100%);
								transform: translateY(-2px) scale(1.05);
								box-shadow: 0 4px 16px rgba(13, 148, 136, 0.55);
							}
							.iwlm-nav-button:active {
								transform: translateY(0) scale(0.98);
							}
							.iwlm-nav-button svg { width: 21px; height: 21px; color: #fff;
								filter: drop-shadow(0 1px 2px rgba(0,0,0,0.25)); }
						</style>`);
				}
			},
		});
	}

	function boot() {
		initPickingIcon();
		followOldRoute();
		if (frappe.router && frappe.router.on) {
			frappe.router.on('change', followOldRoute);
		}
	}

	if (typeof frappe !== 'undefined' && frappe.user) {
		$(document).ready(boot);
	} else {
		$(document).on('frappe:ready', boot);
	}
})();
