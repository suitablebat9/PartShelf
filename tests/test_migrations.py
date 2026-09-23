import sqlite3
from inventory import SCHEMA, create_app


def test_upgrade_keeps_existing_data_and_unknown_purchase_quantity(tmp_path):
    path = tmp_path/'legacy.db'
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO components(name,name_id,code,stock,unit_price,attributes) VALUES('Old part','OLD','PART-SAVED',7,'0.125','legacy spec')")
        db.execute("INSERT INTO movements(component_id,delta,reason) VALUES(1,7,'Original')")
        db.commit()
    config = {'TESTING': True, 'DATA_DIR': tmp_path, 'DATABASE': str(path)}
    create_app(config)
    create_app(config)  # Migrations must be safe to rerun under multiple workers.
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT code,stock,unit_price,attributes,purchase_quantity FROM components').fetchone() == ('PART-SAVED',7,'0.125','legacy spec',None)
        assert db.execute('SELECT COUNT(*) FROM movements').fetchone()[0] == 1
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
