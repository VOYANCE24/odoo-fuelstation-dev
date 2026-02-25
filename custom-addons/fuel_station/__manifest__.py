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
    'version': '0.2',

    'depends': ['base', 'product', 'purchase', 'stock', 'hr'],

    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',

        # Core views
        'views/fuel_delivery_views.xml',
        'views/calibration_views.xml',
        'views/stock_picking_actions.xml',
        'views/stock_picking_views.xml',

        'views/fuel_shift_views.xml',
        'views/fuel_pump_views.xml',
        'views/fuel_attendant_views.xml',
        'views/fuel_credit_sale_views.xml',
        'views/fuel_cash_deposit_views.xml',
        'views/fuel_credit_payment_views.xml',
        'views/fuel_attendant_session_views.xml',
        'views/fuel_station_shift_close_views.xml',

        # Dashboard (must come after all model views so server action
        # can reference them; also after product views so the inherit works)
        'views/fuel_dashboard_views.xml',

        'views/menu.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}