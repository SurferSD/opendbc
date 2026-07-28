import unittest

from opendbc.car import make_tester_present_msg, uds
from opendbc.car.can_definitions import CanData
from opendbc.car.ecu_addrs import _is_tester_present_response, get_all_ecu_addrs, get_ecu_addrs

BUS = 0
TESTER_PRESENT_RESPONSE = bytes([0x02, uds.SERVICE_TYPE.TESTER_PRESENT + 0x40, 0x00, 0, 0, 0, 0, 0])


class MockCan:
  def __init__(self, packets: list[list[CanData]] | None = None, send_exception: Exception | None = None):
    self.packets = packets if packets is not None else []
    self.send_exception = send_exception
    self.sent: list[list[CanData]] = []

  def recv(self, wait_for_one: bool = False) -> list[list[CanData]]:
    # the buffer is flushed before the queries are sent, so only respond after that
    if not len(self.sent) or not len(self.packets):
      return []
    return [self.packets.pop(0)]

  def send(self, msgs: list[CanData]) -> None:
    if self.send_exception is not None:
      raise self.send_exception
    self.sent.append(msgs)


class TestIsTesterPresentResponse(unittest.TestCase):
  def test_positive_response(self):
    self.assertTrue(_is_tester_present_response(CanData(0x758, TESTER_PRESENT_RESPONSE, BUS)))

  def test_negative_response(self):
    dat = bytes([0x03, 0x7F, uds.SERVICE_TYPE.TESTER_PRESENT, 0x11, 0, 0, 0, 0])
    self.assertTrue(_is_tester_present_response(CanData(0x758, dat, BUS)))

  def test_can_frame_optimization(self):
    # ISO-TP messages don't have to be padded to 8 bytes
    self.assertTrue(_is_tester_present_response(CanData(0x758, TESTER_PRESENT_RESPONSE[:3], BUS)))

  def test_other_service_response(self):
    dat = bytes([0x02, uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER + 0x40, 0x00, 0, 0, 0, 0, 0])
    self.assertFalse(_is_tester_present_response(CanData(0x758, dat, BUS)))

  def test_negative_response_for_other_service(self):
    dat = bytes([0x03, 0x7F, uds.SERVICE_TYPE.READ_DATA_BY_IDENTIFIER, 0x11, 0, 0, 0, 0])
    self.assertFalse(_is_tester_present_response(CanData(0x758, dat, BUS)))

  def test_bad_lengths(self):
    for dat in (b"", TESTER_PRESENT_RESPONSE[:2], TESTER_PRESENT_RESPONSE + b"\x00"):
      self.assertFalse(_is_tester_present_response(CanData(0x758, dat, BUS)))

  def test_bad_frame_length_byte(self):
    for frame_len in (0x00, 0x08, 0x10):
      dat = bytes([frame_len]) + TESTER_PRESENT_RESPONSE[1:]
      self.assertFalse(_is_tester_present_response(CanData(0x758, dat, BUS)))

  def test_subaddr(self):
    dat = bytes([0x0D]) + TESTER_PRESENT_RESPONSE[:7]
    self.assertTrue(_is_tester_present_response(CanData(0x758, dat, BUS), subaddr=0x0D))
    # without accounting for the subaddr, the same message is not a response
    self.assertFalse(_is_tester_present_response(CanData(0x758, dat, BUS)))


class TestGetEcuAddrs(unittest.TestCase):
  def test_query_and_response(self):
    can = MockCan([[CanData(0x758, TESTER_PRESENT_RESPONSE, BUS)]])
    ecus = get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.1)
    self.assertEqual(ecus, {(0x758, None, BUS)})
    self.assertEqual(can.sent, [[make_tester_present_msg(0x750, BUS)]])

  def test_no_response(self):
    can = MockCan()
    self.assertEqual(get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.01), set())

  def test_unexpected_responses_ignored(self):
    can = MockCan([[
      CanData(0x759, TESTER_PRESENT_RESPONSE, BUS),      # unexpected address
      CanData(0x758, TESTER_PRESENT_RESPONSE, BUS + 1),  # unexpected bus
      CanData(0x758, bytes([0x02, 0x50, 0x00, 0, 0, 0, 0, 0]), BUS),  # not a tester present response
    ]])
    self.assertEqual(get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.01), set())

  def test_empty_remote_frame_skipped(self):
    can = MockCan([[CanData(0x758, b"", BUS), CanData(0x758, TESTER_PRESENT_RESPONSE, BUS)]])
    ecus = get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.1)
    self.assertEqual(ecus, {(0x758, None, BUS)})

  def test_duplicate_responses(self):
    can = MockCan([[CanData(0x758, TESTER_PRESENT_RESPONSE, BUS)], [CanData(0x758, TESTER_PRESENT_RESPONSE, BUS)]])
    ecus = get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.1)
    self.assertEqual(ecus, {(0x758, None, BUS)})

  def test_subaddr(self):
    dat = bytes([0x0D]) + TESTER_PRESENT_RESPONSE[:7]
    can = MockCan([[CanData(0x758, dat, BUS)]])
    ecus = get_ecu_addrs(can.recv, can.send, {(0x750, 0x0D, BUS)}, {(0x758, 0x0D, BUS)}, timeout=0.1)
    self.assertEqual(ecus, {(0x758, 0x0D, BUS)})
    self.assertEqual(can.sent, [[make_tester_present_msg(0x750, BUS, subaddr=0x0D)]])

  def test_exception_is_caught(self):
    can = MockCan(send_exception=RuntimeError("panda disconnected"))
    self.assertEqual(get_ecu_addrs(can.recv, can.send, {(0x750, None, BUS)}, {(0x758, None, BUS)}, timeout=0.01), set())


class TestGetAllEcuAddrs(unittest.TestCase):
  def test_queries_all_addrs(self):
    can = MockCan([[CanData(0x18da10f1, TESTER_PRESENT_RESPONSE, BUS)]])
    ecus = get_all_ecu_addrs(can.recv, can.send, BUS, timeout=0.1)
    self.assertEqual(ecus, {(0x18da10f1, None, BUS)})

    queried = {msg.address for msg in can.sent[0]}
    self.assertEqual(len(queried), 512)
    self.assertTrue({0x700, 0x7FF, 0x18da00f1, 0x18dafff1}.issubset(queried))


if __name__ == "__main__":
  unittest.main()
