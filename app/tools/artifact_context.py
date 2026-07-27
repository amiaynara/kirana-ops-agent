from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactPayload:
    data: bytes
    filename: str
    mime_type: str


class ArtifactContext:
    def __init__(self):
        self._pending: list[ArtifactPayload] = []

    def set(self, *, data: bytes, filename: str, mime_type: str) -> None:
        self._pending.append(ArtifactPayload(data=data, filename=filename, mime_type=mime_type))

    def pop_all(self) -> list[ArtifactPayload]:
        payloads = self._pending
        self._pending = []
        return payloads
