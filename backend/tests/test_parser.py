import base64

from app.services.gmail.parser import MAX_BODY_CHARS, html_to_text, parse_message
from tests.fakes import gmail_message


def test_parses_headers_recipients_and_plain_body():
    raw = gmail_message(
        "m1",
        sender='"Aisha Rahman" <Aisha@Grab.com>',
        to="Me <me@example.com>, Team <team@example.com>",
        body="Hello &amp; welcome",
        extra_headers={"Reply-To": "jobs@grab.com", "List-Unsubscribe": "<mailto:u@grab.com>"},
    )
    raw["snippet"] = "Hello &amp; welcome"
    parsed = parse_message(raw)

    assert parsed.sender_name == "Aisha Rahman"
    assert parsed.sender_email == "aisha@grab.com"
    assert parsed.reply_to == "jobs@grab.com"
    assert [r["email"] for r in parsed.recipients] == ["me@example.com", "team@example.com"]
    assert parsed.snippet == "Hello & welcome"
    assert "UNREAD" in parsed.label_ids
    assert parsed.received_at.tzinfo is not None
    assert parsed.headers == {"list-unsubscribe": "<mailto:u@grab.com>"}


def test_html_only_body_is_reduced_to_text_without_scripts():
    raw = gmail_message(
        "m2",
        body="",
        html=(
            "<html><head><style>p{color:red}</style></head><body>"
            "<script>alert('x')</script><p>Your exam is booked.</p>"
            '<a href="https://www.pearsonvue.com/confirm">Details</a></body></html>'
        ),
    )
    parsed = parse_message(raw)

    assert "Your exam is booked." in parsed.body_text
    assert "alert" not in parsed.body_text
    assert "color" not in parsed.body_text
    assert parsed.link_domains == ["pearsonvue.com"]


def test_attachments_are_metadata_only():
    raw = gmail_message("m3", attachments=(("cv.pdf", "application/pdf", 1234),))
    parsed = parse_message(raw)
    assert parsed.attachments == [{"filename": "cv.pdf", "mime_type": "application/pdf", "size": 1234}]
    assert "cv.pdf" not in parsed.body_text


def test_decodes_declared_charset():
    raw = gmail_message("m4", body="")
    data = base64.urlsafe_b64encode("Café".encode("iso-8859-1")).decode()
    raw["payload"]["parts"] = [
        {
            "mimeType": "text/plain",
            "headers": [{"name": "Content-Type", "value": 'text/plain; charset="iso-8859-1"'}],
            "body": {"data": data},
        }
    ]
    assert parse_message(raw).body_text == "Café"


def test_long_bodies_are_truncated_and_flagged():
    parsed = parse_message(gmail_message("m5", body="x" * (MAX_BODY_CHARS + 10)))
    assert len(parsed.body_text) == MAX_BODY_CHARS
    assert parsed.body_truncated is True


def test_html_to_text_keeps_block_structure():
    text, links = html_to_text("<div>One</div><div>Two<br>Three</div>")
    assert [line for line in text.splitlines() if line] == ["One", "Two", "Three"]
    assert links == []
