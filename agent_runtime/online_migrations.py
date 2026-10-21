"""Fail-closed MySQL online DDL. Never silently fall back to table copying."""
from django.db import migrations, NotSupportedError


def online_sql(editor, sql):
    with editor.connection.cursor() as cursor:
        cursor.execute('SELECT @@SESSION.lock_wait_timeout')
        previous = cursor.fetchone()[0]
        cursor.execute('SET SESSION lock_wait_timeout = 1')
        try:
            editor.execute(sql)
        finally:
            cursor.execute('SET SESSION lock_wait_timeout = %s', [previous])


class KeepOnlineChanges:
    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == 'mysql':
            raise NotSupportedError('keep additive schema during application rollback')
        return super().database_backwards(app_label, schema_editor, from_state, to_state)


class OnlineNullableField(KeepOnlineChanges, migrations.AddField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'mysql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        model = to_state.apps.get_model(app_label, self.model_name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        field = model._meta.get_field(self.name)
        if not field.null or field.unique or field.db_index or getattr(field, 'db_constraint', False):
            raise NotSupportedError('online column stage must be nullable and have no index or constraint')
        quote = schema_editor.quote_name
        online_sql(schema_editor, f'ALTER TABLE {quote(model._meta.db_table)} ADD COLUMN '
                   f'{quote(field.column)} {field.db_type(schema_editor.connection)} NULL, ALGORITHM=INSTANT')


class OnlineCreateModel(KeepOnlineChanges, migrations.CreateModel):
    """Create the new ownership table with all FKs in its initial CREATE TABLE."""
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'mysql':
            return super().database_forwards(app_label, schema_editor, from_state, to_state)
        model = to_state.apps.get_model(app_label, self.name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        offset = len(schema_editor.deferred_sql)
        sql, params = schema_editor.table_sql(model)
        deferred = schema_editor.deferred_sql[offset:]
        del schema_editor.deferred_sql[offset:]
        prefix = 'ALTER TABLE ' + schema_editor.quote_name(model._meta.db_table) + ' ADD '
        constraints = []
        for statement in deferred:
            value = str(statement)
            if not value.startswith(prefix):
                raise NotSupportedError('unexpected deferred ownership DDL')
            constraints.append(value[len(prefix):])
        end = sql.rfind(')')
        if end < 0 or params or len(constraints) != 2:
            raise NotSupportedError('ownership CREATE must contain both real foreign keys')
        sql = sql[:end] + ', ' + ', '.join(constraints) + sql[end:]
        online_sql(schema_editor, sql)
        for statement in schema_editor._model_indexes_sql(model):
            online_sql(schema_editor, statement)
