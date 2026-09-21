import sqlite3

import pytest

from tiberium_ai.audit_store import (
    ANALYSIS_SCHEMA_VERSION,
    AuditRecord,
    SqliteAuditStore,
)

HASH_A = 'a' * 64
HASH_B = 'b' * 64
POLICY = 'static-audit-v1+rules:0f'


def record(**overrides):
    fields = dict(
        recorded_at='2026-09-21T00:00:00Z',
        project_id='parcimonia',
        policy_version=POLICY,
        content_hash=HASH_A,
        role='module',
        role_reason='module_default',
        band='noted',
        deficit=21.5,
        dimensions={'substance': 0.5},
        skipped=(),
        rule_counts={'rule.probe': 1},
        attribution={'substance': 1.0, 'rule_penalty': 0.0},
        findings_total=1,
        data_origin='measured',
    )
    fields.update(overrides)
    return AuditRecord(**fields)


def test_a_record_refuses_a_malformed_content_hash():
    with pytest.raises(ValueError):
        record(content_hash='zz')


def test_a_record_refuses_an_unknown_provenance():
    with pytest.raises(ValueError):
        record(data_origin='observed')


def test_only_an_undetermined_band_may_omit_the_deficit():
    undetermined = record(band='undetermined', deficit=None, dimensions={}, rule_counts={}, findings_total=0)
    assert undetermined.deficit is None
    assert undetermined.reusable is False
    with pytest.raises(ValueError):
        record(band='undetermined')
    with pytest.raises(ValueError):
        record(deficit=None)


def test_a_record_refuses_an_unknown_dimension_or_a_skipped_one():
    with pytest.raises(ValueError):
        record(dimensions={'vibe': 1.0})
    with pytest.raises(ValueError):
        record(skipped=('import_hygiene',))


def test_recording_the_same_verdict_twice_is_a_no_op():
    with SqliteAuditStore(':memory:') as store:
        assert store.record(record()) is True
        later = record(recorded_at='2026-09-22T00:00:00Z')
        assert store.record(later) is False
        assert store.count() == 1


def test_a_second_verdict_for_the_same_key_is_refused():
    with SqliteAuditStore(':memory:') as store:
        store.record(record())
        with pytest.raises(ValueError):
            store.record(record(band='critical', deficit=91.0))


def test_reuse_requires_the_same_policy_version_and_measured_provenance():
    with SqliteAuditStore(':memory:') as store:
        store.record(record())
        assert store.reuse(HASH_A, POLICY) is not None
        assert store.reuse(HASH_A, 'other-policy') is None
        assert store.reuse(HASH_B, POLICY) is None
        store.record(record(content_hash=HASH_B, data_origin='fixture'))
        assert store.reuse(HASH_B, POLICY) is None


def test_a_stored_verdict_keeps_the_source_out_of_the_store():
    with SqliteAuditStore(':memory:') as store:
        store.record(record())
        stored = store.reuse(HASH_A, POLICY)
        assert stored.dimensions == {'substance': 0.5}
        assert not hasattr(stored, 'source')
        assert not hasattr(stored, 'path')


def test_history_returns_every_policy_version_oldest_first():
    with SqliteAuditStore(':memory:') as store:
        store.record(record())
        store.record(record(policy_version='static-audit-v2+rules:11', deficit=30.0, band='noted'))
        history = store.history(HASH_A)
        assert [item.policy_version for item in history] == [POLICY, 'static-audit-v2+rules:11']


def test_export_writes_one_line_per_record_and_never_overwrites(tmp_path):
    with SqliteAuditStore(':memory:') as store:
        store.record(record())
        store.record(record(content_hash=HASH_B, deficit=30.0))
        target = tmp_path / 'records.jsonl'
        assert store.export_jsonl(target) == 2
        assert len(target.read_text(encoding='utf-8').strip().splitlines()) == 2
        with pytest.raises(FileExistsError):
            store.export_jsonl(target)


def test_the_store_never_creates_its_parent_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        SqliteAuditStore(tmp_path / 'missing' / 'audit.sqlite3')


def test_the_store_refuses_a_schema_version_it_does_not_understand(tmp_path):
    path = tmp_path / 'audit.sqlite3'
    connection = sqlite3.connect(str(path))
    connection.execute('PRAGMA user_version = 99')
    connection.commit()
    connection.close()

    with pytest.raises(ValueError):
        SqliteAuditStore(path)


def test_a_new_file_is_stamped_with_the_current_schema_version(tmp_path):
    path = tmp_path / 'audit.sqlite3'
    with SqliteAuditStore(path) as store:
        store.record(record())
    connection = sqlite3.connect(str(path))
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    connection.close()

    assert version == ANALYSIS_SCHEMA_VERSION == 1
    with SqliteAuditStore(path) as reopened:
        assert reopened.count() == 1
