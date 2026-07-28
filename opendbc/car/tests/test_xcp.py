import unittest

from opendbc.car.tests.mock_panda import MockPanda
from opendbc.car.xcp import CONNECT_MODE, COMMAND_CODE, GET_ID_REQUEST_TYPE, XcpClient, CommandResponseError, CommandTimeoutError

TX_ADDR = 0x7E0
RX_ADDR = 0x7E8
BUS = 2

# resource availability, comm mode basic, max CTO, max DTO (2 bytes), protocol version, transport version
CONNECT_RESP = b"\x1d\xc1\x08\x00\x08\x01\x01"


def responses(*payloads: bytes | tuple[bytes, ...]):
  """Responder that replies with a positive response for each successive request.

  A tuple replies to a single request with multiple messages, as used in block mode.
  """
  it = iter(payloads)

  def responder(addr, dat, bus):
    payload = next(it, None)
    if payload is None:
      return []
    frames = payload if isinstance(payload, tuple) else (payload,)
    return [(RX_ADDR, b"\xff" + f, BUS) for f in frames]
  return responder


class TestXcpClient(unittest.TestCase):
  def client(self, *payloads: bytes | tuple[bytes, ...], connect: bool = True, **kwargs) -> XcpClient:
    """Build a client, by default already connected with big endian byte order and block mode support."""
    self.panda = MockPanda(responses(*((CONNECT_RESP,) if connect else ()) + payloads))
    client = XcpClient(self.panda, TX_ADDR, RX_ADDR, bus=BUS, timeout=0.01, **kwargs)
    if connect:
      client.connect()
    return client

  def assertSent(self, cmd: int, dat: bytes, idx: int = -1):
    addr, tx_data, bus = self.panda.sent[idx]
    self.assertEqual((addr, bus), (TX_ADDR, BUS))
    self.assertEqual(tx_data, (bytes([cmd]) + dat).ljust(8, b"\x00"))

  # *** transport ***

  def test_padding(self):
    client = self.client(connect=False, pad=False)
    self.panda.queue_rx((RX_ADDR, b"\xff", BUS))
    client.disconnect()
    self.assertEqual(self.panda.sent[-1][1], bytes([COMMAND_CODE.DISCONNECT]))

  def test_clears_can_buffers_before_sending(self):
    self.client()
    self.assertEqual(self.panda.cleared, [BUS, 0xFFFF])

  def test_ignores_other_addresses_and_buses(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff" + CONNECT_RESP, BUS + 1),  # wrong bus
                        (RX_ADDR + 1, b"\xff" + CONNECT_RESP, BUS),  # wrong address
                        (RX_ADDR, b"\xff" + CONNECT_RESP, BUS))
    client.connect()

  def test_rx_buffer_overflow(self):
    client = self.client(connect=False)
    self.panda.queue_rx(*([(RX_ADDR + 2, b"\x00" * 8, BUS)] * 255 + [(RX_ADDR, b"\xff" + CONNECT_RESP, BUS)]))
    client.connect()

  def test_debug_logging(self):
    client = self.client(connect=False, debug=True)
    self.panda.queue_rx((RX_ADDR, b"\xff" + CONNECT_RESP, BUS))
    client.connect()

  def test_timeout(self):
    client = self.client(connect=False)
    with self.assertRaises(CommandTimeoutError):
      client.connect()

  def test_error_response(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xfe\x25\x00", BUS))
    with self.assertRaises(CommandResponseError) as cm:
      client.connect()
    self.assertEqual(cm.exception.return_code, 0x25)
    self.assertEqual(str(cm.exception), "0x25 - Access denied, Seed & Key is required b'\\x00'")

  def test_unknown_error_response(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xfe\xaa\x00", BUS))
    with self.assertRaises(CommandResponseError) as cm:
      client.connect()
    self.assertEqual(str(cm.exception), "0xaa - unknown error b'\\x00'")

  # *** commands ***

  def test_connect(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff" + CONNECT_RESP, BUS))
    ret = client.connect(CONNECT_MODE.USER_DEFINED)
    self.assertSent(COMMAND_CODE.CONNECT, b"\x01")
    self.assertEqual(ret, {
      "cal_support": True,
      "daq_support": True,
      "stim_support": True,
      "pgm_support": True,
      "byte_order": ">",
      "address_granularity": 1,
      "slave_block_mode": True,
      "optional": True,
      "max_cto": 8,
      "max_dto": 8,
      "protocol_version": 1,
      "transport_version": 1,
    })

  def test_connect_little_endian(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff\x00\x04\x08\x40\x00\x01\x01", BUS))
    ret = client.connect()
    self.assertSent(COMMAND_CODE.CONNECT, b"\x00")
    self.assertEqual(ret["byte_order"], "<")
    self.assertEqual(ret["max_dto"], 0x40)
    self.assertEqual(ret["address_granularity"], 4)
    self.assertFalse(any(ret[k] for k in ("cal_support", "daq_support", "stim_support", "pgm_support", "slave_block_mode", "optional")))

  def test_connect_bad_length(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff\x00\x00", BUS))
    with self.assertRaises(AssertionError):
      client.connect()

  def test_disconnect(self):
    client = self.client(b"")
    client.disconnect()
    self.assertSent(COMMAND_CODE.DISCONNECT, b"")

  def test_disconnect_bad_length(self):
    client = self.client(b"\x00")
    with self.assertRaises(AssertionError):
      client.disconnect()

  def test_get_id(self):
    client = self.client(b"\x00\x00\x00\x00\x00\x00\x10")
    ret = client.get_id(GET_ID_REQUEST_TYPE.ASAM_MC2_PATH)
    self.assertSent(COMMAND_CODE.GET_ID, b"\x02")
    self.assertEqual(ret, {"mode": 0, "length": 0x10, "identifier": None})
    with self.assertRaises(ValueError):
      client.get_id(256)

  def test_get_id_with_identifier(self):
    # only CAN FD (max CTO > 8) has room for the identifier in the response
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff\x1d\xc1\x40\x00\x40\x01\x01", BUS))
    client.connect()
    self.panda.queue_rx((RX_ADDR, b"\xff\x01\x00\x00\x00\x00\x00\x03abc", BUS))
    self.assertEqual(client.get_id()["identifier"], b"abc")

  def test_get_seed(self):
    client = self.client(b"\x04\xde\xad\xbe\xef\x00\x00")
    self.assertEqual(client.get_seed(1), b"\xde\xad\xbe\xef")
    self.assertSent(COMMAND_CODE.GET_SEED, b"\x00\x01")
    with self.assertRaises(ValueError):
      client.get_seed(256)

  def test_unlock(self):
    client = self.client(b"\x10")
    self.assertEqual(client.unlock(b"\x01\x02\x03"), b"\x10")
    self.assertSent(COMMAND_CODE.UNLOCK, b"\x03\x01\x02\x03")

  def test_set_mta(self):
    client = self.client(b"\x00")
    client.set_mta(0xDEADBEEF, addr_ext=2)
    self.assertSent(COMMAND_CODE.SET_MTA, b"\x00\x00\x02\xde\xad\xbe\xef")
    with self.assertRaises(ValueError):
      client.set_mta(0, addr_ext=256)

  def test_upload(self):
    client = self.client(b"\x01\x02\x03\x04\x05\x06\x07")
    self.assertEqual(client.upload(4), b"\x01\x02\x03\x04")
    self.assertSent(COMMAND_CODE.UPLOAD, b"\x04")
    with self.assertRaises(ValueError):
      client.upload(256)

  def test_upload_block_mode(self):
    # a response larger than max DTO is spread over multiple messages
    client = self.client((b"\x01\x02\x03\x04\x05\x06\x07", b"\x08\x09\x0a\x00\x00\x00\x00"))
    self.assertEqual(client.upload(10), bytes(range(1, 11)))

  def test_upload_without_block_mode(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff\x1d\x81\x08\x00\x08\x01\x01", BUS))
    client.connect()
    with self.assertRaises(ValueError):
      client.upload(10)

  def test_short_upload(self):
    client = self.client(b"\x01\x02\x03\x04\x05\x06\x07")
    self.assertEqual(client.short_upload(3, 1, 0x1234), b"\x01\x02\x03")
    self.assertSent(COMMAND_CODE.SHORT_UPLOAD, b"\x03\x00\x01\x00\x00\x12\x34")
    with self.assertRaises(ValueError):
      client.short_upload(7, 0, 0)
    with self.assertRaises(ValueError):
      client.short_upload(1, 256, 0)

  def test_download(self):
    client = self.client(b"\x00\x00\x00")
    client.download(b"\x01\x02")
    self.assertSent(COMMAND_CODE.DOWNLOAD, b"\x02\x01\x02")
    with self.assertRaises(ValueError):
      client.download(b"\x00" * 256)

  def test_download_without_block_mode(self):
    client = self.client(connect=False)
    self.panda.queue_rx((RX_ADDR, b"\xff\x1d\x81\x08\x00\x08\x01\x01", BUS))
    client.connect()
    with self.assertRaises(ValueError):
      client.download(b"\x00" * 7)


if __name__ == "__main__":
  unittest.main()
