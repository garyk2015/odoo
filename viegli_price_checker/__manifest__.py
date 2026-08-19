{
    'name': 'Viegli Quick Reseller Price Checker',
    'version': '1.0',
    'summary': 'Instant SKU & Reseller Pricelist Lookup for Sales Support',
    'category': 'Sales',
    'author': 'Viegli UK Ltd',
    'depends': ['sale_management', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'views/price_checker_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}