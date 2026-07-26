import asyncio

from claude_agent_sdk import tool


def build_preferences_tools(preferences):
    @tool("set_preference",
          "Remember a standing owner preference (e.g. default payment mode, default brand for "
          "an item, shop name/GSTIN) so it silently applies in future chats too.",
          {"key": str, "value": str})
    async def set_preference(args):
        await asyncio.to_thread(preferences.set_preference, key=args["key"], value=args["value"])
        return {"content": [{"type": "text", "text": f"Got it, remembered {args['key']} = {args['value']}."}]}

    @tool("get_preference", "Look up a previously remembered owner preference by key.", {"key": str})
    async def get_preference(args):
        value = await asyncio.to_thread(preferences.get_preference, key=args["key"])
        if value is None:
            return {"content": [{"type": "text", "text": f"No preference set for {args['key']!r}."}]}
        return {"content": [{"type": "text", "text": f"{args['key']} = {value}"}]}

    return [set_preference, get_preference]
