from app.agent_session import AgentSession


class SessionRegistry:
    def __init__(self, *, session_factory, anthropic_api_key: str | None = None,
                 model: str | None = None):
        self._session_factory = session_factory
        self._anthropic_api_key = anthropic_api_key
        self._model = model
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, chat_id: str) -> AgentSession:
        session = self._sessions.get(chat_id)
        if session is None:
            session = AgentSession(
                chat_id=chat_id,
                session_factory=self._session_factory,
                model=self._model,
                anthropic_api_key=self._anthropic_api_key,
            )
            self._sessions[chat_id] = session
        return session

    def reset(self, chat_id: str) -> AgentSession | None:
        """Drop the cached session for chat_id, if any, and return it.

        Synchronous by design (matches get_or_create) -- does NOT call
        .close() on the popped session, since that requires an `await`.
        Closing the popped session, if needed, is the caller's job.
        """
        return self._sessions.pop(chat_id, None)

    async def close_all(self):
        for session in self._sessions.values():
            await session.close()
