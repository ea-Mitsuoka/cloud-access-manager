import pytest
from app.iam_executor import IamExecutor

def test_normalize_action():
    assert IamExecutor._normalize_action("GRANT") == "GRANT"
    assert IamExecutor._normalize_action("grant") == "GRANT"
    assert IamExecutor._normalize_action("REVOKE") == "REVOKE"
    assert IamExecutor._normalize_action("revoke") == "REVOKE"
    assert IamExecutor._normalize_action("AnythingElse") == "GRANT"
