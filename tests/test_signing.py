from app.portal_client import sign


def test_signature_matches_independent_hmac():
    # Expected value produced separately with: openssl dgst -sha256 -hmac test-secret
    # over the text "GET\n/portal/export\npage=1\n1700000000".
    ts, sig = sign("GET", "/portal/export", "page=1", "test-secret", timestamp=1700000000)
    assert ts == "1700000000"
    assert sig == "b4b4d3dacaea949dfabeb63650cd8f500ebc3719cf8246de8306a2e31f18d4d6"


def test_message_order_matters():
    _, a = sign("GET", "/portal/export", "page=1", "s", timestamp=1)
    _, b = sign("GET", "page=1", "/portal/export", "s", timestamp=1)
    assert a != b
