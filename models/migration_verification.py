from odoo import fields, models


class MigrationRunVerification(models.Model):
    _name = 'migration.run.verification'
    _description = 'Migration Run Verification (Source vs Target counts)'
    _order = 'run_id, model_key'

    run_id = fields.Many2one('migration.run', required=True, ondelete='cascade', index=True)
    model_key = fields.Char(required=True)
    source_model = fields.Char(required=True)
    source_count = fields.Integer(help='Records found on the source for this run\'s domain.')
    mapped_count = fields.Integer(help='Records that now have a source->target mapping.')
    created_count = fields.Integer()
    updated_count = fields.Integer()
    matched_count = fields.Integer()
    error_count = fields.Integer()
    status = fields.Selection([
        ('ready', 'Ready'),
        ('warning', 'Warning'),
        ('blocked', 'Blocked'),
    ], required=True)
    note = fields.Char()
