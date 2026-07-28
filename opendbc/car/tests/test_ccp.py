import struct
import unittest

from opendbc.car.ccp import BYTE_ORDER, COMMAND_CODE, CcpClient, CommandCounterError, CommandResponseError, CommandTimeoutError
from opendbc.car.tests.mock_panda import MockPanda

TX_ADDR = 0x700
RX_ADDR = 0x701
BUS = 1


def ack(payload: bytes = b"", err: int = 0x00, pid: int = 0xFF, counter: int | None = None):
  """Responder that replies to every command request object with a data transmission object."""
  def responder(addr, dat, bus):
    ctr = dat[1] if counter is None else counter
    return [(RX_ADDR, (bytes([pid, err, ctr]) + payload).ljust(8, b"\x00"), BUS)]
  return responder


def acks(*payloads: bytes):
  """Responder that replies with a different payload for each successive request."""
  it = iter(payloads)

  def responder(addr, dat, bus):
    return [(RX_ADDR, (bytes([0xFF, 0x00, dat[1]]) + next(it)).ljust(8, b"\x00"), BUS)]
  return responder


class TestCcpClient(unittest.TestCase):
  def client(self, responder=None, **kwargs) -> CcpClient:
    self.panda = MockPanda(responder)
    return CcpClient(self.panda, TX_ADDR, RX_ADDR, bus=BUS, **kwargs)

  def assertSent(self, cmd: int, dat: bytes, idx: int = -1):
    addr, tx_data, bus = self.panda.sent[idx]
    self.assertEqual((addr, bus), (TX_ADDR, BUS))
    self.assertEqual(len(tx_data), 8)
    self.assertEqual(tx_data[0], cmd)
    self.assertEqual(tx_data[2:], dat.ljust(6, b"\x00"))

  # *** transport ***

  def test_command_counter_increments_and_wraps(self):
    client = self.client(ack())
    for i in range(3):
      client.select_calibration_page()
      self.assertEqual(self.panda.sent[i][1][1], i)

    client._command_counter = 0xFE
    client.select_calibration_page()
    client.select_calibration_page()
    self.assertEqual(self.panda.sent[-2][1][1], 0xFF)
    self.assertEqual(self.panda.sent[-1][1][1], 0x00)

  def test_clears_can_buffers_before_sending(self):
    client = self.client(ack())
    client.select_calibration_page()
    self.assertEqual(self.panda.cleared, [BUS, 0xFFFF])

  def test_ignores_other_addresses_and_buses(self):
    client = self.client()
    self.panda.queue_rx((RX_ADDR, b"\xff\x00\x00\x01\x02\x03\x04\x05", BUS + 1),  # wrong bus
                        (RX_ADDR + 1, b"\xff\x00\x00\x01\x02\x03\x04\x05", BUS),  # wrong address
                        (RX_ADDR, b"\xff\x00\x00\x0a\x0b\x0c\x0d\x0e", BUS))
    self.assertEqual(client.upload(5), b"\x0a\x0b\x0c\x0d\x0e")

  def test_timeout(self):
    client = self.client()
    with self.assertRaises(CommandTimeoutError):
      client.select_calibration_page()

  def test_counter_mismatch(self):
    client = self.client(ack(counter=0x55))
    with self.assertRaises(CommandCounterError):
      client.select_calibration_page()

  def test_counter_not_checked_for_event_message(self):
    # pid 0xFE is an event message, which carries no command counter
    client = self.client(ack(pid=0xFE, counter=0x55))
    client.select_calibration_page()

  def test_error_response(self):
    client = self.client(ack(err=0x33))
    with self.assertRaises(CommandResponseError) as cm:
      client.select_calibration_page()
    self.assertEqual(cm.exception.return_code, 0x33)
    self.assertEqual(str(cm.exception), "0x33 - access denied")

  def test_unknown_error_response(self):
    client = self.client(ack(err=0xAB))
    with self.assertRaises(CommandResponseError) as cm:
      client.select_calibration_page()
    self.assertEqual(str(cm.exception), "0xab - unknown error")

  def test_busy_response_is_retried(self):
    # 0x10 - 0x12 mean the slave is busy, the client should keep waiting for a real response
    client = self.client()
    self.panda.queue_rx((RX_ADDR, b"\xff\x10\x00" + b"\x00" * 5, BUS))
    self.panda.queue_rx((RX_ADDR, b"\xff\x11\x00" + b"\x00" * 5, BUS))
    self.panda.queue_rx((RX_ADDR, b"\xff\x00\x00\x01\x02\x03\x04\x05", BUS))
    self.assertEqual(client.upload(5), b"\x01\x02\x03\x04\x05")

  def test_rx_buffer_overflow(self):
    client = self.client()
    self.panda.queue_rx(*([(RX_ADDR + 2, b"\x00" * 8, BUS)] * 255 + [(RX_ADDR, b"\xff\x00\x00\x01\x02\x03\x04\x05", BUS)]))
    self.assertEqual(client.upload(5), b"\x01\x02\x03\x04\x05")

  def test_debug_logging(self):
    client = self.client(debug=True)
    self.panda.queue_rx((RX_ADDR, b"\xff\x10\x00" + b"\x00" * 5, BUS))
    self.panda.queue_rx((RX_ADDR, b"\xff\x00\x00\x01\x02\x03\x04\x05", BUS))
    self.assertEqual(client.upload(5), b"\x01\x02\x03\x04\x05")

  def test_data_transmission_object(self):
    # DAQ messages have the packet ID in the first byte, the rest is data
    client = self.client()
    self.panda.queue_rx((RX_ADDR, b"\x01\x02\x03\x04\x05\x06\x07\x08", BUS))
    self.assertEqual(client.upload(5), b"\x02\x03\x04\x05\x06")

  # *** commands ***

  def test_connect(self):
    client = self.client(ack())
    client.connect(0x1234)
    # station address is always little endian
    self.assertSent(COMMAND_CODE.CONNECT, b"\x34\x12")
    with self.assertRaises(ValueError):
      client.connect(65536)

  def test_exchange_station_ids(self):
    client = self.client(ack(b"\x04\x01\x02\x03\x00"))
    ret = client.exchange_station_ids(b"\xaa")
    self.assertSent(COMMAND_CODE.EXCHANGE_ID, b"\xaa")
    self.assertEqual((ret.id_length, ret.data_type, ret.available, ret.protected), (4, 1, 2, 3))

  def test_get_seed(self):
    client = self.client(ack(b"\x00\xde\xad\xbe\xef"))
    self.assertEqual(client.get_seed(0x03), b"\xde\xad\xbe\xef")
    self.assertSent(COMMAND_CODE.GET_SEED, b"\x03")
    with self.assertRaises(ValueError):
      client.get_seed(256)

  def test_unlock(self):
    client = self.client(ack(b"\x07"))
    self.assertEqual(client.unlock(b"\x01\x02\x03"), 0x07)
    self.assertSent(COMMAND_CODE.UNLOCK, b"\x01\x02\x03")
    with self.assertRaises(ValueError):
      client.unlock(b"\x00" * 7)

  def test_set_memory_transfer_address(self):
    client = self.client(ack())
    client.set_memory_transfer_address(1, 2, 0xDEADBEEF)
    self.assertSent(COMMAND_CODE.SET_MTA, b"\x01\x02\xde\xad\xbe\xef")
    with self.assertRaises(ValueError):
      client.set_memory_transfer_address(256, 0, 0)
    with self.assertRaises(ValueError):
      client.set_memory_transfer_address(0, 256, 0)

  def test_download(self):
    client = self.client(ack(b"\x00\x00\x00\x10\x00"))
    self.assertEqual(client.download(b"\x01\x02"), 0x1000)
    self.assertSent(COMMAND_CODE.DNLOAD, b"\x02\x01\x02")
    with self.assertRaises(ValueError):
      client.download(b"\x00" * 6)

  def test_download_6_bytes(self):
    client = self.client(ack(b"\x00\x00\x00\x10\x00"))
    self.assertEqual(client.download_6_bytes(b"\x01\x02\x03\x04\x05\x06"), 0x1000)
    self.assertSent(COMMAND_CODE.DNLOAD_6, b"\x01\x02\x03\x04\x05\x06")
    with self.assertRaises(ValueError):
      client.download_6_bytes(b"\x00" * 5)

  def test_upload(self):
    client = self.client(ack(b"\x01\x02\x03\x04\x05"))
    self.assertEqual(client.upload(3), b"\x01\x02\x03")
    self.assertSent(COMMAND_CODE.UPLOAD, b"\x03")
    with self.assertRaises(ValueError):
      client.upload(6)

  def test_short_upload(self):
    client = self.client(ack(b"\x01\x02\x03\x04\x05"))
    self.assertEqual(client.short_upload(2, 0x01, 0xDEADBEEF), b"\x01\x02")
    self.assertSent(COMMAND_CODE.SHORT_UP, b"\x02\x01\xde\xad\xbe\xef")
    with self.assertRaises(ValueError):
      client.short_upload(6, 0, 0)
    with self.assertRaises(ValueError):
      client.short_upload(1, 256, 0)

  def test_get_daq_list_size(self):
    client = self.client(ack(b"\x08\x0a\x00\x00\x00"))
    ret = client.get_daq_list_size(2, can_id=0x100)
    self.assertSent(COMMAND_CODE.GET_DAQ_SIZE, b"\x02\x00\x00\x00\x01\x00")
    self.assertEqual((ret.list_size, ret.first_pid), (8, 10))
    with self.assertRaises(ValueError):
      client.get_daq_list_size(256)

  def test_set_daq_list_pointer(self):
    client = self.client(ack())
    client.set_daq_list_pointer(1, 2, 3)
    self.assertSent(COMMAND_CODE.SET_DAQ_PTR, b"\x01\x02\x03")
    for args in ((256, 0, 0), (0, 256, 0), (0, 0, 256)):
      with self.assertRaises(ValueError):
        client.set_daq_list_pointer(*args)

  def test_write_daq_list_entry(self):
    client = self.client(ack())
    client.write_daq_list_entry(4, 0, 0x1234)
    self.assertSent(COMMAND_CODE.WRITE_DAQ, b"\x04\x00\x00\x00\x12\x34")
    with self.assertRaises(ValueError):
      client.write_daq_list_entry(256, 0, 0)
    with self.assertRaises(ValueError):
      client.write_daq_list_entry(0, 256, 0)

  def test_start_stop_transmission(self):
    client = self.client(ack())
    client.start_stop_transmission(1, 2, 3, 4, rate_prescaler=5)
    self.assertSent(COMMAND_CODE.START_STOP, b"\x01\x02\x03\x04\x00\x05")
    for args, kwargs in (((256, 0, 0, 0), {}), ((0, 256, 0, 0), {}), ((0, 0, 256, 0), {}),
                         ((0, 0, 0, 256), {}), ((0, 0, 0, 0), {"rate_prescaler": 65536})):
      with self.assertRaises(ValueError):
        client.start_stop_transmission(*args, **kwargs)

  def test_disconnect(self):
    client = self.client(ack())
    client.disconnect(0x1234)
    self.assertSent(COMMAND_CODE.DISCONNECT, b"\x01\x00\x34\x12")
    client.disconnect(0x1234, temporary=True)
    self.assertSent(COMMAND_CODE.DISCONNECT, b"\x00\x00\x34\x12")
    with self.assertRaises(ValueError):
      client.disconnect(65536)

  def test_session_status(self):
    client = self.client(acks(b"\x00\x00\x00\x00\x00", b"\x01\x00\x00\x00\x00", b"\x01\x01\x02\x00\x00"))
    client.set_session_status(0x12)
    self.assertSent(COMMAND_CODE.SET_S_STATUS, b"\x12")

    ret = client.get_session_status()
    self.assertSent(COMMAND_CODE.GET_S_STATUS, b"")
    self.assertEqual((ret.status, ret.info), (1, None))

    # info byte is only valid when the second byte is set
    self.assertEqual(client.get_session_status().info, 2)

    with self.assertRaises(ValueError):
      client.set_session_status(256)

  def test_build_checksum(self):
    client = self.client(ack(b"\x02\xab\xcd\x00\x00"))
    self.assertEqual(client.build_checksum(0x1000), b"\xab\xcd")
    self.assertSent(COMMAND_CODE.BUILD_CHKSUM, b"\x00\x00\x10\x00")

  def test_build_checksum_too_long(self):
    client = self.client(ack(b"\x05\xab\xcd\x00\x00"))
    with self.assertRaises(AssertionError):
      client.build_checksum(0x1000)

  def test_clear_memory(self):
    client = self.client(ack())
    client.clear_memory(0x100)
    self.assertSent(COMMAND_CODE.CLEAR_MEMORY, b"\x00\x00\x01\x00")

  def test_program(self):
    client = self.client(ack(b"\x00\x00\x00\x20\x00"))
    self.assertEqual(client.program(2, b"\x01\x02"), 0x2000)
    self.assertSent(COMMAND_CODE.PROGRAM, b"\x02\x01\x02")
    with self.assertRaises(ValueError):
      client.program(6, b"")
    with self.assertRaises(ValueError):
      client.program(5, b"\x00" * 6)

  def test_program_6_bytes(self):
    client = self.client(ack(b"\x00\x00\x00\x20\x00"))
    self.assertEqual(client.program_6_bytes(b"\x01\x02\x03\x04\x05\x06"), 0x2000)
    self.assertSent(COMMAND_CODE.PROGRAM_6, b"\x01\x02\x03\x04\x05\x06")
    with self.assertRaises(ValueError):
      client.program_6_bytes(b"\x00" * 7)

  def test_move_memory_block(self):
    client = self.client(ack())
    client.move_memory_block(0x40)
    self.assertSent(COMMAND_CODE.MOVE, b"\x00\x00\x00\x40")

  def test_diagnostic_service(self):
    client = self.client(ack(b"\x03\x01\x00\x00\x00"))
    ret = client.diagnostic_service(0x1234, b"\x01\x02")
    self.assertSent(COMMAND_CODE.DIAG_SERVICE, b"\x12\x34\x01\x02")
    self.assertEqual((ret.length, ret.type), (3, 1))
    with self.assertRaises(ValueError):
      client.diagnostic_service(65536)
    with self.assertRaises(ValueError):
      client.diagnostic_service(0, b"\x00" * 5)

  def test_action_service(self):
    client = self.client(ack(b"\x02\x01\x00\x00\x00"))
    ret = client.action_service(0x1234, b"\x01")
    self.assertSent(COMMAND_CODE.ACTION_SERVICE, b"\x12\x34\x01")
    self.assertEqual((ret.length, ret.type), (2, 1))
    with self.assertRaises(ValueError):
      client.action_service(65536)
    with self.assertRaises(ValueError):
      client.action_service(0, b"\x00" * 5)

  def test_test_availability(self):
    client = self.client(ack())
    client.test_availability(0x1234)
    # station address is always little endian
    self.assertSent(COMMAND_CODE.TEST, b"\x34\x12")
    with self.assertRaises(ValueError):
      client.test_availability(65536)

  def test_start_stop_synchronised_transmission(self):
    client = self.client(ack())
    client.start_stop_synchronised_transmission(1)
    self.assertSent(COMMAND_CODE.START_STOP_ALL, b"\x01")
    with self.assertRaises(ValueError):
      client.start_stop_synchronised_transmission(256)

  def test_get_active_calibration_page(self):
    client = self.client(ack(b"\x00\x00\x01\x00\x00"))
    self.assertEqual(client.get_active_calibration_page(), 0x10000)
    self.assertSent(COMMAND_CODE.GET_ACTIVE_CAL_PAGE, b"")

  def test_get_version(self):
    client = self.client(ack(b"\x02\x01\x00\x00\x00"))
    self.assertEqual(client.get_version(2.1), 2.1)
    self.assertSent(COMMAND_CODE.GET_CCP_VERSION, b"\x02\x01")

  def test_little_endian_byte_order(self):
    client = self.client(ack(b"\x00" + struct.pack("<I", 0x1000)), byte_order=BYTE_ORDER.LITTLE_ENDIAN)
    client.set_memory_transfer_address(0, 0, 0xDEADBEEF)
    self.assertSent(COMMAND_CODE.SET_MTA, b"\x00\x00\xef\xbe\xad\xde")
    self.assertEqual(client.download(b"\x01"), 0x1000)


if __name__ == "__main__":
  unittest.main()
