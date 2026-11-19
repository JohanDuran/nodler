from nodler.github import is_rate_limited, status_query


def test_status_query_quotes_names_with_spaces():
    assert status_query(["Ready", "In Review", "Ready to merge"]) == 'status:Ready,"In Review","Ready to merge"'


def test_rate_limit_message_detected():
    assert is_rate_limited("gh: API rate limit already exceeded for user ID 1.")
    assert not is_rate_limited("Could not resolve to a Repository")
