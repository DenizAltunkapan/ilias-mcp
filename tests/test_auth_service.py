import requests

from services.auth_service import AuthService

LOGGED_IN_PAGE = """
<html><body>
  <a href="/logout.php?cmd=doLogout">Abmelden</a>
  <h1>Angemeldet</h1>
</body></html>
"""

LOGIN_PAGE = """
<html><body>
  <form action="/login.php?cmd=force_login">
    <input name="username"><input name="password" type="password">
    <input name="cmd[doStandardAuthentication]" value="Anmelden">
  </form>
</body></html>
"""


def _response(body: str, content_type: str = "text/html; charset=UTF-8"):
    resp = requests.Response()
    resp._content = body.encode()
    resp.headers["Content-Type"] = content_type
    return resp


def test_expired_session_page_is_recognised() -> None:
    # ILIAS answers an expired session with HTTP 200 and the login form.
    assert AuthService._looks_like_login_page(_response(LOGIN_PAGE)) is True


def test_authenticated_page_is_not_mistaken_for_login() -> None:
    assert AuthService._looks_like_login_page(_response(LOGGED_IN_PAGE)) is False


def test_binary_download_is_never_treated_as_login_page() -> None:
    # A PDF must not be decoded and sniffed for login markers.
    resp = _response("%PDF-1.7 nonsense", content_type="application/pdf")
    assert AuthService._looks_like_login_page(resp) is False
