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


DEFAULT_MODEL = "claude-sonnet-5"


class AgentSession:
    def __init__(
        self,
        *,
        chat_id: str,
        session_factory,
        model: str | None = None,
        anthropic_api_key: str | None = None,
    ):
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

        options_kwargs = dict(
            tools=["Skill"],
            mcp_servers={"kirana": server},
            strict_mcp_config=True,
            permission_mode="bypassPermissions",
            # Explicit allowlist rather than "all": "all" pulls in every
            # Claude Code CLI-bundled skill (dataviz, update-config,
            # security-review, etc.) alongside our 4 project skills, which is
            # wasted context on every turn and can change silently on a CLI
            # version bump. NOTE: getting this list wrong fails open (a
            # missing project skill just becomes silently undiscoverable, no
            # crash) -- verify live after touching this.
            setting_sources=["project"],
            skills=["inventory", "billing", "khata", "preferences"],
            cwd=str(REPO_ROOT),
            system_prompt=system_prompt,
            max_turns=20,
            model=model or DEFAULT_MODEL,
        )
        # When we have an explicit API key (real deployment), pin auth to it
        # instead of relying on whatever `claude` CLI session happens to be
        # logged in on the host -- a Fly.io container won't have one at all.
        #
        # Dev-only limitation: when anthropic_api_key is NOT set (local dev,
        # relying on the ambient `claude` CLI login), this process still
        # inherits the host's global ~/.claude/CLAUDE.md and skills/settings
        # ambient config from the CLI session, even though setting_sources is
        # locked to ["project"] here -- that setting only controls what
        # *project*-level config is read, not the ambient CLI session's own
        # global config. A prior attempt to also isolate this via
        # CLAUDE_CONFIG_DIR broke auth entirely in this dev environment
        # (that's where credentials live), so it's left alone. This is an
        # accepted, documented dev-only gap: a real deployment sets
        # anthropic_api_key and therefore never depends on an ambient CLI
        # session in the first place.
        if anthropic_api_key:
            options_kwargs["env"] = {"ANTHROPIC_API_KEY": anthropic_api_key}

        self._options = ClaudeAgentOptions(**options_kwargs)
        self._client = ClaudeSDKClient(options=self._options)
        self._connected = False
        self._lock = asyncio.Lock()

    async def send(self, text: str, *, update_id: str) -> str:
        stripped = text.strip()
        if stripped.startswith("/"):
            if stripped.lower() == "/new":
                # A genuine mid-session reset. This does NOT go to the model
                # at all -- if it did, Claude Code's own CLI-level parser
                # would intercept it as an internal slash command (it wipes
                # the conversation and returns '' rather than replying).
                # Reuse the existing options object: its system prompt
                # (with preferences baked in at __init__ time) is still
                # valid for a mid-session reset. A fresh preferences READ
                # would need a brand-new AgentSession, which is the channel
                # layer's job, not this method's.
                async with self._lock:
                    await self.close()
                    self._client = ClaudeSDKClient(options=self._options)
                    self._connected = False
                return "Started a fresh conversation."
            # Any other leading-"/" text (an owner reflexively typing
            # "/help", a Telegram-style command, etc.) must NOT be passed to
            # `query()` as-is -- Claude Code's CLI-level slash-command parser
            # intercepts it before the model ever sees it (verified live:
            # "/context" returned an internal diagnostics dump, not a chat
            # reply). Escape it as ordinary literal text instead.
            text = f"(the owner typed this literal message, it is not a command): {text}"

        async with self._lock:
            try:
                self._update_context.current_update_id = update_id
                try:
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
                                    f"subtype={message.subtype} errors={message.errors} "
                                    f"result={message.result!r} "
                                    f"terminal_reason={message.terminal_reason!r}",
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
                except Exception:
                    # Whatever failed -- connect(), query(), or
                    # receive_response() -- the client may now be in an
                    # unusable state. Don't leave `_connected` stuck True:
                    # that would make every future send() assume the client
                    # still works and never retry connect().
                    self._connected = False
                    raise
            finally:
                self._update_context.current_update_id = None

    async def close(self):
        if self._connected:
            await self._client.disconnect()
            self._connected = False
