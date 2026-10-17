import gmail_client


def test_compose_html_body_escapes_and_appends_signature():
    result = gmail_client.compose_html_body("Hi <there>\nSecond line & more", "<p>Sig</p>")
    assert "&lt;there&gt;" in result
    assert "&amp; more" in result
    assert "<br>\n" in result
    assert result.endswith("<p>Sig</p>")


def test_compose_html_body_with_empty_signature():
    result = gmail_client.compose_html_body("Hi", "")
    assert "Hi" in result
    assert result.endswith("")  # no trailing signature markup appended beyond the empty string
