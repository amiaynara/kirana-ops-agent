import asyncio
import uuid

from app.agent_session import AgentSession


class CLIChannel:
    def __init__(self, *, chat_id: str, session_factory, anthropic_api_key: str | None = None):
        self._session = AgentSession(
            chat_id=chat_id, session_factory=session_factory, anthropic_api_key=anthropic_api_key,
        )

    async def run(self):
        print("Kirana Ops Agent (CLI) -- type your message, or 'exit' to quit.")
        loop = asyncio.get_event_loop()
        try:
            while True:
                text = await loop.run_in_executor(None, input, "you> ")
                if text.strip().lower() in ("exit", "quit"):
                    break
                if not text.strip():
                    continue
                update_id = str(uuid.uuid4())
                reply = await self._session.send(text, update_id=update_id)
                print(f"kirana> {reply}")
        finally:
            await self._session.close()
