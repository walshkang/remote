from app.modules.hue.driver import HueModel, hs_to_xy

RES = {
    "light": [
        {"id": "L1", "owner": {"rid": "D1"}, "metadata": {"name": "Lamp"}, "on": {"on": True},
         "dimming": {"brightness": 60.0}, "color": {"xy": {"x": 0.5, "y": 0.4}},
         "color_temperature": {"mirek": 300, "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 500}},
         "effects": {"status_values": ["no_effect", "candle"]}},
        {"id": "L2", "owner": {"rid": "D2"}, "metadata": {"name": "Strip"}, "on": {"on": False},
         "dimming": {"brightness": 100.0}},
    ],
    "grouped_light": [{"id": "G1", "on": {"on": True}, "dimming": {"brightness": 55.0}}],
    "room": [{"id": "R1", "metadata": {"name": "Living Room"},
              "children": [{"rid": "D1", "rtype": "device"}, {"rid": "D2", "rtype": "device"}],
              "services": [{"rid": "G1", "rtype": "grouped_light"}]}],
    "zone": [],
    "scene": [{"id": "S1", "metadata": {"name": "Relax"}, "group": {"rid": "R1"}}],
}


def test_build_snapshot():
    m = HueModel()
    m.build(RES)
    snap = m.snapshot()
    room = snap["rooms"][0]
    assert room["name"] == "Living Room" and room["on"] and room["brightness"] == 55.0
    assert room["light_ids"] == ["L1", "L2"] and room["scenes"] == [{"id": "S1", "name": "Relax"}]
    assert snap["lights"]["L1"]["has_color"] and snap["lights"]["L1"]["effects"] == ["candle"]
    assert not snap["lights"]["L2"]["has_color"]


def test_apply_events():
    m = HueModel()
    m.build(RES)
    assert m.apply_event({"type": "light", "id": "L2", "on": {"on": True}, "dimming": {"brightness": 20}})
    assert m.lights["L2"]["on"] and m.lights["L2"]["brightness"] == 20
    assert m.apply_event({"type": "grouped_light", "id": "G1", "on": {"on": False}})
    assert m.snapshot()["rooms"][0]["on"] is False
    assert not m.apply_event({"type": "light", "id": "nope"})


def test_hs_to_xy():
    x, y = hs_to_xy(0, 100)  # red
    assert x > 0.6 and y < 0.35
    x, y = hs_to_xy(120, 100)  # green
    assert y > 0.6
    x, y = hs_to_xy(0, 0)  # white ~ D65
    assert abs(x - 0.3127) < 0.02
