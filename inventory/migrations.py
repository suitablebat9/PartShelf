"""Additive, transactional migrations; existing stock and identifiers stay intact."""

def migrate(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        columns = {r[1] for r in connection.execute('PRAGMA table_info(components)')}
        additions = {
            'purchase_pack': "TEXT NOT NULL DEFAULT '1'", 'purchase_quantity': 'TEXT', 'purchase_total': 'TEXT',
            'price_recorded': 'INTEGER NOT NULL DEFAULT 0',
            'price_mode': "TEXT NOT NULL DEFAULT 'unit'",
            'size': "TEXT NOT NULL DEFAULT ''", 'resistance': "TEXT NOT NULL DEFAULT ''",
            'capacitance': "TEXT NOT NULL DEFAULT ''", 'voltage': "TEXT NOT NULL DEFAULT ''",
            'tolerance': "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f'ALTER TABLE components ADD COLUMN {name} {definition}')
        if 'price_recorded' not in columns:
            connection.execute('UPDATE components SET price_recorded=1 WHERE CAST(unit_price AS REAL)>0')
        connection.execute('CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE)')
        connection.execute('CREATE TABLE IF NOT EXISTS component_tags(component_id INTEGER REFERENCES components(id) ON DELETE CASCADE, tag_id INTEGER REFERENCES tags(id), PRIMARY KEY(component_id,tag_id))')
        connection.execute('CREATE INDEX IF NOT EXISTS component_tags_tag ON component_tags(tag_id,component_id)')
        connection.execute('CREATE TABLE IF NOT EXISTS project_builds(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE, build_count INTEGER NOT NULL, parts TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, undone INTEGER NOT NULL DEFAULT 0)')
        connection.execute('CREATE TABLE IF NOT EXISTS workflow_previews(token TEXT PRIMARY KEY, actor TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, expires INTEGER NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS workspace_milestones(key TEXT PRIMARY KEY, completed INTEGER NOT NULL DEFAULT 1)')
        from .security_schema import migrate_security
        migrate_security(connection)
        from .drawers import migrate_drawers
        migrate_drawers(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
