from .migration_engine import BaseMigrator, register_migrator


class _AddressMixin:
    """Shared country/state resolution for any migrator whose source model
    carries a direct country_id/state_id (res.partner, crm.lead)."""

    def _resolve_country(self, country_field):
        if not country_field:
            return False
        return self.resolve_by_name('res.country', country_field[1], '_country_cache')

    def _resolve_state(self, state_field, country_id):
        if not state_field:
            return False
        name = state_field[1]
        cache = getattr(self, '_state_cache', None)
        if cache is None:
            cache = {}
            self._state_cache = cache
        cache_key = (name, country_id)
        if cache_key in cache:
            return cache[cache_key]
        domain = [('name', '=', name)]
        if country_id:
            domain.append(('country_id', '=', country_id))
        rec = self.env['res.country.state'].search(domain, limit=1)
        cache[cache_key] = rec.id if rec else False
        return cache[cache_key]


@register_migrator('res_partner')
class ResPartnerMigrator(_AddressMixin, BaseMigrator):
    source_model = 'res.partner'
    target_model = 'res.partner'
    source_fields = [
        'name', 'is_company', 'company_type', 'street', 'street2', 'city',
        'zip', 'phone', 'mobile', 'email', 'website', 'vat', 'ref',
        'function', 'lang', 'parent_id', 'country_id', 'state_id', 'title',
    ]
    matching_keys = ['ref', 'vat', 'email']
    self_referential_fields = ['parent_id']

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'is_company': bool(record.get('is_company')),
            'company_type': record.get('company_type') or (
                'company' if record.get('is_company') else 'person'),
            'street': record.get('street') or False,
            'street2': record.get('street2') or False,
            'city': record.get('city') or False,
            'zip': record.get('zip') or False,
            'phone': record.get('phone') or False,
            'mobile': record.get('mobile') or False,
            'email': record.get('email') or False,
            'website': record.get('website') or False,
            'vat': record.get('vat') or False,
            'ref': record.get('ref') or False,
            'function': record.get('function') or False,
        }
        parent_id, missing = self.resolve_m2o('res.partner', record.get('parent_id'))
        if missing:
            return values, missing
        if parent_id:
            values['parent_id'] = parent_id

        country_id = self._resolve_country(record.get('country_id'))
        if country_id:
            values['country_id'] = country_id

        state_id = self._resolve_state(record.get('state_id'), country_id)
        if state_id:
            values['state_id'] = state_id

        title = record.get('title')
        if title:
            title_id = self.resolve_by_name('res.partner.title', title[1], '_title_cache')
            if title_id:
                values['title'] = title_id

        return values, None


@register_migrator('product_category')
class ProductCategoryMigrator(BaseMigrator):
    source_model = 'product.category'
    target_model = 'product.category'
    source_fields = ['name', 'parent_id']
    matching_keys = ['name']  # unused directly - find_business_match is overridden below
    self_referential_fields = ['parent_id']

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown'}
        parent_id, missing = self.resolve_m2o('product.category', record.get('parent_id'))
        if missing:
            return values, missing
        if parent_id:
            values['parent_id'] = parent_id
        return values, None

    def find_business_match(self, values):
        """Match on name scoped to the (already-resolved) parent category,
        not on name alone - two different categories under different
        parents (e.g. "Accessories" under both "Electronics" and
        "Furniture") must never be treated as the same record."""
        Target = self.env[self.target_model]
        name = values.get('name')
        if not name:
            return Target.browse(), None, None
        domain = [('name', '=', name), ('parent_id', '=', values.get('parent_id') or False)]
        found = Target.search(domain, limit=2)
        if len(found) != 1:
            return Target.browse(), None, None
        if self._is_target_claimed(found.id):
            return Target.browse(), None, (
                'Business-key match on "name+parent" ignored - already linked to '
                'a different source record; created as a new record instead.')
        return found, 'name+parent', None


