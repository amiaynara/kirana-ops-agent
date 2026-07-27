import asyncio
from datetime import datetime

from claude_agent_sdk import tool

PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_analytics_tools(analytics_service, artifact_context):
    @tool(
        "get_daily_summary",
        "Get today's (or a given date's) sales summary: total sales, tax collected, "
        "cash vs UPI vs card split, and top-selling items.",
        {
            "type": "object",
            "properties": {
                "target_date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
            },
            "required": [],
        },
    )
    async def get_daily_summary(args):
        target_date = _parse_date(args["target_date"]) if args.get("target_date") else None
        summary = await asyncio.to_thread(analytics_service.get_daily_summary, target_date=target_date)
        lines = [
            f"Date: {summary['date']}",
            f"Bills: {summary['bill_count']}",
            f"Total sales: Rs {summary['total_sales']}",
            f"Tax collected: Rs {summary['tax_collected']}",
        ]
        if summary["by_payment_mode"]:
            lines.append("By payment mode: " + ", ".join(
                f"{mode}=Rs {amt}" for mode, amt in summary["by_payment_mode"].items()
            ))
        if summary["top_items"]:
            lines.append("Top items: " + ", ".join(
                f"{name} ({qty})" for name, qty in summary["top_items"]
            ))
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "render_analysis_deck",
        "Generate a PPTX sales-analysis deck (with real charts) for a date range: sales trend, "
        "top items, GST collected, and stock health.",
        {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    )
    async def render_analysis_deck(args):
        start = _parse_date(args["start_date"])
        end = _parse_date(args["end_date"])
        pptx_bytes = await asyncio.to_thread(
            analytics_service.render_analysis_deck, start_date=start, end_date=end,
        )
        artifact_context.set(
            data=pptx_bytes, filename=f"analysis-{start}-to-{end}.pptx", mime_type=PPTX_MIME_TYPE,
        )
        return {"content": [{"type": "text",
                              "text": f"Generated the sales analysis deck for {start} to {end}."}]}

    return [get_daily_summary, render_analysis_deck]
