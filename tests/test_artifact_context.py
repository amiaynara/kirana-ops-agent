from app.tools.artifact_context import ArtifactContext


def test_pop_returns_none_when_nothing_set():
    ctx = ArtifactContext()
    assert ctx.pop() is None


def test_set_then_pop_returns_payload_and_clears():
    ctx = ArtifactContext()
    ctx.set(data=b"hello", filename="a.pdf", mime_type="application/pdf")

    payload = ctx.pop()

    assert payload.data == b"hello"
    assert payload.filename == "a.pdf"
    assert payload.mime_type == "application/pdf"
    assert ctx.pop() is None
