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
        'active',
    ]
    matching_keys = ['ref', 'vat', 'email']
    self_referential_fields = ['parent_id']
    # Without this, a source contact that is archived (e.g. a technical
    # "Public user" partner used by anonymous website orders) is silently
    # excluded, and anything referencing it later (a Sales/Purchase Order,
    # a CRM lead) fails as a missing dependency even though the partner
    # genuinely exists on the source.
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'is_company': bool(record.get('is_company')),
            'company_type': record.get('company_type') or (
                'company' if record.get('is_company') else 'person'),
            'active': record.get('active', True),
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
    source_fields = ['name', 'parent_id', 'active']
    matching_keys = ['name']  # unused directly - find_business_match is overridden below
    self_referential_fields = ['parent_id']
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown', 'active': record.get('active', True)}
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


@register_migrator('product_attribute')
class ProductAttributeMigrator(BaseMigrator):
    source_model = 'product.attribute'
    target_model = 'product.attribute'
    source_fields = ['name', 'create_variant']
    matching_keys = ['name']
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown'}
        create_variant = record.get('create_variant')
        if create_variant in ('always', 'dynamic', 'no_variant'):
            values['create_variant'] = create_variant
        return values, None


@register_migrator('product_attribute_value')
class ProductAttributeValueMigrator(BaseMigrator):
    source_model = 'product.attribute.value'
    target_model = 'product.attribute.value'
    source_fields = ['name', 'attribute_id']
    matching_keys = []  # find_business_match is overridden below (scoped to attribute)
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        attribute_id, missing = self.resolve_m2o('product.attribute', record.get('attribute_id'))
        if missing:
            return {}, missing
        values = {'name': record.get('name') or 'Unknown'}
        if attribute_id:
            values['attribute_id'] = attribute_id
        return values, None

    def find_business_match(self, values):
        """A value's name is only unique within its own attribute (e.g.
        "M" exists under both "Size" and some other attribute) - never
        match on name alone."""
        Target = self.env[self.target_model]
        name = values.get('name')
        attribute_id = values.get('attribute_id')
        if not name or not attribute_id:
            return Target.browse(), None, None
        found = Target.search([('name', '=', name), ('attribute_id', '=', attribute_id)], limit=2)
        if len(found) != 1:
            return Target.browse(), None, None
        if self._is_target_claimed(found.id):
            return Target.browse(), None, (
                'Business-key match on "name+attribute" ignored - already linked '
                'to a different source record; created as a new record instead.')
        return found, 'name+attribute', None


