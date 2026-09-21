import xmlrpc.client
import logging

_logger = logging.getLogger(__name__)


class MigrationConnectionError(Exception):
    """Raised when a source Odoo database cannot be reached or authenticated."""
    pass


class BaseOdooAdapter:
    """Common interface every transport adapter must implement.

    Kept deliberately small (connect/get_version/fields_get/search/read/
    create/write) so the migration engine never talks to xmlrpc or a future
    JSON-2 API directly - it only depends on this interface.
    """

    def __init__(self, url, database, username, password):
        self.url = (url or '').rstrip('/')
        self.database = database
        self.username = username
        self.password = password
        self.uid = None

    def connect(self):
        raise NotImplementedError

    def get_version(self):
        raise NotImplementedError

    def fields_get(self, model, attributes=None):
        raise NotImplementedError

    def search(self, model, domain, offset=0, limit=None, order=None):
        raise NotImplementedError

    def read(self, model, ids, fields=None):
        raise NotImplementedError

    def search_read(self, model, domain, fields=None, offset=0, limit=None, order=None):
        raise NotImplementedError

    def create(self, model, values):
        raise NotImplementedError

    def write(self, model, ids, values):
        raise NotImplementedError


class XmlRpcAdapter(BaseOdooAdapter):
    """Transport adapter for Odoo's standard XML-RPC external API.

    Works against Odoo 16, 17, 18 and 19 sources - this is the only
    transport the Odoo 19 target variant of this module needs.
    """

    def __init__(self, url, database, username, password):
        super().__init__(url, database, username, password)
        self._common = None
        self._models = None

    def connect(self):
        try:
            self._common = xmlrpc.client.ServerProxy(
                '%s/xmlrpc/2/common' % self.url, allow_none=True)
            self.uid = self._common.authenticate(
                self.database, self.username, self.password, {})
        except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError, OSError) as exc:
            raise MigrationConnectionError(
                'Could not reach %s: %s' % (self.url, exc)) from exc

        if not self.uid:
            raise MigrationConnectionError(
                'Authentication failed for user "%s" on database "%s"'
                % (self.username, self.database))

        self._models = xmlrpc.client.ServerProxy(
            '%s/xmlrpc/2/object' % self.url, allow_none=True)
        return self.uid

    def _ensure_connected(self):
        if not self.uid or self._models is None:
            self.connect()

    def _execute(self, model, method, *args, **kwargs):
        self._ensure_connected()
        try:
            return self._models.execute_kw(
                self.database, self.uid, self.password,
                model, method, list(args), kwargs)
        except xmlrpc.client.Fault as exc:
            raise MigrationConnectionError(
                '%s.%s failed on %s: %s' % (model, method, self.url, exc)) from exc

    def get_version(self):
        self._ensure_connected()
        info = self._common.version()
        return info.get('server_version')

    def fields_get(self, model, attributes=None):
        attributes = attributes or ['string', 'type', 'relation', 'required', 'selection']
        return self._execute(model, 'fields_get', [], {'attributes': attributes})

    def search(self, model, domain, offset=0, limit=None, order=None):
        kwargs = {'offset': offset}
        if limit:
            kwargs['limit'] = limit
        if order:
            kwargs['order'] = order
        return self._execute(model, 'search', domain, **kwargs)

    def read(self, model, ids, fields=None):
        kwargs = {'fields': fields} if fields else {}
        return self._execute(model, 'read', ids, **kwargs)

    def search_read(self, model, domain, fields=None, offset=0, limit=None, order=None):
        kwargs = {'offset': offset}
        if fields:
            kwargs['fields'] = fields
        if limit:
            kwargs['limit'] = limit
        if order:
            kwargs['order'] = order
        return self._execute(model, 'search_read', domain, **kwargs)

    def create(self, model, values):
        return self._execute(model, 'create', [values])

    def write(self, model, ids, values):
        return self._execute(model, 'write', ids, values)


def get_adapter(transport, url, database, username, password):
    """Factory: resolves a transport name to a concrete adapter instance."""
    if transport == 'xmlrpc':
        return XmlRpcAdapter(url, database, username, password)
    raise MigrationConnectionError('Unsupported transport: %s' % transport)