@register_migrator('product_template')
class ProductTemplateMigrator(BaseMigrator):
    source_model = 'product.template'
    target_model = 'product.template'
    source_fields = [
        'name', 'default_code', 'barcode', 'type', 'sale_ok', 'purchase_ok',
        'list_price', 'standard_price', 'categ_id', 'uom_id', 'uom_po_id',
        'description_sale', 'product_variant_id',
    ]
    matching_keys = ['default_code', 'barcode']

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'default_code': record.get('default_code') or False,
            'barcode': record.get('barcode') or False,
            'sale_ok': bool(record.get('sale_ok')),
            'purchase_ok': bool(record.get('purchase_ok')),
            'list_price': record.get('list_price') or 0.0,
            'standard_price': record.get('standard_price') or 0.0,
            'description_sale': record.get('description_sale') or False,
        }
        # 'type' (goods/service/combo) selection values have changed across
        # Odoo versions - copy only if the target still accepts it.
        product_type = record.get('type')
        if product_type in ('consu', 'service'):
            values['type'] = product_type

        categ_id, missing = self.resolve_m2o('product.category', record.get('categ_id'))
        if missing:
            return values, missing
        if categ_id:
            values['categ_id'] = categ_id

        uom = record.get('uom_id')
        if uom:
            uom_id = self.resolve_by_name('uom.uom', uom[1], '_uom_cache')
            if uom_id:
                values['uom_id'] = uom_id
        uom_po = record.get('uom_po_id')
        if uom_po:
            uom_po_id = self.resolve_by_name('uom.uom', uom_po[1], '_uom_cache')
            if uom_po_id:
                values['uom_po_id'] = uom_po_id

        return values, None

    def _after_write(self, record, target_id):
        # A template without variant attributes has exactly one auto-created
        # product.product ("variant"). Map it too so sale/purchase order
        # lines (which reference product.product, not product.template) can
        # resolve it. Multi-variant products are a known V1 limitation.
        source_variant = record.get('product_variant_id')
        if not source_variant:
            return
        source_variant_id = source_variant[0] if isinstance(source_variant, (list, tuple)) else source_variant
        target_template = self.env[self.target_model].browse(target_id)
        target_variant_id = target_template.product_variant_id.id
        if target_variant_id:
            self.Mapping.set_mapping(
                self.connection.id, 'product.product', source_variant_id,
                'product.product', target_variant_id)


@register_migrator('crm_lead')
class CrmLeadMigrator(_AddressMixin, BaseMigrator):
    source_model = 'crm.lead'
    target_model = 'crm.lead'
    source_fields = [
        'name', 'partner_name', 'contact_name', 'email_from', 'phone', 'mobile',
        'website', 'function', 'street', 'street2', 'city', 'zip', 'country_id',
        'state_id', 'description', 'type', 'partner_id', 'expected_revenue',
        'probability', 'priority', 'date_deadline', 'stage_id', 'user_id',
        'team_id', 'tag_ids', 'source_id', 'medium_id', 'lost_reason_id',
    ]
    matching_keys = []
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'partner_name': record.get('partner_name') or False,
            'contact_name': record.get('contact_name') or False,
            'email_from': record.get('email_from') or False,
            'phone': record.get('phone') or False,
            'mobile': record.get('mobile') or False,
            'website': record.get('website') or False,
            'function': record.get('function') or False,
            'street': record.get('street') or False,
            'street2': record.get('street2') or False,
            'city': record.get('city') or False,
            'zip': record.get('zip') or False,
            'description': record.get('description') or False,
            'type': record.get('type') or 'lead',
            'expected_revenue': record.get('expected_revenue') or 0.0,
            'probability': record.get('probability') or 0.0,
            'priority': record.get('priority') or '0',
            'date_deadline': record.get('date_deadline') or False,
        }

        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            # A lead's linked customer is nice-to-have, not required - do not block.
            missing = None
        if partner_id:
            values['partner_id'] = partner_id

        country_id = self._resolve_country(record.get('country_id'))
        if country_id:
            values['country_id'] = country_id
        state_id = self._resolve_state(record.get('state_id'), country_id)
        if state_id:
            values['state_id'] = state_id

        stage_id = self._resolve_stage(record.get('stage_id'))
        if stage_id:
            values['stage_id'] = stage_id

        user_id = self.resolve_user(record.get('user_id'))
        if user_id:
            values['user_id'] = user_id

        team = record.get('team_id')
        if team:
            team_id = self.resolve_by_name('crm.team', team[1], '_team_cache')
            if team_id:
                values['team_id'] = team_id

        source = record.get('source_id')
        if source:
            source_id = self.resolve_or_create_by_name('utm.source', source[1], '_source_cache')
            if source_id:
                values['source_id'] = source_id

        medium = record.get('medium_id')
        if medium:
            medium_id = self.resolve_or_create_by_name('utm.medium', medium[1], '_medium_cache')
            if medium_id:
                values['medium_id'] = medium_id

        lost_reason = record.get('lost_reason_id')
        if lost_reason:
            lost_reason_id = self.resolve_by_name(
                'crm.lost.reason', lost_reason[1], '_lost_reason_cache')
            if lost_reason_id:
                values['lost_reason_id'] = lost_reason_id

        tag_ids = record.get('tag_ids')
        if tag_ids:
            values['tag_ids'] = [(6, 0, self.resolve_or_create_m2m_by_name(
                'crm.tag', tag_ids, 'crm.tag', '_tag_cache'))]

        return values, missing

    def _resolve_stage(self, stage_field):
        if not stage_field:
            return False
        source_stage_id = stage_field[0] if isinstance(stage_field, (list, tuple)) else stage_field
        cache = getattr(self, '_stage_cache', None)
        if cache is None:
            cache = {}
            self._stage_cache = cache
        if source_stage_id in cache:
            return cache[source_stage_id]
        mapping = self.env['migration.crm.stage.mapping'].search([
            ('connection_id', '=', self.connection.id),
            ('source_stage_id', '=', source_stage_id),
        ], limit=1)
        target_id = mapping.target_stage_id.id if mapping and mapping.target_stage_id else False
        cache[source_stage_id] = target_id
        return target_id


