---
name: analytics
description: Use whenever the owner asks about sales performance, wants a summary of today's/this week's business, or wants a proper analysis deck -- "today's sales?", "close the day", "make this week's sales analysis deck", "how are we doing".
---

# Analytics

Two different things, don't conflate them:

- **`get_daily_summary`** -- a quick text answer for "today's sales?" / "close the day": total
  sales, tax collected, cash/UPI/card split, and top items for one day (defaults to today if no
  date is given). Use this for a conversational check-in, not a document.
- **`render_analysis_deck`** -- a real PPTX deck for a date range: a daily-sales-trend line chart,
  a top-items bar chart, and a summary slide (total sales, GST collected, and which items are
  running low on stock). GST and stock health are reported as summary text on that last slide, not
  as separate charts -- don't tell the owner there's a "GST chart" or a "stock chart". Use this
  when the owner explicitly wants a presentation/deck, not just a quick number -- e.g. "make this
  week's sales analysis deck". Needs a `start_date` and `end_date` (YYYY-MM-DD); for "this week"
  work out the actual calendar dates from context rather than asking the owner to compute them.

Like the invoice PDF, once `render_analysis_deck` is called the file is delivered automatically by
the channel -- just confirm briefly what date range it covers.
