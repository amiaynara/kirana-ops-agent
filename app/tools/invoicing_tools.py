import asyncio

from claude_agent_sdk import tool

from app.errors import DomainError


def build_invoicing_tools(invoice_service, artifact_context):
    @tool(
        "render_invoice_pdf",
        "Generate a GST-correct PDF invoice for a finalized bill, given its bill id "
        "(the number shown when the bill was finalized, e.g. 'Bill #12').",
        {"bill_id": int},
    )
    async def render_invoice_pdf(args):
        try:
            pdf_bytes = await asyncio.to_thread(
                invoice_service.render_invoice_pdf, bill_id=args["bill_id"],
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        artifact_context.set(
            data=pdf_bytes, filename=f"invoice-{args['bill_id']}.pdf", mime_type="application/pdf",
        )
        return {"content": [{"type": "text",
                              "text": f"Generated the GST invoice PDF for Bill #{args['bill_id']}."}]}

    return [render_invoice_pdf]