class _OrderMigratorMixin:
    """Shared line-building logic for sale.order and purchase.order.

    Lines are only (re)written the first time an order is created - once a
    mapping exists, later runs only update header fields. Re-syncing lines
    on an order that may already have invoices/receipts against it is out
    of scope for V1 (documented limitation).
    """
    line_model = None
    line_field = None
    qty_field = None
    line_source_fields = []

    def _build_lines(self, order_record):
        line_ids = order_record.get(self.line_field) or []
        if not line_ids:
            return [], None
        lines = self.adapter.read(self.line_model, line_ids, fields=self.line_source_fields)
        commands = []
        for line in lines:
            product_id, missing = self.resolve_m2o('product.product', line.get('product_id'))
            if line.get('product_id') and missing:
                return None, missing
            line_vals = {
                'name': line.get('name') or '',
                self.qty_field: line.get(self.qty_field) or 0.0,
                'price_unit': line.get('price_unit') or 0.0,
            }
            if line.get('discount'):
                line_vals['discount'] = line['discount']
            if product_id:
                line_vals['product_id'] = product_id
            uom = line.get('product_uom')
            if uom:
                uom_id = self.resolve_by_name('uom.uom', uom[1], '_uom_cache')
                if uom_id:
                    line_vals['product_uom'] = uom_id
            commands.append((0, 0, line_vals))
        return commands, None


@register_migrator('sale_order')
class SaleOrderMigrator(_OrderMigratorMixin, BaseMigrator):
    source_model = 'sale.order'
    target_model = 'sale.order'
    source_fields = ['name', 'partner_id', 'date_order', 'client_order_ref', 'order_line']
    matching_keys = []
    line_model = 'sale.order.line'
    line_field = 'order_line'
    qty_field = 'product_uom_qty'
    line_source_fields = ['product_id', 'name', 'product_uom_qty', 'product_uom', 'price_unit', 'discount']

    def transform(self, record, is_update=False):
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            return {}, missing
        values = {
            'partner_id': partner_id,
            'date_order': record.get('date_order') or False,
            'client_order_ref': record.get('client_order_ref') or False,
        }
        if not is_update:
            lines, missing = self._build_lines(record)
            if missing:
                return values, missing
            values['order_line'] = lines
        return values, None


@register_migrator('purchase_order')
class PurchaseOrderMigrator(_OrderMigratorMixin, BaseMigrator):
    source_model = 'purchase.order'
    target_model = 'purchase.order'
    source_fields = ['name', 'partner_id', 'date_order', 'partner_ref', 'order_line']
    matching_keys = []
    line_model = 'purchase.order.line'
    line_field = 'order_line'
    qty_field = 'product_qty'
    line_source_fields = ['product_id', 'name', 'product_qty', 'product_uom', 'price_unit']

    def transform(self, record, is_update=False):
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            return {}, missing
        values = {
            'partner_id': partner_id,
            'date_order': record.get('date_order') or False,
            'partner_ref': record.get('partner_ref') or False,
        }
        if not is_update:
            lines, missing = self._build_lines(record)
            if missing:
                return values, missing
            values['order_line'] = lines
        return values, None
