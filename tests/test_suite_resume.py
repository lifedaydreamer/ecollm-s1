import hashlib
import json
import sys
from pathlib import Path
import pytest
from ml.run_clause_suite import main
from tradepilot.clause_task import score


def fixture_suite(tmp_path, monkeypatch):
    data = tmp_path / 'data'; previous = tmp_path / 'previous'; output = tmp_path / 'new'
    data.mkdir(); (previous / 'old-validation').mkdir(parents=True)
    row = {'id': 'validation-only', 'input': {'category': 'Insurance', 'text': 'Maintain insurance.'},
           'target': {'status': 'found', 'evidence': ['Maintain insurance.']}}
    prediction = {'id': row['id'], 'schema_valid': True, 'grounded': True, 'output': row['target']}
    (data / 'validation.jsonl').write_text(json.dumps(row) + '\n')
    (data / 'manifest.json').write_text('{}')
    config = {'seed': 42}; config_path = tmp_path / 'config.json'; config_path.write_text(json.dumps(config))
    plan = {'candidate_a': config, 'data_manifest_sha256': hashlib.sha256((data / 'manifest.json').read_bytes()).hexdigest()}
    (previous / 'preregistered-plan.json').write_text(json.dumps(plan))
    for name, guided in [('v1-basic-validation', False), ('v1-guided-validation', True)]:
        path = previous / 'old-validation'
        (path / (name + '-predictions.json')).write_text(json.dumps([prediction]))
        (path / (name + '-metrics.json')).write_text(json.dumps({**score([row], [prediction]), 'batch_size': 4, 'with_definitions': guided}))
    monkeypatch.setattr('tradepilot.artifacts.verify_clause_adapter', lambda _: None)
    monkeypatch.setattr(sys, 'argv', ['suite', '--model', str(tmp_path / 'base'), '--data', str(data),
        '--output', str(output), '--config', str(config_path), '--old-adapter', str(tmp_path / 'old-adapter'), '--baseline-suite', str(previous)])
    return data, previous, output


class TrainingReached(Exception):
    pass


def test_resume_rechecks_scores_and_only_reuses_validation(tmp_path, monkeypatch):
    data, previous, output = fixture_suite(tmp_path, monkeypatch)
    def stop_before_training(command, **kwargs):
        assert command[1].endswith('train_clause_pilot.py')
        raise TrainingReached
    monkeypatch.setattr('ml.run_clause_suite.subprocess.run', stop_before_training)
    # There is deliberately no confirmation file: resuming baselines must not read it.
    with pytest.raises(TrainingReached): main()
    audit = json.loads((output / 'reused-baselines.json').read_text())
    assert audit['validation_only'] and audit['fresh_confirmation_still_sealed']
    assert len(audit['files_sha256']) == 4
    assert not (output / 'confirmation').exists()


def test_resume_rejects_tampered_baseline_scores(tmp_path, monkeypatch):
    data, previous, output = fixture_suite(tmp_path, monkeypatch)
    path = previous / 'old-validation/v1-basic-validation-metrics.json'
    metric = json.loads(path.read_text()); metric['mean_evidence_token_f1'] = 0.5
    path.write_text(json.dumps(metric))
    with pytest.raises(ValueError, match='do not match'): main()
    assert not (output / 'candidate-a').exists()


def test_shutdown_wait_does_not_treat_zombies_or_reused_pids_as_live(monkeypatch):
    from ml import run_remote_pilot
    from types import SimpleNamespace
    def status(state, start):
        values = ['0'] * 20; values[0] = state; values[19] = start
        return '42 (own worker) ' + ' '.join(values)
    record = {'text': status('S', '123')}
    monkeypatch.setattr(run_remote_pilot, 'Path', lambda _: SimpleNamespace(read_text=lambda: record['text']))
    assert run_remote_pilot.process_alive(42, '123')
    record['text'] = status('Z', '123')
    assert not run_remote_pilot.process_alive(42, '123')
    record['text'] = status('S', '456')
    assert not run_remote_pilot.process_alive(42, '123')
