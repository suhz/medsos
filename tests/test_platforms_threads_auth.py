from unittest.mock import MagicMock, patch

import pytest

from medsos.platforms.threads.auth import ThreadsAuth, ThreadsAuthError


def test_authorize_url_contains_required_params():
    a = ThreadsAuth(app_id="APP", app_secret="SEC", callback_base="https://x.test")
    url = a.authorize_url(state="abc123", scopes=["threads_basic", "threads_content_publish"])
    assert "client_id=APP" in url
    assert "redirect_uri=https%3A%2F%2Fx.test%2Faccounts%2Fcallback" in url
    assert "scope=threads_basic%2Cthreads_content_publish" in url
    assert "response_type=code" in url
    assert "state=abc123" in url


def test_callback_url_default():
    a = ThreadsAuth(app_id="A", app_secret="S", callback_base="https://x.test/")
    assert a.callback_url() == "https://x.test/accounts/callback"


def test_exchange_code_raises_structured_error_on_http_failure():
    a = ThreadsAuth(app_id="A", app_secret="S", callback_base="https://x.test")
    bad = MagicMock()
    bad.ok = False
    bad.status_code = 400
    bad.text = '{"error":"redirect_uri mismatch"}'

    with patch("medsos.platforms.threads.auth.requests.post", return_value=bad):
        with pytest.raises(ThreadsAuthError) as ei:
            a.exchange_code("CODE")

    err = ei.value
    assert err.status_code == 400
    assert err.redirect_uri == "https://x.test/accounts/callback"
    assert "redirect_uri mismatch" in err.body
    msg = err.public_message()
    assert "token exchange failed: HTTP 400" in msg
    assert "redirect_uri=https://x.test/accounts/callback" in msg
    assert "redirect_uri mismatch" in msg


def test_exchange_code_promotes_to_long_lived_token():
    a = ThreadsAuth(app_id="A", app_secret="S", callback_base="https://x.test")
    short = MagicMock()
    short.ok = True
    short.json.return_value = {"access_token": "short", "expires_in": 3600}
    long = MagicMock()
    long.ok = True
    long.json.return_value = {"access_token": "long", "expires_in": 5184000}

    with patch("medsos.platforms.threads.auth.requests.post", return_value=short), \
         patch("medsos.platforms.threads.auth.requests.get", return_value=long):
        out = a.exchange_code("CODE")

    assert out["access_token"] == "long"
    assert out["expires_at"] > 0
