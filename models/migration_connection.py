from odoo import fields, models
from odoo.exceptions import UserError

from .migration_adapter import MigrationConnectionError, get_adapter


class MigrationConnection(models.Model):
    _name = 'migration.connection'
    _description = 'Migration Source Connection'
    _order = 'name'

    name = fields.Char(required=True)
    url = fields.Char(string='Server URL', required=True,
                       help='Base URL of the source Odoo server, e.g. https://old.example.com')
    database = fields.Char(string='Database', required=True)
    transport = fields.Selection(
        [('xmlrpc', 'XML-RPC')], default='xmlrpc', required=True,
        help='Protocol used to talk to the source database.')
    username = fields.Char(required=True)
    password = fields.Char(required=True, groups='base.group_system',
                            help='Password or API key. Only administrators can read this field.')

    odoo_version = fields.Char(string='Detected Odoo Version', readonly=True)
    state = fields.Selection(
        [('draft', 'Not Tested'), ('tested', 'Connected'), ('error', 'Error')],
        default='draft', readonly=True, copy=False)
    last_test_result = fields.Text(string='Last Result', readonly=True, copy=False)
    active = fields.Boolean(default=True)

    def _get_adapter(self):
        self.ensure_one()
        return get_adapter(self.transport, self.url, self.database,
                            self.username, self.password)

    def _notify(self, title, message, level='success', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': level,  # 'success', 'warning', 'danger', 'info'
                'sticky': sticky,
            },
        }

    def action_test_connection(self):
        self.ensure_one()
        adapter = self._get_adapter()
        try:
            adapter.connect()
        except MigrationConnectionError as exc:
            self.write({'state': 'error', 'last_test_result': str(exc)})
            return self._notify('Connection Failed', str(exc), level='danger', sticky=True)
        self.write({
            'state': 'tested',
            'last_test_result': 'Connected successfully as uid %s' % adapter.uid,
        })
        return self._notify('Connection Successful',
                             'Connected to %s as uid %s' % (self.database, adapter.uid))

    def action_detect_version(self):
        self.ensure_one()
        adapter = self._get_adapter()
        try:
            version = adapter.get_version()
        except MigrationConnectionError as exc:
            self.write({'state': 'error', 'last_test_result': str(exc)})
            return self._notify('Version Detection Failed', str(exc), level='danger', sticky=True)
        self.write({
            'state': 'tested',
            'odoo_version': version,
            'last_test_result': 'Detected server version: %s' % version,
        })
        return self._notify('Version Detected', 'Source server is running Odoo %s' % version)

    def fetch_source_models(self):
        """Fetch the list of models installed on the source as a first
        compatibility signal. Full model/field mapping UI is a later
        milestone (migration.model.mapping). Returns a list of dicts -
        callable from Python/other actions, not meant to be bound to a
        button directly (button-bound methods must return an action dict
        or None, not a plain list)."""
        self.ensure_one()
        adapter = self._get_adapter()
        try:
            adapter.connect()
            model_records = adapter.search_read(
                'ir.model', [], fields=['model', 'name'], order='model')
        except MigrationConnectionError as exc:
            self.write({'state': 'error', 'last_test_result': str(exc)})
            raise UserError(str(exc)) from exc

        self.write({
            'state': 'tested',
            'last_test_result': 'Loaded %s models from source database.' % len(model_records),
        })
        return model_records

    def action_load_models(self):
        """Button entry point - runs fetch_source_models() and shows a
        notification with the result."""
        self.ensure_one()
        try:
            model_records = self.fetch_source_models()
        except UserError as exc:
            return self._notify('Load Models Failed', str(exc), level='danger', sticky=True)
        return self._notify('Models Loaded',
                             'Loaded %s models from the source database.' % len(model_records))

    def action_open_wizard(self):
        """Launch the Migration Wizard pre-filled with this connection."""
        self.ensure_one()
        if self.state == 'draft':
            raise UserError('Please Test Connection first.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Migration Wizard',
            'res_model': 'migration.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_connection_id': self.id},
        }