@register_migrator('product_template')
class ProductTemplateMigrator(BaseMigrator):
    source_model = 'product.template'
    target_model = 'product.template'
    source_fields = [
        'name', 'default_code', 'barcode', 'type', 'sale_ok', 'purchase_ok',
        'list_price', 'standard_price', 'categ_id', 'uom_id', 'uom_po_id',
        'description_sale', 'description_purchase', 'weight', 'volume',
        'image_1920', 'product_tag_ids', 'attribute_line_ids', 'active',
        'product_variant_id', 'product_variant_ids',
    ]
    matching_keys = ['default_code', 'barcode']
    # A discontinued/archived product referenced by an old Sales or
    # Purchase order line must still be migrated, or that order line fails
    # as a missing dependency (same failure mode diagnosed for contacts).
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'active': record.get('active', True),
            'default_code': record.get('default_code') or False,
            'barcode': record.get('barcode') or False,
            'sale_ok': bool(record.get('sale_ok')),
            'purchase_ok': bool(record.get('purchase_ok')),
            'list_price': record.get('list_price') or 0.0,
            'standard_price': record.get('standard_price') or 0.0,
            'description_sale': record.get('description_sale') or False,
            'description_purchase': record.get('description_purchase') or False,
            'weight': record.get('weight') or 0.0,
            'volume': record.get('volume') or 0.0,
            'image_1920': record.get('image_1920') or False,
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

        tag_ids = record.get('product_tag_ids')
        if tag_ids:
            values['product_tag_ids'] = [(6, 0, self.resolve_or_create_m2m_by_name(
                'product.tag', tag_ids, 'product.tag', '_tag_cache'))]

        # Variant attributes (Color, Size, ...) are only set up on first
        # create - Odoo auto-generates the product.product variants for
        # every combination from this. Re-syncing attribute lines on an
        # already-migrated template is out of scope for V1 (documented
        # limitation, same reasoning as sale/purchase order lines).
        if not is_update:
            lines, missing = self._build_attribute_lines(record)
            if missing:
                return values, missing
            if lines:
                values['attribute_line_ids'] = lines

        return values, None

    def _build_attribute_lines(self, record):
        line_ids = record.get('attribute_line_ids') or []
        if not line_ids:
            return [], None
        lines = self.adapter.read(
            'product.template.attribute.line', line_ids, fields=['attribute_id', 'value_ids'])
        commands = []
        for line in lines:
            attribute_id, missing = self.resolve_m2o('product.attribute', line.get('attribute_id'))
            if missing:
                return None, missing
            value_ids, missing = self.resolve_m2m(
                'product.attribute.value', line.get('value_ids') or [])
            if missing:
                return None, missing
            if attribute_id and value_ids:
                commands.append((0, 0, {
                    'attribute_id': attribute_id,
                    'value_ids': [(6, 0, value_ids)],
                }))
        return commands, None

    def _after_write(self, record, target_id):
        """Map every source product.product variant onto the matching
        auto-generated target variant, identified by comparing their
        (attribute, value) combinations - not by list position, which can
        differ between databases."""
        source_variant_ids = record.get('product_variant_ids') or []
        if not source_variant_ids:
            return

        target_template = self.env[self.target_model].browse(target_id)
        target_variants = target_template.product_variant_ids

        if len(source_variant_ids) == 1 and len(target_variants) == 1:
            self.Mapping.set_mapping(
                self.connection.id, 'product.product', source_variant_ids[0],
                'product.product', target_variants.id)
            return

        source_variants = self.adapter.read(
            'product.product', source_variant_ids,
            fields=['product_template_attribute_value_ids'])
        all_ptav_ids = set()
        for variant in source_variants:
            all_ptav_ids.update(variant.get('product_template_attribute_value_ids') or [])

        ptav_by_id = {}
        if all_ptav_ids:
            for ptav in self.adapter.read(
                    'product.template.attribute.value', list(all_ptav_ids),
                    fields=['attribute_id', 'product_attribute_value_id']):
                ptav_by_id[ptav['id']] = ptav

        def source_signature(ptav_ids):
            sig = []
            for ptav_id in ptav_ids:
                ptav = ptav_by_id.get(ptav_id)
                if not ptav:
                    continue
                attr_id, _ = self.resolve_m2o('product.attribute', ptav.get('attribute_id'))
                val_id, _ = self.resolve_m2o(
                    'product.attribute.value', ptav.get('product_attribute_value_id'))
                if attr_id and val_id:
                    sig.append((attr_id, val_id))
            return frozenset(sig)

        target_by_signature = {}
        for tv in target_variants:
            sig = frozenset(
                (ptav.attribute_id.id, ptav.product_attribute_value_id.id)
                for ptav in tv.product_template_attribute_value_ids)
            target_by_signature[sig] = tv.id

        for variant in source_variants:
            sig = source_signature(variant.get('product_template_attribute_value_ids') or [])
            target_variant_id = target_by_signature.get(sig)
            if target_variant_id:
                self.Mapping.set_mapping(
                    self.connection.id, 'product.product', variant['id'],
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


@register_migrator('hr_department')
class HrDepartmentMigrator(BaseMigrator):
    source_model = 'hr.department'
    target_model = 'hr.department'
    source_fields = ['name', 'parent_id']
    matching_keys = ['name']  # unused directly - find_business_match is overridden below
    self_referential_fields = ['parent_id']
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown'}
        parent_id, missing = self.resolve_m2o('hr.department', record.get('parent_id'))
        if missing:
            return values, missing
        if parent_id:
            values['parent_id'] = parent_id
        return values, None

    def find_business_match(self, values):
        """Same reasoning as product categories: a department name is only
        unique within its own parent (e.g. "Support" under both "Sales"
        and "Engineering")."""
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


@register_migrator('hr_employee')
class HrEmployeeMigrator(BaseMigrator):
    source_model = 'hr.employee'
    target_model = 'hr.employee'
    source_fields = [
        'name', 'work_email', 'work_phone', 'mobile_phone', 'job_title',
        'department_id', 'parent_id', 'job_id', 'resource_calendar_id',
        'gender', 'birthday', 'identification_id', 'barcode', 'active',
    ]
    matching_keys = ['work_email', 'barcode']
    self_referential_fields = ['parent_id']  # manager is also an hr.employee
    # Terminated/archived employees must still be migrated, or an old Sales
    # Order/Project Task that names them as salesperson/assignee would fail
    # as a missing dependency (same failure mode diagnosed for contacts).
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'work_email': record.get('work_email') or False,
            'work_phone': record.get('work_phone') or False,
            'mobile_phone': record.get('mobile_phone') or False,
            'job_title': record.get('job_title') or False,
            'active': record.get('active', True),
            'identification_id': record.get('identification_id') or False,
            'barcode': record.get('barcode') or False,
        }
        if record.get('gender') in ('male', 'female', 'other'):
            values['gender'] = record['gender']
        if record.get('birthday'):
            values['birthday'] = record['birthday']

        department_id, missing = self.resolve_m2o('hr.department', record.get('department_id'))
        if missing:
            return values, missing
        if department_id:
            values['department_id'] = department_id

        # The manager is nice-to-have, not required - a missing manager
        # link must never block the employee record itself.
        manager_id, _missing = self.resolve_m2o('hr.employee', record.get('parent_id'))
        if manager_id:
            values['parent_id'] = manager_id

        job = record.get('job_id')
        if job:
            job_id = self.resolve_by_name('hr.job', job[1], '_job_cache')
            if job_id:
                values['job_id'] = job_id

        calendar = record.get('resource_calendar_id')
        if calendar:
            calendar_id = self.resolve_by_name('resource.calendar', calendar[1], '_calendar_cache')
            if calendar_id:
                values['resource_calendar_id'] = calendar_id

        return values, missing


