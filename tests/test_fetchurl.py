from server import fetchurl

HTML = """
<html><head>
<title>Fallback Title</title>
<meta property="og:title" content="Therme Vals" />
<meta property="og:description" content="Stone baths" />
<meta property="og:image" content="/img/cover.jpg" />
<meta property="og:site_name" content="ArchDaily" />
<link rel="canonical" href="https://example.com/therme" />
<link rel="alternate" type="application/json+oembed" href="/oembed?u=therme" />
</head><body></body></html>
"""


def test_parse_metadata_resolves_relative_urls():
    meta = fetchurl.parse_metadata(HTML, "https://example.com/page")
    assert meta["title"] == "Therme Vals"
    assert meta["description"] == "Stone baths"
    assert meta["image"] == "https://example.com/img/cover.jpg"
    assert meta["site_name"] == "ArchDaily"
    assert meta["canonical"] == "https://example.com/therme"
    assert meta["oembed_url"] == "https://example.com/oembed?u=therme"


def test_parse_metadata_title_fallback():
    meta = fetchurl.parse_metadata("<html><head><title>Only Title</title></head></html>", "https://x.com")
    assert meta["title"] == "Only Title"


def test_is_safe_url_rejects_local_and_private():
    assert fetchurl.is_safe_url("http://127.0.0.1/") is False
    assert fetchurl.is_safe_url("http://10.0.0.5/") is False
    assert fetchurl.is_safe_url("http://169.254.1.1/") is False
    assert fetchurl.is_safe_url("ftp://example.com/") is False
    assert fetchurl.is_safe_url("not a url") is False
