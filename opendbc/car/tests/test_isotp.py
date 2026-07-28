import unittest
from unittest.mock import patch

from opendbc.car import isotp
from opendbc.car.tests.mock_panda import MockPanda

ADDR = 0x750
RECV_ADDR = ADDR + 8
BUS = 1


class TestIsoTp(unittest.TestCase):
  def setUp(self):
    # the module buffers unmatched messages in a global
    isotp.kmsgs = []
    self.panda = MockPanda()

  def sent(self) -> list[bytes]:
    for addr, _, _ in self.panda.sent:
      self.assertEqual(addr, ADDR)
    return [dat for _, dat, _ in self.panda.sent]

  # *** framing helpers ***

  def test_msg(self):
    self.assertEqual(isotp.msg(b"\x01\x02\x03"), b"\x03\x01\x02\x03\x00\x00\x00\x00")
    self.assertEqual(isotp.msg(b""), b"\x00" * 8)
    self.assertEqual(isotp.msg(b"\x01" * 7), b"\x07" + b"\x01" * 7)
    with self.assertRaises(AssertionError):
      isotp.msg(b"\x00" * 8)

  def test_recv_filters_and_buffers(self):
    self.panda.queue_rx((ADDR, b"\xaa", BUS),
                        (ADDR, b"\xbb", BUS + 1),  # wrong bus, buffered
                        (ADDR + 1, b"\xcc", BUS),  # wrong address, buffered
                        (ADDR, b"\xdd", BUS))
    self.assertEqual(isotp.recv(self.panda, 2, ADDR, BUS), [b"\xaa", b"\xdd"])
    self.assertEqual(isotp.kmsgs, [(ADDR, b"\xbb", BUS + 1), (ADDR + 1, b"\xcc", BUS)])

  def test_recv_across_multiple_polls(self):
    self.panda.queue_rx((ADDR, b"\xaa", BUS))
    self.panda.queue_rx()
    self.panda.queue_rx((ADDR, b"\xbb", BUS))
    self.assertEqual(isotp.recv(self.panda, 2, ADDR, BUS), [b"\xaa", b"\xbb"])

  # *** send ***

  def test_send_single_frame(self):
    isotp.isotp_send(self.panda, b"\x01\x02\x03", ADDR, bus=BUS)
    self.assertEqual(self.panda.sent, [(ADDR, b"\x03\x01\x02\x03\x00\x00\x00\x00", BUS)])

  def test_send_single_frame_subaddr(self):
    isotp.isotp_send(self.panda, b"\x01" * 6, ADDR, bus=BUS, subaddr=0x0d)
    self.assertEqual(self.panda.sent, [(ADDR, b"\x0d\x06" + b"\x01" * 6, BUS)])

  def test_send_multi_frame(self):
    dat = bytes(range(20))
    self.panda.queue_rx((RECV_ADDR, b"\x30\x00" + b"\x00" * 6, BUS))
    isotp.isotp_send(self.panda, dat, ADDR, bus=BUS)
    self.assertEqual(self.sent(), [b"\x10\x14" + dat[:6],
                                   b"\x21" + dat[6:13],
                                   b"\x22" + dat[13:20]])

  def test_send_multi_frame_single_block(self):
    # a block size of one means the receiver sends flow control between each frame
    dat = bytes(range(20))
    for _ in range(2):
      self.panda.queue_rx((RECV_ADDR, b"\x30\x01" + b"\x00" * 6, BUS))
    isotp.isotp_send(self.panda, dat, ADDR, bus=BUS)
    self.assertEqual(self.sent(), [b"\x10\x14" + dat[:6],
                                   b"\x21" + dat[6:13],
                                   b"\x22" + dat[13:20]])
    # consecutive frames are sent one by one on bus 0
    self.assertEqual([bus for _, _, bus in self.panda.sent], [BUS, 0, 0])

  def test_send_multi_frame_with_rate(self):
    dat = bytes(range(20))
    self.panda.queue_rx((RECV_ADDR, b"\x30\x00" + b"\x00" * 6, BUS))
    with patch("opendbc.car.isotp.time.sleep") as sleep:
      isotp.isotp_send(self.panda, dat, ADDR, bus=BUS, rate=0.01)
    self.assertEqual(sleep.call_count, 2)
    self.assertEqual(self.sent(), [b"\x10\x14" + dat[:6],
                                   b"\x21" + dat[6:13],
                                   b"\x22" + dat[13:20]])

  def test_send_multi_frame_subaddr(self):
    dat = bytes(range(17))
    self.panda.queue_rx((RECV_ADDR, b"\x0d\x30\x00" + b"\x00" * 5, BUS))
    isotp.isotp_send(self.panda, dat, ADDR, bus=BUS, subaddr=0x0d)
    self.assertEqual(self.sent(), [b"\x0d\x10\x11" + dat[:5],
                                   b"\x0d\x21" + dat[5:11],
                                   b"\x0d\x22" + dat[11:17]])

  def test_send_default_recv_addr(self):
    dat = bytes(range(20))
    self.panda.queue_rx((RECV_ADDR, b"\x30\x00" + b"\x00" * 6, BUS))
    isotp.isotp_send(self.panda, dat, ADDR, bus=BUS, recvaddr=None)
    self.assertEqual(len(self.panda.sent), 3)

  # *** recv ***

  def test_recv_single_frame(self):
    self.panda.queue_rx((ADDR, b"\x03\x01\x02\x03\x00\x00\x00\x00", BUS))
    self.assertEqual(isotp.isotp_recv(self.panda, ADDR, bus=BUS), b"\x01\x02\x03")
    self.assertEqual(self.panda.sent, [])

  def test_recv_multi_frame(self):
    dat = bytes(range(20))
    self.panda.queue_rx((ADDR, b"\x10\x14" + dat[:6], BUS),
                        (ADDR, b"\x21" + dat[6:13], BUS),
                        (ADDR, b"\x22" + dat[13:20], BUS))
    self.assertEqual(isotp.isotp_recv(self.panda, ADDR, bus=BUS), dat)
    # flow control with a block size of zero is sent to the default send address
    self.assertEqual(self.panda.sent, [(ADDR - 8, b"\x30" + b"\x00" * 7, BUS)])

  def test_recv_bad_frame_type(self):
    self.panda.queue_rx((ADDR, b"\x40" + b"\x00" * 7, BUS))
    with self.assertRaises(AssertionError):
      isotp.isotp_recv(self.panda, ADDR, bus=BUS)

  def test_recv_single_frame_subaddr(self):
    self.panda.queue_rx((ADDR, b"\x0d\x03\x01\x02\x03\x00\x00\x00", BUS))
    self.assertEqual(isotp.isotp_recv(self.panda, ADDR, bus=BUS, subaddr=0x0d), b"\x01\x02\x03")

  def test_recv_multi_frame_subaddr(self):
    dat = bytes(range(17))
    self.panda.queue_rx((ADDR, b"\x0d\x10\x11" + dat[:5], BUS),
                        (ADDR, b"\x0d\x21" + dat[5:11], BUS),
                        (ADDR, b"\x0d\x22" + dat[11:17], BUS))
    self.assertEqual(isotp.isotp_recv(self.panda, ADDR, bus=BUS, sendaddr=0x740, subaddr=0x0d), dat)
    self.assertEqual(self.panda.sent, [(0x740, b"\x0d\x30" + b"\x00" * 6, BUS)])

  def test_recv_wrong_subaddr(self):
    self.panda.queue_rx((ADDR, b"\x0e\x03\x01\x02\x03\x00\x00\x00", BUS))
    with self.assertRaises(AssertionError):
      isotp.isotp_recv(self.panda, ADDR, bus=BUS, subaddr=0x0d)

  def test_recv_bad_frame_type_subaddr(self):
    self.panda.queue_rx((ADDR, b"\x0d\x40" + b"\x00" * 6, BUS))
    with self.assertRaises(AssertionError):
      isotp.isotp_recv(self.panda, ADDR, bus=BUS, subaddr=0x0d)

  def test_recv_bad_consecutive_frame_index(self):
    dat = bytes(range(20))
    self.panda.queue_rx((ADDR, b"\x10\x14" + dat[:6], BUS),
                        (ADDR, b"\x25" + dat[6:13], BUS),
                        (ADDR, b"\x22" + dat[13:20], BUS))
    with self.assertRaises(AssertionError):
      isotp.isotp_recv(self.panda, ADDR, bus=BUS)

  def test_debug_logging(self):
    self.panda.queue_rx((ADDR, b"\x03\x01\x02\x03\x00\x00\x00\x00", BUS))
    with patch("opendbc.car.isotp.DEBUG", True):
      isotp.isotp_send(self.panda, b"\x01", ADDR, bus=BUS)
      self.assertEqual(isotp.isotp_recv(self.panda, ADDR, bus=BUS), b"\x01\x02\x03")


if __name__ == "__main__":
  unittest.main()
