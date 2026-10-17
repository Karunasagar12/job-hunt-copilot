"""The CV writer must produce runnable data before scoring/rendering."""
import pytest

import generate


def test_writer_requests_only_complete_data_and_extracts_python(monkeypatch):
    captured = {}
    def response(skill, input_text, knowledge):
        captured['prompt'] = input_text
        return '```python\nJOB_COMPANY = "Example Oncology"\nJOB_TITLE = "Senior Data Scientist"\n```'
    monkeypatch.setattr(generate, 'call_llm', response)

    code = generate.call_cv_writer('Job description', 'eu', 'Verified facts', 'Fix previous claims')

    assert code.startswith('JOB_COMPANY =')
    assert 'OUTPUT CONTRACT' in captured['prompt']
    assert 'Do not include a walkthrough' in captured['prompt']
    assert 'Fix previous claims' in captured['prompt']


@pytest.mark.parametrize('raw', [
    "I'll work through the full pipeline step by step before generating the final data module.",
    '```python\nSUMMARY = "Truncated output',
    '',
])
def test_writer_rejects_walkthrough_truncation_and_empty_output(monkeypatch, raw):
    monkeypatch.setattr(generate, 'call_llm', lambda *args: raw)
    with pytest.raises(RuntimeError, match='CV writer returned'):
        generate.call_cv_writer('Job description', 'eu', 'Verified facts')


def test_writer_accepts_valid_unfenced_module(monkeypatch):
    monkeypatch.setattr(generate, 'call_llm', lambda *args: 'JOB_COMPANY = "Example Oncology"')
    assert generate.call_cv_writer('JD', 'eu', 'Facts') == 'JOB_COMPANY = "Example Oncology"'
