{
    'name': "Fuel Station Module",
    'summary': "Module to manage a fuel station.",
    'description': """
        Fuel Station Management: deliveries, pump sessions, shift closes,
        credit sales, cash reconciliation, and dashboard.
    """,
    'author': "Voyance Consulting Co. Limited",
    'website': "https://www.voyanceconsults.com",
    'category': 'Fuel Station',
    'version': '0.5',

    'depends': ['base', 'mail', 'product', 'purchase', 'stock', 'hr', 'uom', 'account'],

    'assets': {
        'web.assets_backend': [
            'fuel_station/static/src/scss/fuel_station.scss',
        ],
    },

    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',

        # Core views
        'views/fuel_delivery_views.xml',
        'views/calibration_views.xml',
        'views/stock_picking_actions.xml',
        'views/stock_picking_views.xml',

        'views/fuel_shift_views.xml',
        'views/fuel_pump_views.xml',
        'views/fuel_nozzle_views.xml',
        'views/fuel_attendant_views.xml',
        'views/fuel_credit_sale_views.xml',
        'views/fuel_cash_deposit_views.xml',
        'views/fuel_credit_payment_views.xml',
        'views/fuel_attendant_session_views.xml',
        'views/fuel_station_shift_close_views.xml',

        # Dashboard (must come after all model views so server action
        # can reference them; also after product views so the inherit works)
        'views/fuel_dashboard_views.xml',

        'views/fuel_price_views.xml',
        'views/fuel_customer_statement_wizard_views.xml',

        'views/fuel_petty_cash_category_views.xml',
        'views/fuel_petty_cash_expense_views.xml',
        'views/fuel_petty_cash_replenishment_views.xml',
        'views/fuel_payout_views.xml',
        'views/fuel_station_config_views.xml',
        'views/res_partner_fuel_views.xml',

        'views/menu.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}