import logging

from odoo import fields as odoo_fields

_logger = logging.getLogger(__name__)

# Coarse dependency order the doc calls out (section 13): parents before
# the documents that reference them.
MIGRATION_ORDER = [
    'res_partner',
    'product_category',
    'product_template',
    'crm_lead',
    'sale_order',
    'purchase_order',
]

MIGRATOR_REGISTRY = {}


def register_migrator(key):
    def _decorator(cls):
        cls.key = key
        MIGRATOR_REGISTRY[key] = cls
        return cls
    return _decorator


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


class BaseMigrator:
    """One migrator = one source model mapped onto one target model.

    Subclasses only need to declare source_model/target_model/source_fields/
    matching_keys and implement transform(). Everything else (batching,
    duplicate prevention, missing-dependency handling, dry-run, logging) is
    handled here so every migrator behaves consistently.
    """

    key = None
    source_model = None
    target_model = None
    source_fields = []
    matching_keys = []
    batch_size = 200
    domain = []
    # Fields that are a Many2one back onto this same target_model (e.g.
    # res.partner.parent_id, product.category.parent_id). A loose business-key
    # match (shared email/VAT between a company and its own contact) can
    # otherwise resolve one of these to the record's own id and Odoo's
    # recursion check would reject the write outright.
    self_referential_fields = []

    def __init__(self, env, connection, adapter, run):
        self.env = env
        self.connection = connection
        self.adapter = adapter
        self.run = run
        self.Mapping = env['migration.record.mapping']

    # ---- override in subclasses ----
    def get_domain(self):
        return list(self.domain)

    def transform(self, record, is_update=False):
        """Return (values_dict, missing_dependency) for one source record."""
        raise NotImplementedError

    def _after_write(self, record, target_id):
        """Hook for subclasses that need to register extra mappings
        (e.g. a product template's auto-created variant)."""

    # ---- relation helpers available to subclasses ----
    def resolve_m2o(self, source_comodel, value):
        if not value:
            return False, None
        source_id = value[0] if isinstance(value, (list, tuple)) else value
        target_id = self.Mapping.get_target_id(self.connection.id, source_comodel, source_id)
        if not target_id:
            return False, '%s:%s' % (source_comodel, source_id)
        return target_id, None

    def resolve_m2m(self, source_comodel, values):
        if not values:
            return [], None
        mapping = self.Mapping.get_target_ids(self.connection.id, source_comodel, values)
        missing = [v for v in values if v not in mapping]
        target_ids = list(mapping.values())
        missing_str = '%s:%s' % (source_comodel, ','.join(map(str, missing))) if missing else None
        return target_ids, missing_str

    def resolve_by_name(self, target_model, name, cache_attr):
        """Best-effort lookup for shared master data (UoM, stages...) that
        is expected to already exist on the target with the same name."""
        if not name:
            return False
        cache = getattr(self, cache_attr, None)
        if cache is None:
            cache = {}
            setattr(self, cache_attr, cache)
        if name in cache:
            return cache[name]
        rec = self.env[target_model].search([('name', '=', name)], limit=1)
        cache[name] = rec.id if rec else False
        return cache[name]

    def resolve_or_create_by_name(self, target_model, name, cache_attr, extra_vals=None):
        """Like resolve_by_name but creates a lightweight record when no
        match exists. Only safe for low-risk, no-side-effect models (tags,
        UTM sources/mediums) - never for structural/configured models."""
        if not name:
            return False
        cache = getattr(self, cache_attr, None)
        if cache is None:
            cache = {}
            setattr(self, cache_attr, cache)
        if name in cache:
            return cache[name]
        rec = self.env[target_model].search([('name', '=', name)], limit=1)
        if not rec:
            vals = {'name': name}
            if extra_vals:
                vals.update(extra_vals)
            rec = self.env[target_model].create(vals)
        cache[name] = rec.id
        return cache[name]

    def resolve_or_create_m2m_by_name(self, source_comodel, source_ids, target_model, cache_attr):
        """Many2many equivalent of resolve_or_create_by_name: fetches the
        names of the not-yet-cached source ids in one batch read, then
        find-or-creates matching target records."""
        if not source_ids:
            return []
        cache = getattr(self, cache_attr, None)
        if cache is None:
            cache = {}
            setattr(self, cache_attr, cache)

        uncached = [sid for sid in source_ids if sid not in cache]
        if uncached:
            for rec in self.adapter.read(source_comodel, uncached, fields=['name']):
                cache[rec['id']] = self.resolve_or_create_by_name(
                    target_model, rec.get('name'), cache_attr + '_by_name')

        return [cache[sid] for sid in source_ids if cache.get(sid)]

    def resolve_user(self, user_field, cache_attr='_user_login_cache'):
        """Resolve a Many2one res.users value by login (typically the
        user's email), which is far more reliable across databases than
        matching on display name."""
        if not user_field:
            return False
        source_user_id = user_field[0] if isinstance(user_field, (list, tuple)) else user_field
        cache = getattr(self, cache_attr, None)
        if cache is None:
            cache = {}
            setattr(self, cache_attr, cache)
        if source_user_id in cache:
            return cache[source_user_id]
        recs = self.adapter.read('res.users', [source_user_id], fields=['login'])
        login = recs[0].get('login') if recs else None
        target_id = False
        if login:
            target = self.env['res.users'].search([('login', '=', login)], limit=1)
            target_id = target.id if target else False
        cache[source_user_id] = target_id
        return target_id

    def find_business_match(self, values):
        """Returns (match_record_or_empty, matched_key_or_None, rejected_note_or_None).

        A business-key hit is only trusted if the matched target record is
        not already linked to a *different* source record in this same
        connection. Without this guard, several genuinely distinct source
        records that happen to share a value (e.g. several department
        contacts all using the company's generic email) would silently
        collapse onto a single target record instead of getting their own.
        """
        Target = self.env[self.target_model]
        for key in self.matching_keys:
            value = values.get(key)
            if not value:
                continue
            found = Target.search([(key, '=', value)], limit=2)
            if len(found) != 1:
                continue
            if self._is_target_claimed(found.id):
                return Target.browse(), None, (
                    'Business-key match on "%s" ignored - that target record is '
                    'already linked to a different source record; created as '
                    'a new record instead.' % key)
            return found, key, None
        return Target.browse(), None, None

    def _is_target_claimed(self, target_id):
        return bool(self.Mapping.search([
            ('connection_id', '=', self.connection.id),
            ('source_model', '=', self.source_model),
            ('target_model', '=', self.target_model),
            ('target_res_id', '=', target_id),
        ], limit=1))

    def _guard_self_reference(self, values, target_id):
        """Drop any self-referential field that would point a record at
        itself (e.g. a contact business-key-matched onto its own parent
        company). Returns the list of field names that were stripped."""
        stripped = []
        for field in self.self_referential_fields:
            if values.get(field) == target_id:
                values[field] = False
                stripped.append(field)
        return stripped

    # ---- main entry point ----
    def fetch_source_ids(self, only_source_ids=None):
        if only_source_ids is not None:
            return list(only_source_ids)
        return self.adapter.search(self.source_model, self.get_domain())

    def run_pass(self, only_source_ids=None):
        """Process one pass over the source ids. Returns the list of source
        ids that hit a missing dependency, so the runner can retry them
        once earlier migrators/passes have produced more mappings."""
        ids = self.fetch_source_ids(only_source_ids)
        pending = []

        for batch in chunked(ids, self.batch_size):
            records = self.adapter.read(self.source_model, batch, fields=self.source_fields)
            counts = {'created': 0, 'updated': 0, 'matched': 0, 'skipped': 0, 'error': 0}
            line_vals = []
            for record in records:
                source_id = record['id']
                try:
                    self._process_record(record, source_id, pending, counts, line_vals)
                except Exception as exc:  # noqa: BLE001 - one bad record must not abort the run
                    _logger.exception('Migration error on %s#%s', self.source_model, source_id)
                    counts['error'] += 1
                    line_vals.append(self._line_vals(source_id, 'error', str(exc)))
            self._flush(counts, line_vals)
        return pending

    def _process_record(self, record, source_id, pending, counts, line_vals):
        Target = self.env[self.target_model]
        existing_target_id = self.Mapping.get_target_id(
            self.connection.id, self.source_model, source_id)

        if existing_target_id:
            if self.run.mode in ('update_only', 'create_update'):
                values, missing = self.transform(record, is_update=True)
                if missing:
                    pending.append(source_id)
                    counts['error'] += 1
                    line_vals.append(self._line_vals(
                        source_id, 'error', 'Missing dependency', missing, existing_target_id))
                    return
                stripped = self._guard_self_reference(values, existing_target_id)
                note = ('Dropped self-referential field(s): %s' % ', '.join(stripped)
                        if stripped else None)
                if self.run.dry_run:
                    counts['updated'] += 1
                    line_vals.append(self._line_vals(
                        source_id, 'updated', note or 'Dry run - not written',
                        target_id=existing_target_id))
                    return
                Target.browse(existing_target_id).write(values)
                self._after_write(record, existing_target_id)
                counts['updated'] += 1
                line_vals.append(self._line_vals(source_id, 'updated', note, target_id=existing_target_id))
            else:
                counts['skipped'] += 1
                line_vals.append(self._line_vals(
                    source_id, 'skipped', 'Already migrated (create-only mode)',
                    target_id=existing_target_id))
            return

        values, missing = self.transform(record, is_update=False)
        if missing:
            pending.append(source_id)
            counts['error'] += 1
            line_vals.append(self._line_vals(source_id, 'error', 'Missing dependency', missing))
            return

        if self.run.mode == 'update_only':
            counts['skipped'] += 1
            line_vals.append(self._line_vals(
                source_id, 'skipped', 'No existing target record (update-only mode)'))
            return

        match, _matched_key, rejected_note = self.find_business_match(values)
        if match:
            note = None
            if not self.run.dry_run:
                self.Mapping.set_mapping(
                    self.connection.id, self.source_model, source_id, self.target_model, match.id)
                if self.run.mode == 'create_update':
                    stripped = self._guard_self_reference(values, match.id)
                    if stripped:
                        note = 'Dropped self-referential field(s): %s' % ', '.join(stripped)
                    match.write(values)
                self._after_write(record, match.id)
            counts['matched'] += 1
            line_vals.append(self._line_vals(source_id, 'matched', note, target_id=match.id))
            return

        if self.run.dry_run:
            counts['created'] += 1
            message = ('%s (dry run - not written)' % rejected_note) if rejected_note else 'Dry run - not written'
            line_vals.append(self._line_vals(source_id, 'created', message))
            return

        new_record = Target.create(values)
        self.Mapping.set_mapping(
            self.connection.id, self.source_model, source_id, self.target_model, new_record.id)
        self._after_write(record, new_record.id)
        counts['created'] += 1
        line_vals.append(self._line_vals(source_id, 'created', rejected_note, target_id=new_record.id))

    def _line_vals(self, source_id, state, message=None, missing_dependency=None, target_id=None):
        return {
            'run_id': self.run.id,
            'model_key': self.key,
            'source_model': self.source_model,
            'source_res_id': source_id,
            'target_res_id': target_id or 0,
            'state': state,
            'message': message,
            'missing_dependency': missing_dependency,
        }

    def _flush(self, counts, line_vals):
        if line_vals:
            self.env['migration.run.line'].create(line_vals)
        self.run.write({
            'created_count': self.run.created_count + counts['created'],
            'updated_count': self.run.updated_count + counts['updated'] + counts['matched'],
            'skipped_count': self.run.skipped_count + counts['skipped'],
            'error_count': self.run.error_count + counts['error'],
        })