@register_migrator('stock_warehouse')
class StockWarehouseMigrator(BaseMigrator):
    source_model = 'stock.warehouse'
    target_model = 'stock.warehouse'
    source_fields = ['name', 'code']
    matching_keys = ['code', 'name']

    def transform(self, record, is_update=False):
        return {
            'name': record.get('name') or 'Unknown',
            'code': record.get('code') or False,
        }, None


@register_migrator('stock_location')
class StockLocationMigrator(BaseMigrator):
    """Master data only (warehouses/locations) - never quantities/on-hand
    stock. Two Odoo databases essentially never agree on real-world stock
    levels, and copying quant data blindly risks silently wrong inventory
    valuation; the doc's own guidance (and this deployment's choice) is
    that opening balances belong in a separate, deliberate Inventory
    Adjustment done by the business, not an automated field copy."""
    source_model = 'stock.location'
    target_model = 'stock.location'
    source_fields = ['name', 'location_id', 'usage', 'warehouse_id', 'active']
    matching_keys = []  # find_business_match is overridden below (scoped to parent)
    self_referential_fields = ['location_id']
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {'name': record.get('name') or 'Unknown'}
        if record.get('usage') in ('supplier', 'view', 'internal', 'customer',
                                    'inventory', 'procurement', 'production', 'transit'):
            values['usage'] = record['usage']

        parent_id, missing = self.resolve_m2o('stock.location', record.get('location_id'))
        if missing:
            return values, missing
        if parent_id:
            values['location_id'] = parent_id

        warehouse_id, missing = self.resolve_m2o('stock.warehouse', record.get('warehouse_id'))
        if missing:
            # A location's warehouse link is informational - do not block
            # on it (e.g. Odoo's own top-level "Physical Locations" has none).
            missing = None
        if warehouse_id:
            values['warehouse_id'] = warehouse_id

        return values, missing

    def find_business_match(self, values):
        """A location name ("Stock", "Input", "Output"...) is only
        meaningful within its parent location - never match on name alone."""
        Target = self.env[self.target_model]
        name = values.get('name')
        if not name:
            return Target.browse(), None, None
        domain = [('name', '=', name), ('location_id', '=', values.get('location_id') or False)]
        found = Target.search(domain, limit=2)
        if len(found) != 1:
            return Target.browse(), None, None
        if self._is_target_claimed(found.id):
            return Target.browse(), None, (
                'Business-key match on "name+parent" ignored - already linked to '
                'a different source record; created as a new record instead.')
        return found, 'name+parent', None


@register_migrator('project_project')
class ProjectMigrator(BaseMigrator):
    source_model = 'project.project'
    target_model = 'project.project'
    source_fields = ['name', 'partner_id', 'user_id', 'active']
    matching_keys = ['name']
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        values = {
            'name': record.get('name') or 'Unknown',
            'active': record.get('active', True),
        }
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            missing = None  # nice-to-have, not required
        if partner_id:
            values['partner_id'] = partner_id

        user_id = self.resolve_user(record.get('user_id'))
        if user_id:
            values['user_id'] = user_id

        return values, missing


