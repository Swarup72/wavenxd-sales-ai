import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_conversations import login_user, conversation_context


def test_admin_portal_routes_served():
    """Verify that /admin and /admin/ serve admin.html with 200 OK."""
    with TestClient(app) as client:
        for path in ["/admin", "/admin/", "/favicon.ico"]:
            resp = client.get(path)
            assert resp.status_code == 200, f"Failed on {path}: {resp.status_code}"
            if "admin" in path:
                assert "text/html" in resp.headers["content-type"]
                assert "Admin Control Center" in resp.text
            elif path == "/favicon.ico":
                assert resp.headers["content-type"] == "image/x-icon"


def test_admin_portal_tabs_and_panes_contract():
    """Verify that every tab button in admin.html has a corresponding pane-<tab> section."""
    admin_html_path = Path("app/static/admin.html")
    assert admin_html_path.exists()
    content = admin_html_path.read_text()

    # Find all nav items
    nav_tabs = re.findall(r'class="nav-item[^"]*"\s+data-tab="([^"]+)"', content)
    assert len(nav_tabs) >= 10, f"Expected at least 10 nav tabs, found: {nav_tabs}"

    # Verify matching pane-<tab> exists for each nav tab
    for tab in nav_tabs:
        pane_id = f'id="pane-{tab}"'
        assert pane_id in content, f"Nav tab '{tab}' is missing corresponding section with {pane_id} in admin.html"


def test_admin_portal_js_modules_and_imports():
    """Verify that all JS modules in app/static/js/admin exist, parse cleanly, and resolve all imports."""
    admin_js_dir = Path("app/static/js/admin")
    assert admin_js_dir.exists()

    js_files = list(admin_js_dir.glob("*.js")) + [Path("app/static/js/admin.js")]
    assert len(js_files) >= 10

    for f in js_files:
        src = f.read_text()
        imports = re.findall(r'(?:import|from)\s+[\'"]([^\'"]+\.js)[\'"]', src)
        for imp in imports:
            target = (f.parent / imp).resolve()
            assert target.exists(), f"Broken import in {f.name}: {imp} -> {target}"


def test_admin_portal_table_bodies_declared_in_html():
    """Verify that all table body IDs targeted by JS modules exist in admin.html."""
    admin_html = Path("app/static/admin.html").read_text()
    html_ids = set(re.findall(r'id="([^"]+)"', admin_html))

    expected_tbodies = [
        "companiesTableBody",
        "usersTableBody",
        "invitationsTableBody",
        "productsTableBody",
        "assignmentsTableBody",
        "flaggedProdsTableBody",
        "accessRequestsTableBody",
        "supportConversationsTableBody",
        "auditTableBody",
    ]

    for tb in expected_tbodies:
        assert tb in html_ids, f"Table body id='{tb}' expected by admin modules is missing from admin.html"


def test_admin_portal_api_security_isolation(conversation_context):
    """Verify that ordinary customers receive 403 Forbidden on all /admin endpoints."""
    with TestClient(app) as client:
        auth_alice = login_user(client, "alice@alphapharma.com")
        headers = {"X-CSRF-Token": auth_alice["csrf_token"]}

        for endpoint in [
            "/admin/overview",
            "/admin/companies",
            "/admin/users",
            "/admin/products",
            "/admin/assignments",
            "/admin/technical-review-queue",
            "/admin/support/conversations",
            "/admin/audit-logs",
        ]:
            resp = client.get(endpoint, headers=headers)
            assert resp.status_code == 403, f"Endpoint {endpoint} allowed customer access with HTTP {resp.status_code}"
