from odoo import fields, models


class MigrationRecordMapping(models.Model):
    _name = 'migration.record.mapping'
    _description = 'Migration Source -> Target Record Mapping'
    _rec_name = 'target_res_id'

    connection_id = fields.Many2one('migration.connection', required=True,
                                     ondelete='cascade', index=True)
    source_model = fields.Char(required=True, index=True)
    source_res_id = fields.Integer(required=True, index=True)
    target_model = fields.Char(required=True)
    target_res_id = fields.Integer(required=True)

    _sql_constraints = [
        ('mapping_unique',
         'unique(connection_id, source_model, source_res_id)',
         'A source record can only be mapped once per connection.'),
    ]

    def get_target_id(self, connection_id, source_model, source_res_id):
        """Return the target id already mapped for this source record, or False."""
        mapping = self.search([
            ('connection_id', '=', connection_id),
            ('source_model', '=', source_model),
            ('source_res_id', '=', source_res_id),
        ], limit=1)
        return mapping.target_res_id if mapping else False

    def get_target_ids(self, connection_id, source_model, source_res_ids):
        """Bulk lookup: returns {source_res_id: target_res_id} for the ids that are mapped."""
        if not source_res_ids:
            return {}
        mappings = self.search([
            ('connection_id', '=', connection_id),
            ('source_model', '=', source_model),
            ('source_res_id', 'in', source_res_ids),
        ])
        return {m.source_res_id: m.target_res_id for m in mappings}

    def set_mapping(self, connection_id, source_model, source_res_id, target_model, target_res_id):
        existing = self.search([
            ('connection_id', '=', connection_id),
            ('source_model', '=', source_model),
            ('source_res_id', '=', source_res_id),
        ], limit=1)
        if existing:
            existing.write({'target_model': target_model, 'target_res_id': target_res_id})
            return existing
        return self.create({
            'connection_id': connection_id,
            'source_model': source_model,
            'source_res_id': source_res_id,
            'target_model': target_model,
            'target_res_id': target_res_id,
        })
