"""Temporary CI-only network probe; remove this file after inspection."""

import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

import pytest


@pytest.mark.skipif(
    not (os.environ.get("GITHUB_ACTIONS") == "true"
         and sys.platform.startswith("linux")
         and sys.version_info[:2] == (3, 13)),
    reason="one-run HTTP check only on GitHub Actions Linux Python 3.13",
)
def test_mcpservers_listing_and_svg_are_retrievable():
    urls = [
        ("listing", "https://mcpservers.org/servers/tsyyan/buddie"),
        ("badge", "https://mcpservers.org/badge.svg"),
    ]
    for kind, url in urls:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(1024 * 1024)
            assert response.status == 200, (kind, response.status)
            if kind == "listing":
                assert b"buddie" in data.lower(), "listing did not mention buddie"
            else:
                root = ET.fromstring(data)
                assert root.tag.endswith("svg"), "badge content is not SVG"
