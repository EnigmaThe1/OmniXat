"""Subject-scoped directory. The execute-only SQL capability is server internal."""
from uuid import UUID
from psycopg.rows import dict_row
from .postgres import _tenant_transaction


def list_workspaces(connection, verifier, token, *, after=None, limit=50):
    identity = verifier.verify(token)
    if 'records:read' not in identity.scopes:
        raise PermissionError('Record read scope required')
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('Invalid page size')
    cursor_id = UUID(str(after)) if after is not None else None
    with _tenant_transaction(connection, UUID(int=0), tables_required=('identities','memberships','tenants')):
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT has_schema_privilege('omnixat','USAGE,CREATE') AS direct_access")
            if cursor.fetchone()['direct_access']:
                raise PermissionError('Dedicated directory grants required')
            cursor.execute('SELECT * FROM omnixat_directory.list_workspaces(%s,%s,%s,%s,%s)',
                           (identity.issuer,identity.subject,identity.issued_at,cursor_id,limit+1))
            rows = cursor.fetchall()
            more = len(rows) > limit
            items = [dict(row,can_write=row['role'] in ('editor','owner') and 'records:write' in identity.scopes)
                     for row in rows[:limit]]
            return {'items':items,'next_cursor':str(items[-1]['id']) if more else None}
