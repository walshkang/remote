import asyncio
from types import SimpleNamespace

import pytest

from app.core.state_bus import StateBus
from app.core.ws_manager import WSManager
from app.modules.litter_robot.module import Module, robot_snapshot


class FakeRobot:
    def __init__(self, status="READY"):
        self.status = SimpleNamespace(name=status, text=status)
        self.name, self.is_online, self.is_on = "Robo", True, True
        self.is_waste_drawer_full = False
        self.waste_drawer_level, self.litter_level, self.pet_weight = 42.34, 80.0, 9.6
        self.night_light_mode_enabled = self.panel_lock_enabled = False
        self.clean_cycle_wait_time_minutes = 7
        self.cleans = 0

    async def start_cleaning(self):
        self.cleans += 1
        return True


async def make(status="READY"):
    bus = StateBus(WSManager())
    mod = Module()
    bus.register(mod.module_id, mod.initial_state())
    mod.bus, mod.robot = bus, FakeRobot(status)
    return bus, mod


def test_snapshot():
    snap = robot_snapshot(FakeRobot("CLEAN_CYCLE"))
    assert snap["cycling"] and snap["waste_level"] == 42.3 and not snap["cat_detected"]


@pytest.mark.asyncio
async def test_simultaneous_clean_taps_start_one_cycle():
    bus, mod = await make()
    await asyncio.gather(*(mod.handle_action("clean", {}, f"c{i}") for i in range(3)))
    assert mod.robot.cleans == 1


@pytest.mark.asyncio
async def test_no_clean_with_cat_inside():
    bus, mod = await make("CAT_DETECTED")
    await mod.handle_action("clean", {}, "c1")
    assert mod.robot.cleans == 0
    assert "cat" in bus.get(mod.module_id)["notice"].lower()
