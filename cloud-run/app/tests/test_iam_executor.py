import pytest
from app.iam_executor import IamExecutor


def test_normalize_action():
    assert IamExecutor._normalize_action("GRANT") == "GRANT"
    assert IamExecutor._normalize_action("grant") == "GRANT"
    assert IamExecutor._normalize_action("REVOKE") == "REVOKE"
    assert IamExecutor._normalize_action("revoke") == "REVOKE"
    assert IamExecutor._normalize_action("AnythingElse") == "GRANT"


def test_to_member():
    assert IamExecutor._to_member("user@example.com") == "user:user@example.com"
    assert (
        IamExecutor._to_member(
            "sa@project.iam.gserviceaccount.com"
        )
        == "serviceAccount:sa@project.iam.gserviceaccount.com"
    )
    assert (
        IamExecutor._to_member("group:group@example.com")
        == "group:group@example.com"
    )
    assert (
        IamExecutor._to_member(
            "serviceAccount:another-sa@project.iam.gserviceaccount.com"
        )
        == (
            "serviceAccount:another-sa@project.iam"
            ".gserviceaccount.com"
        )
    )


def test_parse_resource():
    assert IamExecutor._parse_resource("projects/my-project") == (
        "projects",
        "my-project",
    )
    assert IamExecutor._parse_resource("folders/12345") == ("folders", "12345")
    assert IamExecutor._parse_resource("organizations/67890") == (
        "organizations",
        "67890",
    )
    with pytest.raises(ValueError, match="unsupported resource_name format"):
        IamExecutor._parse_resource("buckets/my-bucket")
