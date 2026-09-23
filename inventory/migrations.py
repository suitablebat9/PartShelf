"""Additive, transactional migrations; existing stock and identifiers stay intact."""

def migrate(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        columns = {r[1] for r in connection.execute('PRAGMA table_info(components)')}
        additions = {
            'purchase_quantity': 'TEXT', 'purchase_total': 'TEXT',
            'price_mode': "TEXT NOT NULL DEFAULT 'unit'",
            'size': "TEXT NOT NULL DEFAULT ''", 'resistance': "TEXT NOT NULL DEFAULT ''",
            'capacitance': "TEXT NOT NULL DEFAULT ''", 'voltage': "TEXT NOT NULL DEFAULT ''",
            'tolerance': "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f'ALTER TABLE components ADD COLUMN {name} {definition}')
        connection.execute('CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE)')
        connection.execute('CREATE TABLE IF NOT EXISTS component_tags(component_id INTEGER REFERENCES components(id) ON DELETE CASCADE, tag_id INTEGER REFERENCES tags(id), PRIMARY KEY(component_id,tag_id))')
        connection.execute('CREATE INDEX IF NOT EXISTS component_tags_tag ON component_tags(tag_id,component_id)')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
