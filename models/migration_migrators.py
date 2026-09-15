from .migration_engine import BaseMigrator, register_migrator


@register_migrator('res_partner')
class ResPartnerMigrator(BaseMigrator):
    source_model = 'res.partner'
    target_model = 'res.partner'
    source_fields = [
        'name', 'is_company', 'company_type', 'street', 'street2', 'city',
        'zip', 'phone', 'mobile', 'email', 'website', 'vat', 'ref',
        'function', 'lang', 'parent_id',
    ]
    matching_keys = ['ref', 'vat', 'email']

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
        return values, None


@register_migrator('product_category')
class ProductCategoryMigrator(BaseMigrator):
    source_model = 'product.category'
    target_model = 'product.category'
    source_fields = ['name', 'parent_id']
    matching_keys = ['name']

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown'}
        parent_id, missing = self.resolve_m2o('product.category', record.get('parent_id'))
        if missing:
            return values, missing
        if parent_id:
            values['parent_id'] = parent_id
        return values, None


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
class CrmLeadMigrator(BaseMigrator):
    source_model = 'crm.lead'
    target_model = 'crm.lead'
    source_fields = [
        'name', 'partner_name', 'contact_name', 'email_from', 'phone',
        'description', 'type', 'partner_id', 'expected_revenue', 'probability',
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
            'description': record.get('description') or False,
            'type': record.get('type') or 'lead',
            'expected_revenue': record.get('expected_revenue') or 0.0,
            'probability': record.get('probability') or 0.0,
        }
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            # A lead's linked customer is nice-to-have, not required - do not block.
            missing = None
        if partner_id:
            values['partner_id'] = partner_id
        return values, missing


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
