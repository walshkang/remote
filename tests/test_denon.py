import pytest

from app.modules.denon.driver import DenonDriver
from app.modules.denon.module import Module


@pytest.mark.asyncio
async def test_denon_driver_parsing():
    updates = []

    async def callback(patch):
        updates.append(patch)

    driver = DenonDriver("127.0.0.1", on_state_change=callback)

    # 1. Power
    await driver._parse_line("PWON")
    assert updates[-1] == {"power": "ON"}
    await driver._parse_line("PWSTANDBY")
    assert updates[-1] == {"power": "STANDBY"}

    # 2. Mute
    await driver._parse_line("MUON")
    assert updates[-1] == {"mute": True}
    await driver._parse_line("MUOFF")
    assert updates[-1] == {"mute": False}

    # 3. Volume 2-digit & 3-digit half-dB
    await driver._parse_line("MV40")
    assert updates[-1] == {"volume": 40.0, "volume_db": "-40.0 dB"}
    await driver._parse_line("MV505")
    assert updates[-1] == {"volume": 50.5, "volume_db": "-29.5 dB"}

    # 4. Must ignore MVMAX (no crash, no update)
    prev_len = len(updates)
    await driver._parse_line("MVMAX 80")
    assert len(updates) == prev_len

    # 5. Input Source
    await driver._parse_line("SIMPLAY")
    assert updates[-1] == {"source": "MPLAY"}

    # 6. Now Playing NSE
    await driver._parse_line("NSE1Bohemian Rhapsody")
    await driver._parse_line("NSE2Queen")
    assert updates[-1]["now_playing"]["track"] == "Bohemian Rhapsody"
    assert updates[-1]["now_playing"]["artist"] == "Queen"


@pytest.mark.asyncio
async def test_denon_module_actions():
    from app.core.state_bus import StateBus
    from app.core.ws_manager import WSManager

    bus = StateBus(WSManager())
    mod = Module()
    bus.register(mod.module_id, mod.initial_state())
    await mod.start(bus)

    # Test initial volume delta
    start_vol = bus.get(mod.module_id)["volume"]
    await mod.handle_action("volume_delta", {"delta": 2.5}, client_id="test-client")
    assert bus.get(mod.module_id)["volume"] == start_vol + 2.5

    await mod.stop()
