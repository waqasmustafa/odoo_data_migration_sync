{
    'name': 'Odoo Data Migration & Sync',
    'version': '18.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Connect two Odoo databases and safely migrate/sync business data',
    'description': """
Odoo Data Migration & Sync
===========================
Connect a source Odoo database (16/17/18) to this Odoo 18 database and
analyze, map, preview, migrate and verify selected business data.

This is a data migration and synchronization tool, not a one-click full
Odoo database upgrade. Target-compatible modules must already be installed
on this database before their data can be migrated.
""",
    'author': 'Waqas Mustafa',
    'license': 'OPL-1',
    'depends': [
        'base', 'product', 'crm', 'sale', 'purchase', 'hr', 'stock', 'project',
        'hr_holidays', 'hr_timesheet',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/migration_connection_views.xml',
        'views/migration_run_views.xml',
        'views/migration_mapping_views.xml',
        'views/migration_stage_mapping_views.xml',
        'views/migration_dashboard_views.xml',
        'wizard/migration_wizard_views.xml',
        'views/migration_menus.xml',
    ],
    'installable': True,
    'application': True,
}
