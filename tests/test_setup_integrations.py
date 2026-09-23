import stat

import pytest

from scripts.setup_integrations import update_env


def test_environment_update_preserves_settings_and_restricts_permissions(tmp_path):
    path = tmp_path / 'partshelf.env'
    path.write_text('# Existing deployment\nDATABASE_PATH=/var/lib/partshelf/db\nPUBLIC_URL=old\n')
    update_env(path, {'PUBLIC_URL': 'https://inventory.example.com', 'SMTP_PASSWORD': 'test"value\\end'})
    assert path.read_text() == '# Existing deployment\nDATABASE_PATH=/var/lib/partshelf/db\nPUBLIC_URL="https://inventory.example.com"\nSMTP_PASSWORD="test\\"value\\\\end"\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_suffix('.env.tmp').exists()


def test_invalid_environment_value_leaves_existing_file_unchanged(tmp_path):
    path = tmp_path / 'partshelf.env'
    path.write_text('PUBLIC_URL=original\n')
    with pytest.raises(ValueError):
        update_env(path, {'PUBLIC_URL': 'invalid\nINJECTED=1'})
    assert path.read_text() == 'PUBLIC_URL=original\n'
