from odoo import fields, models
from odoo.exceptions import UserError


class MigrationWizard(models.TransientModel):
    _name = 'migration.wizard'
    _description = 'Guided Migration Wizard'

    connection_id = fields.Many2one('migration.connection', required=True,
                                     string='Source Connection')

    migrate_partners = fields.Boolean(string='Contacts', default=True)
    migrate_categories = fields.Boolean(string='Product Categories', default=True)
    migrate_products = fields.Boolean(string='Products', default=True)
    migrate_crm = fields.Boolean(string='CRM Leads/Opportunities')
    migrate_sales = fields.Boolean(string='Sales Orders')
    migrate_purchases = fields.Boolean(string='Purchase Orders')

    mode = fields.Selection([
        ('create_only', 'Create Only'),
        ('update_only', 'Update Only'),
        ('create_update', 'Create + Update'),
    ], default='create_update', required=True)

    last_run_id = fields.Many2one('migration.run', readonly=True)

    def _selected_keys(self):
        mapping = {
            'migrate_partners': ('res_partner',),
            'migrate_categories': ('product_category',),
            'migrate_products': ('product_attribute', 'product_attribute_value', 'product_template'),
            'migrate_crm': ('crm_lead',),
            'migrate_sales': ('sale_order',),
            'migrate_purchases': ('purchase_order',),
        }
        keys = []
        for field, field_keys in mapping.items():
            if self[field]:
                keys.extend(field_keys)
        if not keys:
            raise UserError('Select at least one type of data to migrate.')
        return keys

    def _create_and_run(self, dry_run):
        self.ensure_one()
        if self.connection_id.state == 'draft':
            raise UserError('Please Test Connection on the source before migrating.')
        keys = self._selected_keys()
        run = self.env['migration.run'].create({
            'name': '%s - %s' % (self.connection_id.name, 'Dry Run' if dry_run else 'Migration'),
            'connection_id': self.connection_id.id,
            'model_keys': ','.join(keys),
            'mode': self.mode,
            'dry_run': dry_run,
        })
        run.action_run()
        self.last_run_id = run.id
        return run

    def action_analyze(self):
        """Step 3/4: Compatibility analysis + Dry Run preview - writes nothing."""
        run = self._create_and_run(dry_run=True)
        return self._open_run(run)

    def action_migrate(self):
        """Step 5: actually migrate the selected data."""
        run = self._create_and_run(dry_run=False)
        return self._open_run(run)

    def _open_run(self, run):
        return {
            'type': 'ir.actions.act_window',
            'name': run.name,
            'res_model': 'migration.run',
            'res_id': run.id,
            'view_mode': 'form',
            'target': 'current',
        }