@register_migrator('project_task')
class ProjectTaskMigrator(BaseMigrator):
    source_model = 'project.task'
    target_model = 'project.task'
    source_fields = [
        'name', 'project_id', 'partner_id', 'user_ids', 'user_id', 'stage_id',
        'date_deadline', 'priority', 'description', 'tag_ids', 'active',
    ]
    matching_keys = []
    domain = [('active', 'in', [True, False])]

    def transform(self, record, is_update=False):
        project_id, missing = self.resolve_m2o('project.project', record.get('project_id'))
        if missing:
            return {}, missing
        values = {
            'project_id': project_id,
            'name': record.get('name') or 'Unknown',
            'date_deadline': record.get('date_deadline') or False,
            'priority': record.get('priority') or '0',
            'description': record.get('description') or False,
            'active': record.get('active', True),
        }

        partner_id, p_missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if partner_id:
            values['partner_id'] = partner_id

        assignee_ids = self._resolve_assignees(record)
        if assignee_ids:
            values['user_ids'] = [(6, 0, assignee_ids)]

        stage = record.get('stage_id')
        if stage:
            stage_id = self.resolve_by_name('project.task.type', stage[1], '_stage_cache')
            if stage_id:
                values['stage_id'] = stage_id

        tag_ids = record.get('tag_ids')
        if tag_ids:
            values['tag_ids'] = [(6, 0, self.resolve_or_create_m2m_by_name(
                'project.tags', tag_ids, 'project.tags', '_tag_cache'))]

        return values, missing

    def _resolve_assignees(self, record):
        # Odoo moved from a single 'user_id' to multi-assignee 'user_ids'
        # around v17 - support whichever the source actually has.
        raw_ids = record.get('user_ids')
        if not raw_ids and record.get('user_id'):
            value = record['user_id']
            raw_ids = [value[0] if isinstance(value, (list, tuple)) else value]
        resolved = []
        for uid in (raw_ids or []):
            target_id = self.resolve_user(uid)
            if target_id:
                resolved.append(target_id)
        return resolved


class _OrderMigratorMixin:
    """Shared line-building and header-resolution logic for sale.order and
    purchase.order.

    Lines are only (re)written the first time an order is created - once a
    mapping exists, later runs only update header fields. Re-syncing lines
    on an order that may already have invoices/receipts against it is out
    of scope for V1 (documented limitation).
    """
    line_model = None
    line_field = None
    qty_field = None
    line_source_fields = []
    tax_field = None       # 'tax_id' on sale.order.line, 'taxes_id' on purchase.order.line
    tax_type_use = None    # 'sale' or 'purchase' - scopes account.tax matching

    def _build_lines(self, order_record):
        line_ids = order_record.get(self.line_field) or []
        if not line_ids:
            return [], None
        wanted_fields = list(self.line_source_fields)
        if self.tax_field:
            wanted_fields.append(self.tax_field)
        available_fields = self._filter_available_fields(
            self.line_model, wanted_fields, '_line_fields_cache')
        lines = self.adapter.read(self.line_model, line_ids, fields=available_fields)
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
            if line.get('sequence') is not None:
                line_vals['sequence'] = line['sequence']
            if product_id:
                line_vals['product_id'] = product_id
            uom = line.get('product_uom')
            if uom:
                uom_id = self.resolve_by_name('uom.uom', uom[1], '_uom_cache')
                if uom_id:
                    line_vals['product_uom'] = uom_id
            if self.tax_field and line.get(self.tax_field):
                tax_ids = self.resolve_taxes(line[self.tax_field], self.tax_type_use)
                if tax_ids:
                    line_vals[self.tax_field] = [(6, 0, tax_ids)]
            self._sanitize_values(line_vals, model=self.line_model)
            commands.append((0, 0, line_vals))
        return commands, None

    def _resolve_currency(self, currency_field):
        if not currency_field:
            return False
        source_id = currency_field[0]
        cache = getattr(self, '_currency_cache', None)
        if cache is None:
            cache = {}
            self._currency_cache = cache
        if source_id in cache:
            return cache[source_id]
        recs = self.adapter.read('res.currency', [source_id], fields=['name'])
        code = recs[0].get('name') if recs else None
        target_id = self.resolve_by_name('res.currency', code, '_currency_by_code_cache') if code else False
        cache[source_id] = target_id
        return target_id


