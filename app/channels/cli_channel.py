import asyncio
import uuid
from pathlib import Path

from app.agent_session import AgentSession

ARTIFACTS_DIR = Path("data/artifacts")


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
                result = await self._session.send(text, update_id=update_id)
                print(f"kirana> {result.text}")
                if result.artifact is not None:
                    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                    saved_path = ARTIFACTS_DIR / result.artifact.filename
                    saved_path.write_bytes(result.artifact.data)
                    print(f"kirana> (saved to {saved_path})")
        finally:
            await self._session.close()
