from odoo import fields, models


class MigrationCrmStageMapping(models.Model):
    _name = 'migration.crm.stage.mapping'
    _description = 'CRM Stage Mapping (Source -> Target)'
    _order = 'connection_id, sequence, id'

    connection_id = fields.Many2one('migration.connection', required=True,
                                     ondelete='cascade', index=True)
    source_stage_id = fields.Integer(required=True)
    source_stage_name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    target_stage_id = fields.Many2one('crm.stage', string='Target Stage')

    _sql_constraints = [
        ('stage_mapping_unique',
         'unique(connection_id, source_stage_id)',
         'Each source stage can only be mapped once per connection.'),
    ]
