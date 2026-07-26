import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    create_sdk_mcp_server,
)

from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.services.khata import KhataService
from app.services.preferences import PreferencesService
from app.tools.billing_tools import UpdateContext, build_billing_tools
from app.tools.inventory_tools import build_inventory_tools
from app.tools.khata_tools import build_khata_tools
from app.tools.preferences_tools import build_preferences_tools

REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_SYSTEM_PROMPT = (
    "You are Kirana, the conversational assistant running an Indian kirana (supermarket) store "
    "from Telegram, on behalf of the shop owner. The owner talks to you in plain, terse English, "
    "shopkeeper-style. You act on their behalf using your tools -- never invent a price, GST "
    "rate, or stock level; always look it up. Amounts are in Indian Rupees. When a request is "
    "genuinely ambiguous (e.g. which SKU, which unit), ask a clarifying question instead of "
    "guessing. When a tool refuses an action, relay the reason to the owner plainly -- do not "
    "try to work around it."
)


def _format_preferences(prefs: dict) -> str:
    if not prefs:
        return "No standing preferences set yet."
    lines = "\n".join(f"- {k}: {v}" for k, v in prefs.items())
    return f"Standing owner preferences (apply these silently unless the owner says otherwise):\n{lines}"


class AgentSession:
    def __init__(self, *, chat_id: str, session_factory, model: str | None = None):
        self.chat_id = chat_id
        inventory = InventoryService(session_factory)
        billing = BillingService(session_factory)
        khata = KhataService(session_factory)
        preferences = PreferencesService(session_factory)

        self._update_context = UpdateContext()
        self._all_tools = (
            build_inventory_tools(inventory)
            + build_billing_tools(billing, inventory, chat_id, self._update_context)
            + build_khata_tools(khata)
            + build_preferences_tools(preferences)
        )
        server = create_sdk_mcp_server(name="kirana", version="1.0.0", tools=self._all_tools)

        prefs_block = _format_preferences(preferences.get_all_preferences())
        system_prompt = f"{BASE_SYSTEM_PROMPT}\n\n{prefs_block}"

        self._options = ClaudeAgentOptions(
            tools=["Skill"],
            mcp_servers={"kirana": server},
            strict_mcp_config=True,
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            skills="all",
            cwd=str(REPO_ROOT),
            system_prompt=system_prompt,
            max_turns=20,
            model=model,
        )
        self._client = ClaudeSDKClient(options=self._options)
        self._connected = False
        self._lock = asyncio.Lock()

    async def send(self, text: str, *, update_id: str) -> str:
        async with self._lock:
            try:
                self._update_context.current_update_id = update_id
                if not self._connected:
                    await self._client.connect()
                    self._connected = True
                await self._client.query(text)
                result_text = ""
                async for message in self._client.receive_response():
                    if isinstance(message, ResultMessage):
                        if message.is_error:
                            print(
                                f"[agent_session] chat_id={self.chat_id} "
                                f"update_id={update_id} dead turn "
                                f"subtype={message.subtype} errors={message.errors}",
                                file=sys.stderr,
                            )
                            result_text = (
                                "Something went wrong on my end and I couldn't finish "
                                "that -- please check 'show the bill' or 'how much "
                                "stock is left' before trying again."
                            )
                        else:
                            result_text = message.result or ""
                return result_text
            finally:
                self._update_context.current_update_id = None

    async def close(self):
        if self._connected:
            await self._client.disconnect()
            self._connected = False
