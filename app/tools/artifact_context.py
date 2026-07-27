from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactPayload:
    data: bytes
    filename: str
    mime_type: str


class ArtifactContext:
    def __init__(self):
        self._pending: ArtifactPayload | None = None

    def set(self, *, data: bytes, filename: str, mime_type: str) -> None:
        self._pending = ArtifactPayload(data=data, filename=filename, mime_type=mime_type)

    def pop(self) -> ArtifactPayload | None:
        payload = self._pending
        self._pending = None
        return payload
