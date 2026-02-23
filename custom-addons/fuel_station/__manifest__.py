{
    'name': "Fuel Station Module",

    'summary': "Module to manage a fuel station.",

    'description': """
Long description of module's purpose
    """,

    'author': "Voyance Consulting Co. Limited",
    'website': "https://www.voyanceconsults.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Fuel Station',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'product', 'purchase', 'stock'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/fuel_delivery_views.xml',
        'views/calibration_views.xml',
        'views/stock_picking_actions.xml',
        'views/stock_picking_views.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',

    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}

