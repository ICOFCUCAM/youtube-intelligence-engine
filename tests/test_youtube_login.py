"""yt-youtube login: PKCE + loopback consent, simulated browser and token endpoint."""
import base64
import hashlib
import json
import os
import stat
import urllib.parse
import urllib.request

import pytest

from youtube_intelligence.integrations.youtube.auth import READ_ONLY_SCOPES, AuthError, Credentials
from youtube_intelligence.integrations.youtube.cli import main
from youtube_intelligence.integrations.youtube.login import (inside_git_worktree, login, pkce_pair,
                                                             read_token_file, save_token)

CLIENT = Credentials(client_id="cid.apps.googleusercontent.com", client_secret="csecret")
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def browser(code="4/fake-code", state=None, error=None, seen=None):
    """Stands in for the user's browser: inspects the consent URL, then hits the redirect."""
    def open_url(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        if seen is not None:
            seen.update(q)
        params = {"state": state if state is not None else q["state"]}
        params.update({"error": error} if error else {"code": code})
        NOPROXY.open(q["redirect_uri"] + "?" + urllib.parse.urlencode(params), timeout=5).read()
    return open_url


def token_endpoint(scope=" ".join(READ_ONLY_SCOPES), refresh=True, record=None):
    def transport(method, url, headers, body):
        form = dict(urllib.parse.parse_qsl(body.decode()))
        if record is not None:
            record.update(form)
        d = {"access_token": "ya29.x", "expires_in": 3599, "scope": scope}
        if refresh:
            d["refresh_token"] = "1//refresh"
        return 200, json.dumps(d).encode()
    return transport


def test_pkce_pair_follows_rfc7636():
    p = pkce_pair()
    assert 43 <= len(p["verifier"]) <= 128 and set(p["verifier"]) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    expect = base64.urlsafe_b64encode(hashlib.sha256(p["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert p["challenge"] == expect and "=" not in p["challenge"]
    assert pkce_pair()["verifier"] != p["verifier"]


def test_full_flow_requests_read_only_and_binds_pkce():
    seen, form = {}, {}
    tok = login(CLIENT, open_url=browser(seen=seen), transport=token_endpoint(record=form),
                timeout=10, announce=lambda m: None)
    assert tok["refresh_token"] == "1//refresh"
    assert seen["scope"].split() == list(READ_ONLY_SCOPES)
    assert seen["code_challenge_method"] == "S256" and seen["access_type"] == "offline"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert form["grant_type"] == "authorization_code" and form["code"] == "4/fake-code"
    assert form["redirect_uri"] == seen["redirect_uri"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == seen["code_challenge"]


def test_forged_state_is_rejected():
    with pytest.raises(AuthError, match="state mismatch"):
        login(CLIENT, open_url=browser(state="forged"), transport=token_endpoint(), timeout=10, announce=lambda m: None)


def test_user_denies_consent():
    with pytest.raises(AuthError, match="access_denied"):
        login(CLIENT, open_url=browser(error="access_denied"), transport=token_endpoint(), timeout=10,
              announce=lambda m: None)


def test_write_scope_grant_is_discarded():
    with pytest.raises(AuthError, match="more than read-only"):
        login(CLIENT, open_url=browser(), transport=token_endpoint(scope=READ_ONLY_SCOPES[0] +
              " https://www.googleapis.com/auth/youtube"), timeout=10, announce=lambda m: None)


def test_missing_refresh_token_explained():
    with pytest.raises(AuthError, match="no refresh token"):
        login(CLIENT, open_url=browser(), transport=token_endpoint(refresh=False), timeout=10, announce=lambda m: None)


def test_timeout_and_missing_client():
    with pytest.raises(AuthError, match="within 0 s"):
        login(CLIENT, open_url=None, transport=token_endpoint(), timeout=0.2, announce=lambda m: None)
    with pytest.raises(AuthError, match="YT_OAUTH_CLIENT_ID"):
        login(Credentials(), announce=lambda m: None)


# --- token file ------------------------------------------------------------------------------------
def test_save_and_read_token_file(tmp_path):
    p = save_token({"refresh_token": "1//r", "scope": "x"}, str(tmp_path / "cfg" / "token.json"))
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert read_token_file(p) == "1//r"
    with pytest.raises(AuthError, match="exists"):
        save_token({"refresh_token": "2"}, p)
    save_token({"refresh_token": "2"}, p, force=True)
    assert read_token_file(p) == "2"


def test_refuses_path_inside_git_repo(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    target = str(tmp_path / "repo" / "secrets" / "token.json")
    assert inside_git_worktree(target)
    with pytest.raises(AuthError, match="git working tree"):
        save_token({"refresh_token": "r"}, target)


def test_refuses_group_readable_token_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text('{"refresh_token": "r"}')
    os.chmod(p, 0o644)
    with pytest.raises(AuthError, match="readable by other users"):
        read_token_file(str(p))


def test_env_token_file_feeds_credentials(tmp_path):
    p = save_token({"refresh_token": "1//fromfile"}, str(tmp_path / "t.json"))
    c = Credentials.from_env({"YT_OAUTH_TOKEN_FILE": p, "YT_OAUTH_CLIENT_ID": "a", "YT_OAUTH_CLIENT_SECRET": "b"})
    assert c.refresh_token == "1//fromfile" and c.has_oauth
    assert "1//fromfile" not in repr(c)


def test_cli_login_saves_and_never_prints_token(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("YT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YT_OAUTH_CLIENT_SECRET", "csecret")
    fake = lambda creds, **kw: {"refresh_token": "1//SECRET-REFRESH", "scope": " ".join(READ_ONLY_SCOPES)}
    out = tmp_path / "token.json"
    assert main(["login", "--save", str(out), "--no-browser"], login_fn=fake) == 0
    cap = capsys.readouterr()
    assert "1//SECRET-REFRESH" not in cap.out + cap.err and "YT_OAUTH_TOKEN_FILE" in cap.err
    assert read_token_file(str(out)) == "1//SECRET-REFRESH"


def test_cli_checks_save_path_before_sign_in(tmp_path, capsys, monkeypatch):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setenv("YT_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("YT_OAUTH_CLIENT_SECRET", "csecret")
    called = []
    fake = lambda creds, **kw: called.append(1) or {"refresh_token": "r"}
    assert main(["login", "--save", str(tmp_path / "repo" / "token.json")], login_fn=fake) == 1
    assert called == [] and "git working tree" in capsys.readouterr().err
    existing = tmp_path / "t.json"
    existing.write_text("{}")
    assert main(["login", "--save", str(existing)], login_fn=fake) == 1 and called == []