class MigrationRunner:
    """Orchestrates one migration.run: connects once, then executes every
    requested migrator in dependency order with a bounded missing-dependency
    retry loop."""

    def __init__(self, env, run):
        self.env = env
        self.run = run
        connection = run.connection_id
        from .migration_adapter import get_adapter
        self.adapter = get_adapter(
            connection.transport, connection.url, connection.database,
            connection.username, connection.password)
        self.adapter.connect()

    def run_migrator(self, key, only_source_ids=None, max_passes=5):
        migrator_cls = MIGRATOR_REGISTRY.get(key)
        if not migrator_cls:
            raise ValueError('Unknown migrator: %s' % key)
        migrator = migrator_cls(self.env, self.run.connection_id, self.adapter, self.run)
        pending = only_source_ids
        for _pass in range(max_passes):
            previous_pending_count = len(pending) if pending else None
            pending = migrator.run_pass(only_source_ids=pending)
            if not pending:
                break
            if previous_pending_count is not None and len(pending) >= previous_pending_count:
                # No progress this pass (e.g. a genuinely missing target module) - stop retrying.
                break
        return pending

    def run_all(self):
        self.run.write({'state': 'running', 'start_date': odoo_fields.Datetime.now()})
        requested = [k.strip() for k in (self.run.model_keys or '').split(',') if k.strip()]
        ordered = [k for k in MIGRATION_ORDER if k in requested]
        ordered += [k for k in requested if k not in MIGRATION_ORDER]
        try:
            for key in ordered:
                self.run_migrator(key)
            self.run.write({'state': 'done', 'end_date': odoo_fields.Datetime.now()})
        except Exception:
            _logger.exception('Migration run %s failed', self.run.id)
            self.run.write({'state': 'error', 'end_date': odoo_fields.Datetime.now()})
            raise