@register_migrator('sale_order')
class SaleOrderMigrator(_OrderMigratorMixin, BaseMigrator):
    source_model = 'sale.order'
    target_model = 'sale.order'
    source_fields = [
        'name', 'partner_id', 'date_order', 'client_order_ref', 'order_line',
        'state', 'validity_date', 'commitment_date', 'payment_term_id',
        'pricelist_id', 'currency_id', 'user_id', 'team_id', 'note',
    ]
    matching_keys = []
    line_model = 'sale.order.line'
    line_field = 'order_line'
    qty_field = 'product_uom_qty'
    line_source_fields = ['product_id', 'name', 'product_uom_qty', 'product_uom',
                           'price_unit', 'discount', 'sequence']
    tax_field = 'tax_id'
    tax_type_use = 'sale'

    # 'done' (locked) was folded into state='sale' + a separate 'locked'
    # boolean on newer Odoo versions - map it down rather than risk an
    # invalid-selection-value error on the target.
    _STATE_MAP = {'draft': 'draft', 'sent': 'sent', 'sale': 'sale',
                  'done': 'sale', 'cancel': 'cancel'}

    def transform(self, record, is_update=False):
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            return {}, missing
        values = {
            'partner_id': partner_id,
            'date_order': record.get('date_order') or False,
            'client_order_ref': record.get('client_order_ref') or False,
            'validity_date': record.get('validity_date') or False,
            'commitment_date': record.get('commitment_date') or False,
            'note': record.get('note') or False,
        }

        state = self._STATE_MAP.get(record.get('state'))
        if state:
            values['state'] = state

        payment_term = record.get('payment_term_id')
        if payment_term:
            pt_id = self.resolve_by_name('account.payment.term', payment_term[1], '_payment_term_cache')
            if pt_id:
                values['payment_term_id'] = pt_id

        pricelist = record.get('pricelist_id')
        if pricelist:
            pl_id = self.resolve_by_name('product.pricelist', pricelist[1], '_pricelist_cache')
            if pl_id:
                values['pricelist_id'] = pl_id

        currency_id = self._resolve_currency(record.get('currency_id'))
        if currency_id:
            values['currency_id'] = currency_id

        user_id = self.resolve_user(record.get('user_id'))
        if user_id:
            values['user_id'] = user_id

        team = record.get('team_id')
        if team:
            team_id = self.resolve_by_name('crm.team', team[1], '_team_cache')
            if team_id:
                values['team_id'] = team_id

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
    source_fields = [
        'name', 'partner_id', 'date_order', 'partner_ref', 'order_line',
        'state', 'date_planned', 'payment_term_id', 'currency_id',
        'user_id', 'notes',
    ]
    matching_keys = []
    line_model = 'purchase.order.line'
    line_field = 'order_line'
    qty_field = 'product_qty'
    line_source_fields = ['product_id', 'name', 'product_qty', 'product_uom',
                           'price_unit', 'discount', 'sequence']
    tax_field = 'taxes_id'
    tax_type_use = 'purchase'

    # 'done'/'purchase' variants across versions all collapse onto the
    # confirmed state; only copy values the target is known to accept.
    _STATE_MAP = {'draft': 'draft', 'sent': 'sent', 'to approve': 'to approve',
                  'purchase': 'purchase', 'done': 'purchase', 'cancel': 'cancel'}

    def transform(self, record, is_update=False):
        partner_id, missing = self.resolve_m2o('res.partner', record.get('partner_id'))
        if missing:
            return {}, missing
        values = {
            'partner_id': partner_id,
            'date_order': record.get('date_order') or False,
            'partner_ref': record.get('partner_ref') or False,
            'date_planned': record.get('date_planned') or False,
            'notes': record.get('notes') or False,
        }

        state = self._STATE_MAP.get(record.get('state'))
        if state:
            values['state'] = state

        payment_term = record.get('payment_term_id')
        if payment_term:
            pt_id = self.resolve_by_name('account.payment.term', payment_term[1], '_payment_term_cache')
            if pt_id:
                values['payment_term_id'] = pt_id

        currency_id = self._resolve_currency(record.get('currency_id'))
        if currency_id:
            values['currency_id'] = currency_id

        user_id = self.resolve_user(record.get('user_id'))
        if user_id:
            values['user_id'] = user_id

        if not is_update:
            lines, missing = self._build_lines(record)
            if missing:
                return values, missing
            values['order_line'] = lines
        return values, None
