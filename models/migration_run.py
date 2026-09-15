from odoo import fields, models


class MigrationRun(models.Model):
    _name = 'migration.run'
    _description = 'Migration Run'
    _order = 'create_date desc'

    name = fields.Char(default='New Migration Run', required=True)
    connection_id = fields.Many2one('migration.connection', required=True, ondelete='cascade')
    model_keys = fields.Char(
        required=True,
        help='Comma-separated internal keys of the migrators included in this run, '
             'e.g. res_partner,product_category,product_template')
    mode = fields.Selection([
        ('create_only', 'Create Only'),
        ('update_only', 'Update Only'),
        ('create_update', 'Create + Update'),
    ], default='create_update', required=True)
    dry_run = fields.Boolean(default=True, string='Dry Run',
                              help='If enabled, no data is written to this database - only counted.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Failed'),
    ], default='draft', readonly=True, copy=False)

    start_date = fields.Datetime(readonly=True)
    end_date = fields.Datetime(readonly=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)

    created_count = fields.Integer(readonly=True, copy=False)
    updated_count = fields.Integer(readonly=True, copy=False)
    skipped_count = fields.Integer(readonly=True, copy=False)
    error_count = fields.Integer(readonly=True, copy=False)

    line_ids = fields.One2many('migration.run.line', 'run_id')

    def _get_runner_class(self):
        from .migration_engine import MigrationRunner
        return MigrationRunner

    def action_run(self):
        for run in self:
            runner = run._get_runner_class()(self.env, run)
            runner.run_all()
        return True

    def action_view_errors(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Errors - %s' % self.name,
            'res_model': 'migration.run.line',
            'view_mode': 'list,form',
            'domain': [('run_id', '=', self.id), ('state', '=', 'error')],
        }


class MigrationRunLine(models.Model):
    _name = 'migration.run.line'
    _description = 'Migration Run Record Log'
    _order = 'id'

    run_id = fields.Many2one('migration.run', required=True, ondelete='cascade', index=True)
    model_key = fields.Char(required=True)
    source_model = fields.Char(required=True)
    source_res_id = fields.Integer(required=True)
    target_res_id = fields.Integer()
    state = fields.Selection([
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('matched', 'Matched Existing'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
    ], required=True, index=True)
    message = fields.Char()
    missing_dependency = fields.Char(
        help='Source model/id this record depends on that was not migrated yet.')

    def action_retry(self):
        """Re-run only the failed lines of the parent run(s)."""
        source_ids_by_run_model = {}
        for line in self.filtered(lambda l: l.state == 'error'):
            key = (line.run_id.id, line.model_key)
            source_ids_by_run_model.setdefault(key, []).append(line.source_res_id)

        MigrationRunner = self.env['migration.run']._get_runner_class()
        for (run_id, model_key), source_ids in source_ids_by_run_model.items():
            run = self.env['migration.run'].browse(run_id)
            runner = MigrationRunner(self.env, run)
            runner.run_migrator(model_key, only_source_ids=source_ids)
        return True
