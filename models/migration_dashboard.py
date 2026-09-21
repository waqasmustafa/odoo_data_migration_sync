from odoo import fields, models


class MigrationDashboard(models.TransientModel):
    _name = 'migration.dashboard'
    _description = 'Migration Dashboard'

    connection_count = fields.Integer(readonly=True)
    run_count = fields.Integer(readonly=True)
    run_done_count = fields.Integer(readonly=True)
    run_error_count = fields.Integer(readonly=True)
    run_running_count = fields.Integer(readonly=True)
    total_created = fields.Integer(readonly=True)
    total_updated = fields.Integer(readonly=True)
    total_errors = fields.Integer(readonly=True)
    last_run_id = fields.Many2one('migration.run', readonly=True)

    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        Run = self.env['migration.run']
        Connection = self.env['migration.connection']

        runs = Run.search([])
        values.update({
            'connection_count': Connection.search_count([]),
            'run_count': len(runs),
            'run_done_count': len(runs.filtered(lambda r: r.state == 'done')),
            'run_error_count': len(runs.filtered(lambda r: r.state == 'error')),
            'run_running_count': len(runs.filtered(lambda r: r.state == 'running')),
            'total_created': sum(runs.mapped('created_count')),
            'total_updated': sum(runs.mapped('updated_count')),
            'total_errors': sum(runs.mapped('error_count')),
            'last_run_id': runs[:1].id if runs else False,
        })
        return values

    def action_view_connections(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Connections',
            'res_model': 'migration.connection',
            'view_mode': 'list,form',
        }

    def action_view_runs(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Runs',
            'res_model': 'migration.run',
            'view_mode': 'list,form',
        }

    def action_view_errors(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Errors',
            'res_model': 'migration.run.line',
            'view_mode': 'list,form',
            'domain': [('state', '=', 'error')],
        }

    def action_refresh(self):
        self.ensure_one()
        self.write(self.default_get(list(self._fields.keys())))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Migration Dashboard',
            'res_model': 'migration.dashboard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
