from app.tools.artifact_context import ArtifactContext


def test_pop_all_returns_empty_list_when_nothing_set():
    ctx = ArtifactContext()
    assert ctx.pop_all() == []


def test_set_then_pop_all_returns_payload_and_clears():
    ctx = ArtifactContext()
    ctx.set(data=b"hello", filename="a.pdf", mime_type="application/pdf")

    payloads = ctx.pop_all()

    assert len(payloads) == 1
    assert payloads[0].data == b"hello"
    assert payloads[0].filename == "a.pdf"
    assert payloads[0].mime_type == "application/pdf"
    assert ctx.pop_all() == []


def test_two_sets_before_pop_all_returns_both_payloads_in_order():
    # Regression test: a turn that generates two artifacts (e.g. two
    # render_invoice_pdf calls) must not have the first silently destroyed
    # by the second (verified live before this fix).
    ctx = ArtifactContext()
    ctx.set(data=b"first", filename="invoice-1.pdf", mime_type="application/pdf")
    ctx.set(data=b"second", filename="invoice-2.pdf", mime_type="application/pdf")

    payloads = ctx.pop_all()

    assert len(payloads) == 2
    assert payloads[0].filename == "invoice-1.pdf"
    assert payloads[0].data == b"first"
    assert payloads[1].filename == "invoice-2.pdf"
    assert payloads[1].data == b"second"
    # Drained -- a second call returns nothing left over.
    assert ctx.pop_all() == []
