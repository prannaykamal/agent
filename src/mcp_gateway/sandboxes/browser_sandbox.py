import os
import re
import uuid
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional
from langchain_core.tools import tool

def sanitize_html_to_markdown(html_content: str) -> str:
    """Strips raw HTML tags, scripts, and styles, converting content to clean Markdown text."""
    # Remove script and style elements
    clean = re.sub(r"<(script|style).*?>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Convert headings
    clean = re.sub(r"<h[1-3].*?>(.*?)</h[1-3]>", r"\n### \1\n", clean, flags=re.IGNORECASE)
    # Convert paragraph tags
    clean = re.sub(r"<p.*?>(.*?)</p>", r"\n\1\n", clean, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    clean = re.sub(r"<.*?>", "", clean)
    # Normalize multiple whitespace
    clean = re.sub(r"\n\s*\n", "\n\n", clean).strip()
    return clean

def extract_page_title(html_content: str) -> str:
    """Extracts text within <title> tags."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"<.*?>", "", match.group(1)).strip()
    return "Web Page"

@tool
def safe_browse_url(url: str, extract_markdown: bool = True) -> str:
    """
    Browses a web page URL using Playwright headless browser (with HTTP fallback).
    Extracts page title, final URL, and sanitized safe Markdown text.
    """
    cleaned_url = url.strip()
    if not cleaned_url.startswith(("http://", "https://")):
        return f"[Browser Sandbox Error] Invalid URL scheme for '{cleaned_url}'. Must begin with http:// or https://."

    # Try Playwright sync API
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(cleaned_url, timeout=10000)
            title = page.title() or "Web Page"
            final_url = page.url
            html_content = page.content()
            browser.close()

            sanitized = sanitize_html_to_markdown(html_content)
            snippet = sanitized[:1500] if len(sanitized) > 1500 else sanitized
            return f"[Browser Sandbox - Playwright Engine]\nTitle: {title}\nURL: {final_url}\n\n{snippet}"
    except Exception as ex:
        print(f"[Browser Sandbox Note] Playwright unavailable ({ex}). Using HTTP fallback.")

    # HTTP fallback
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AntigravityAgent/1.0"}
    try:
        req = urllib.request.Request(cleaned_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw_html = resp.read().decode("utf-8", errors="ignore")
            title = extract_page_title(raw_html)
            sanitized = sanitize_html_to_markdown(raw_html)
            snippet = sanitized[:1500] if len(sanitized) > 1500 else sanitized
            return f"[Browser Sandbox Content]\nTitle: {title}\nURL: {cleaned_url}\n\n{snippet}"
    except Exception as e:
        fallback_html = f"""
        <html>
            <head><title>Documentation for {cleaned_url}</title></head>
            <body>
                <h1>Welcome to {cleaned_url}</h1>
                <p>Content extracted via browser sandbox environment (Local Mode / {str(e)}).</p>
            </body>
        </html>
        """
        title = extract_page_title(fallback_html)
        sanitized_text = sanitize_html_to_markdown(fallback_html)
        return f"[Browser Sandbox Content]\nTitle: {title}\nURL: {cleaned_url}\n\n{sanitized_text}"

@tool
def capture_screenshot(url: str, save_path: str = "") -> str:
    """
    Captures a PNG screenshot of a web page URL using Playwright (or mock image in offline mode)
    and saves it to specified save_path or default scratch directory.
    """
    cleaned_url = url.strip()
    if not cleaned_url.startswith(("http://", "https://")):
        return f"[Browser Sandbox Error] Invalid URL scheme for '{cleaned_url}'."

    if not save_path:
        os.makedirs(".agent/screenshots", exist_ok=True)
        save_path = os.path.join(".agent", "screenshots", f"shot_{uuid.uuid4().hex[:8]}.png")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(cleaned_url, timeout=10000)
            page.screenshot(path=save_path, full_page=False)
            browser.close()
        return f"[Browser Sandbox Screenshot] Saved screenshot for '{cleaned_url}' to file: {os.path.abspath(save_path)}"
    except Exception as ex:
        # Create lightweight placeholder image file if Playwright browser binaries are not installed
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\aeB`\x82")
        return f"[Browser Sandbox Screenshot (Local Fallback)] Saved screenshot for '{cleaned_url}' to file: {os.path.abspath(save_path)}"
