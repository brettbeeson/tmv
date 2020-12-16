# pylint: disable=protected-access
from pathlib import Path
from tmv.buttons import OnOffAuto
from tmv.circstates import State, StatesCircle

def test_circstates():
    
    
    states = [State(OnOffAuto.ON,blink=1), State(OnOffAuto.OFF,blink=2), State(OnOffAuto.AUTO,blink=3)]
    stateful = StatesCircle("state",states)
    
    # State
    assert str(stateful._current) == "on"
    assert stateful._current == "on"         # allow str
    assert stateful._current == OnOffAuto.ON # and class instance
    assert OnOffAuto.ON == stateful._current # and backwards
    assert stateful.value == OnOffAuto.ON

    # Iterate
    assert next(stateful) == OnOffAuto.OFF
    assert next(stateful) == "auto"
    assert next(stateful) == "on"
    assert next(stateful) == "off"

    # Use current mode easily
    assert stateful == "off"
    assert stateful == OnOffAuto.OFF
    next(stateful)
    assert stateful == "auto"
    assert stateful == OnOffAuto.AUTO


    # Set states to and get from file
    assert stateful.value == OnOffAuto.AUTO
    stateful.value = OnOffAuto.AUTO
    assert Path("state").read_text() == "auto"

    # Recover if text file corrupted
    Path("state").write_text("askldjfa;skldfjas\n\n\ndf")
    assert stateful.value == OnOffAuto.AUTO
    stateful.value = OnOffAuto.AUTO
    assert Path("state").read_text() == "auto"
    assert next(stateful) == "on"
    assert Path("state").read_text() == "on"

    