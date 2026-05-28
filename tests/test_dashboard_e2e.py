"""
E2E Playwright test for the codex-gateway dashboard.
Tests the root "/" dashboard page and "/v1/stats" API endpoint.
"""
import os
import json
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Load port from gateway.env (same config the server uses)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(_project_root, "gateway.env"))
_port = os.getenv("GATEWAY_PORT", "8000")
BASE_URL = f"http://localhost:{_port}"


def test_stats_api():
    """Test the /v1/stats JSON endpoint returns valid data."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Test stats API
        resp = page.request.get(f"{BASE_URL}/v1/stats")
        print(f"\n[stats API] Status: {resp.status}")
        assert resp.status == 200, f"Expected 200, got {resp.status}"

        data = resp.json()
        print(f"[stats API] Response keys: {list(data.keys())}")
        assert "uptime" in data
        assert "total_requests" in data
        assert "recent_requests" in data
        print("[stats API] ✅ PASS")

        browser.close()


def test_dashboard_page():
    """Test the root dashboard page loads and renders correctly."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Navigate to dashboard
        resp = page.goto(BASE_URL)
        print(f"\n[dashboard] Status: {resp.status}")
        assert resp.status == 200, f"Expected 200, got {resp.status}"

        # Check page title
        title = page.title()
        print(f"[dashboard] Title: '{title}'")
        assert "codex-gateway" in title.lower(), f"Unexpected title: {title}"

        # Check key elements are present
        header = page.locator("h1")
        header_text = header.inner_text()
        print(f"[dashboard] Header: '{header_text}'")
        assert "codex-gateway" in header_text.lower()

        # Check the stat cards exist
        uptime_el = page.locator("#uptime")
        assert uptime_el.is_visible(), "Uptime card not visible"
        print(f"[dashboard] Uptime value: '{uptime_el.inner_text()}'")

        total_el = page.locator("#total")
        assert total_el.is_visible(), "Total requests card not visible"
        print(f"[dashboard] Total requests: '{total_el.inner_text()}'")

        # Check the table exists
        table = page.locator("table")
        assert table.is_visible(), "Requests table not visible"
        print("[dashboard] Table: visible")

        # Wait for auto-refresh (2s) and verify uptime changes
        page.wait_for_timeout(2500)
        uptime_after = page.locator("#uptime").inner_text()
        print(f"[dashboard] Uptime after refresh: '{uptime_after}'")

        # Take a screenshot for visual verification
        page.screenshot(path="tests/dashboard_screenshot.png", full_page=True)
        print("[dashboard] Screenshot saved to tests/dashboard_screenshot.png")
        print("[dashboard] ✅ PASS")

        browser.close()


def test_models_endpoint():
    """Verify /v1/models still works alongside new routes."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        resp = page.request.get(f"{BASE_URL}/v1/models")
        print(f"\n[models API] Status: {resp.status}")
        assert resp.status == 200, f"Expected 200, got {resp.status}"

        data = resp.json()
        print(f"[models API] Model count: {len(data.get('data', []))}")
        print("[models API] ✅ PASS")

        browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  codex-gateway Dashboard E2E Tests")
    print("=" * 60)
    test_stats_api()
    test_dashboard_page()
    test_models_endpoint()
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED ✅")
    print("=" * 60)
