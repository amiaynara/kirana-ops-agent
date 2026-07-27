import asyncio
from datetime import datetime

from claude_agent_sdk import tool

PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _parse_date(value: str, *, field_name):
    """Parse a date string from tool args. Returns (date, None) on success,
    or (None, error_result_dict) on failure — the caller returns error_result_dict
    directly as the tool's result on failure."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, {
            "content": [{"type": "text",
                         "text": f"{field_name!r} must be a date in YYYY-MM-DD format, got {value!r}."}],
            "is_error": True,
        }
    return parsed, None


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
        target_date = None
        if args.get("target_date"):
            target_date, error = _parse_date(args["target_date"], field_name="target_date")
            if error is not None:
                return error
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
        "Generate a PPTX sales-analysis deck for a date range: chart slides for sales trend and "
        "top items, plus a text summary slide covering GST collected and stock health.",
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
        start, error = _parse_date(args["start_date"], field_name="start_date")
        if error is not None:
            return error
        end, error = _parse_date(args["end_date"], field_name="end_date")
        if error is not None:
            return error
        try:
            pptx_bytes = await asyncio.to_thread(
                analytics_service.render_analysis_deck, start_date=start, end_date=end,
            )
        except ValueError as exc:
            return {
                "content": [{"type": "text", "text": f"Refused: {exc}"}],
                "is_error": True,
            }
        artifact_context.set(
            data=pptx_bytes, filename=f"analysis-{start}-to-{end}.pptx", mime_type=PPTX_MIME_TYPE,
        )
        return {"content": [{"type": "text",
                              "text": f"Generated the sales analysis deck for {start} to {end}."}]}

    return [get_daily_summary, render_analysis_deck]
