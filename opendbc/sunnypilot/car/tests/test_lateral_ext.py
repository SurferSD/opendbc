import unittest

from opendbc.car import structs
from opendbc.sunnypilot.car.lateral_ext import get_friction

FRICTION = 0.1
THRESHOLD = 0.2


class TestGetFrictionExt(unittest.TestCase):
  def setUp(self):
    self.torque_params = structs.CarParams.LateralTorqueTuning(friction=FRICTION, latAccelFactor=2.0)

  def test_deadzone(self):
    for error in (-0.09, 0., 0.09):
      self.assertEqual(get_friction(error, 0.1, THRESHOLD, self.torque_params), 0.)

  def test_saturates_at_threshold(self):
    self.assertAlmostEqual(get_friction(THRESHOLD, 0., THRESHOLD, self.torque_params), FRICTION)
    self.assertAlmostEqual(get_friction(10 * THRESHOLD, 0., THRESHOLD, self.torque_params), FRICTION)
    self.assertAlmostEqual(get_friction(-10 * THRESHOLD, 0., THRESHOLD, self.torque_params), -FRICTION)

  def test_interpolates_linearly(self):
    self.assertAlmostEqual(get_friction(THRESHOLD / 2, 0., THRESHOLD, self.torque_params), FRICTION / 2)
    self.assertAlmostEqual(get_friction(-THRESHOLD / 2, 0., THRESHOLD, self.torque_params), -FRICTION / 2)

  def test_ignores_lat_accel_factor(self):
    # unlike opendbc.car.lateral.get_friction, friction is not scaled by latAccelFactor
    scaled = structs.CarParams.LateralTorqueTuning(friction=FRICTION, latAccelFactor=4.0)
    self.assertAlmostEqual(get_friction(THRESHOLD, 0., THRESHOLD, scaled), FRICTION)


if __name__ == "__main__":
  unittest.main()
