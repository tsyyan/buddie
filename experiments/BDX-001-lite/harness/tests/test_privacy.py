import json
from bdx import cli


def test_redaction_is_not_bound_to_current_home():
    data = {'path': r'C:\Users\another-person\AppData\tmp',
            'posix': '/home/someone/private', 'email': 'person@example.net',
            'token': 'ghp_' + 'x' * 30}
    sanitized = cli.redact(json.dumps(data))
    for value in ['another-person', 'someone', 'person@example.net', 'ghp_' + 'x' * 30]:
        assert value not in sanitized
    assert json.loads(sanitized)


def test_redaction_handles_nested_json_and_generic_placeholders():
    raw = json.dumps({'event': json.dumps({'path': r'C:\Users\someone\secret'})})
    assert 'someone' not in cli.redact(raw)
    assert cli.redact('Users/user/example /home/runner/work') == 'Users/user/example /home/runner/work'
