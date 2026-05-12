from aggregator.services.extraction import _extract_text


def test_extract_text_prefers_known_article_containers_over_navigation():
    html = """
    <html>
      <body>
        <nav>Home About Contact News Search Links</nav>
        <div class="v_news_content">
          <p>Primary article paragraph with enough useful text for extraction.</p>
          <p>Second paragraph describing a 2026 notice for students and teachers.</p>
        </div>
      </body>
    </html>
    """

    text = _extract_text(html)

    assert "Primary article paragraph" in text
    assert "Second paragraph" in text
    assert "Home About Contact" not in text
