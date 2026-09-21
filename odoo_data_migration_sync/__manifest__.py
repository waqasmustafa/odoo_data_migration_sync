{
    'name': 'Odoo Data Migration & Sync | Odoo to Odoo Migration | Database Sync Connector | Odoo to Odoo Connector',

    'summary': 'Connect two Odoo databases and safely migrate/sync Contacts, Products, CRM, HR, Inventory, Projects, Sales, Purchase & POS data',

    'description': '''
        Connect a source Odoo database (16/17/18) to this Odoo installation and analyze, map, preview, migrate and verify selected business data - including cross-version migration into Odoo 18.

        This is a data migration and synchronization tool, not a one-click full Odoo database upgrade. Target-compatible modules must already be installed on this database before their data can be migrated.

        Features:
        • Guided Migration Wizard - Connect, Select, Dry Run / Preview, Migrate, Verify
        • Contacts (with full address, archived records, company hierarchy)
        • Product Categories, Attributes, Variants & Products (image, tags, pricing)
        • Employees & Departments, Time Off / Leaves
        • Inventory master data - Warehouses & Locations (no risky quantity copying)
        • CRM Leads/Opportunities with configurable CRM Stage Mapping
        • Projects & Tasks, Timesheets
        • Sales Orders and Purchase Orders with full line detail (taxes, payment terms, currency)
        • Point of Sale Orders (header + lines)
        • Dry-Run / Preview before writing any data - clear create/update/skip/error counts
        • Duplicate prevention via record mapping and configurable business-key matching
        • Dependency-aware migration order with automatic missing-dependency retries
        • Record-level error log with one-click Retry
        • Post-migration Verification report (Ready / Warning / Blocked per model)
        • Dashboard with connection, run and record statistics
        • Batch processing for large datasets

        Perfect for Odoo Community users performing fresh-target migrations, Odoo partners who migrate client databases repeatedly, freelance Odoo developers, and companies running multiple Odoo databases.

        Configuration:
        • Simple setup through the Migration app
        • Server URL + Database + Username + API Key (or password) per connection
        • Test Connection, Detect Version and Load Models before migrating
        • Choose which data types to migrate per run
        • Create Only / Update Only / Create + Update modes

        Technical Highlights:
        • Adapter-based transport architecture (XML-RPC today, ready for future Odoo APIs)
        • Source and target field names are safety-checked at runtime, so a version difference degrades gracefully instead of crashing a run
        • Idempotent record mapping - safe to re-run a migration without creating duplicates
        • Clean, maintainable code architecture
    ''',

    'author': 'Waqas Mustafa',
    'website': 'https://www.linkedin.com/in/waqas-mustafa-ba5701209/',
    'support': 'mustafawaqas0@gmail.com',

    'price': 149.00,
    'currency': 'USD',

    'version': '18.0.1.0.0',
    'license': 'OPL-1',
    'category': 'Extra Tools',

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

    'images': [
        'static/description/banner.gif',
        'static/description/icon.png',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,
}
