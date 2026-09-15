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

    def find_business_match(self, values):
        Target = self.env[self.target_model]
        for key in self.matching_keys:
            value = values.get(key)
            if not value:
                continue
            found = Target.search([(key, '=', value)], limit=2)
            if len(found) == 1:
                return found
        return Target.browse()

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
                if self.run.dry_run:
                    counts['updated'] += 1
                    line_vals.append(self._line_vals(
                        source_id, 'updated', 'Dry run - not written', target_id=existing_target_id))
                    return
                Target.browse(existing_target_id).write(values)
                self._after_write(record, existing_target_id)
                counts['updated'] += 1
                line_vals.append(self._line_vals(source_id, 'updated', target_id=existing_target_id))
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

        match = self.find_business_match(values)
        if match:
            if not self.run.dry_run:
                self.Mapping.set_mapping(
                    self.connection.id, self.source_model, source_id, self.target_model, match.id)
                if self.run.mode == 'create_update':
                    match.write(values)
                self._after_write(record, match.id)
            counts['matched'] += 1
            line_vals.append(self._line_vals(source_id, 'matched', target_id=match.id))
            return

        if self.run.dry_run:
            counts['created'] += 1
            line_vals.append(self._line_vals(source_id, 'created', 'Dry run - not written'))
            return

        new_record = Target.create(values)
        self.Mapping.set_mapping(
            self.connection.id, self.source_model, source_id, self.target_model, new_record.id)
        self._after_write(record, new_record.id)
        counts['created'] += 1
        line_vals.append(self._line_vals(source_id, 'created', target_id=new_record.id))

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
