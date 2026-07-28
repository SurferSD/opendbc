from collections.abc import Callable

CanFrame = tuple[int, bytes, int]
Responder = Callable[[int, bytes, int], list[CanFrame]]


class MockPanda:
  """Minimal stand-in for the panda API used by the CCP, XCP and ISO-TP clients."""

  def __init__(self, responder: Responder | None = None):
    self.responder = responder
    self.sent: list[CanFrame] = []
    self.cleared: list[int] = []
    self.rx: list[list[CanFrame]] = []

  def queue_rx(self, *frames: CanFrame) -> None:
    """Queue frames to all be returned by a single can_recv() call."""
    self.rx.append(list(frames))

  def can_clear(self, bus: int) -> None:
    self.cleared.append(bus)

  def can_send(self, addr: int, dat: bytes, bus: int) -> None:
    self.sent.append((addr, bytes(dat), bus))
    if self.responder is not None:
      # each response frame is returned by a separate can_recv() call
      self.rx.extend([frame] for frame in self.responder(addr, bytes(dat), bus))

  def can_send_many(self, msgs: list[CanFrame]) -> None:
    for addr, dat, bus in msgs:
      self.can_send(addr, dat, bus)

  def can_recv(self) -> list[CanFrame]:
    return self.rx.pop(0) if len(self.rx) else []
