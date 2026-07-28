import unittest
from unittest.mock import patch

from opendbc.car.disable_ecu import COM_CONT_RESPONSE, EXT_DIAG_REQUEST, EXT_DIAG_RESPONSE, disable_ecu

ADDR = 0x7d0
COM_CONT_REQ = b'\x28\x83\x01'


class MockQuery:
  """Records the constructor args of every IsoTpParallelQuery and replays canned query results."""

  results: list = []
  queries: list[tuple] = []

  def __init__(self, can_send, can_recv, bus, addrs, request, response, **kwargs):
    self.queries.append((bus, addrs, request, response))

  def get_data(self, timeout):
    ret = self.results.pop(0)
    if isinstance(ret, Exception):
      raise ret
    return ret

  @classmethod
  def reset(cls, results):
    cls.results = list(results)
    cls.queries = []


class TestDisableEcu(unittest.TestCase):
  def setUp(self):
    patcher = patch("opendbc.car.disable_ecu.IsoTpParallelQuery", MockQuery)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_disable_ecu(self):
    MockQuery.reset([{(ADDR, None): EXT_DIAG_RESPONSE}, {(ADDR, None): COM_CONT_RESPONSE}])
    self.assertTrue(disable_ecu(None, None, bus=1, addr=ADDR))
    self.assertEqual(MockQuery.queries, [(1, [(ADDR, None)], [EXT_DIAG_REQUEST], [EXT_DIAG_RESPONSE]),
                                         (1, [(ADDR, None)], [COM_CONT_REQ], [COM_CONT_RESPONSE])])

  def test_disable_ecu_sub_addr(self):
    MockQuery.reset([{(ADDR, 0x0d): EXT_DIAG_RESPONSE}, {(ADDR, 0x0d): COM_CONT_RESPONSE}])
    self.assertTrue(disable_ecu(None, None, addr=ADDR, sub_addr=0x0d))
    self.assertEqual([addrs for _, addrs, _, _ in MockQuery.queries], [[(ADDR, 0x0d)]] * 2)

  def test_retries_on_empty_response(self):
    MockQuery.reset([{}, {}, {(ADDR, None): EXT_DIAG_RESPONSE}, {(ADDR, None): COM_CONT_RESPONSE}])
    self.assertTrue(disable_ecu(None, None, addr=ADDR))
    self.assertEqual(len(MockQuery.queries), 4)

  def test_retries_on_exception(self):
    MockQuery.reset([RuntimeError("no response"), {(ADDR, None): EXT_DIAG_RESPONSE}, {(ADDR, None): COM_CONT_RESPONSE}])
    self.assertTrue(disable_ecu(None, None, addr=ADDR))

  def test_gives_up_after_retries(self):
    MockQuery.reset([{}] * 3)
    self.assertFalse(disable_ecu(None, None, addr=ADDR, retry=3))
    self.assertEqual(len(MockQuery.queries), 3)


if __name__ == "__main__":
  unittest.main()
