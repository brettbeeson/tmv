# pylint: disable=protected-access
import os
from tempfile import mkdtemp
from pathlib import Path
from tmv.buttons import OnOffAutoVideo
from tmv.circstates import State, StatesCircle


def test_circstates():

    states = [State(OnOffAutoVideo.ON, blink=1), State(
        OnOffAutoVideo.OFF, blink=2), State(OnOffAutoVideo.AUTO, blink=3)]
    stateful = StatesCircle("state", states)

    # State
    assert str(stateful._current) == "on"
    assert stateful._current == "on"         # allow str
    assert stateful._current == OnOffAutoVideo.ON  # and class instance
    assert OnOffAutoVideo.ON == stateful._current  # and backwards
    assert stateful.value == OnOffAutoVideo.ON

    # Iterate
    assert next(stateful) == OnOffAutoVideo.OFF
    assert next(stateful) == "auto"
    assert next(stateful) == "on"
    assert next(stateful) == "off"

    # Use current mode easily
    assert stateful == "off"
    assert stateful == OnOffAutoVideo.OFF
    next(stateful)
    assert stateful == "auto"
    assert stateful == OnOffAutoVideo.AUTO

    # Set states to and get from file
    assert stateful.value == OnOffAutoVideo.AUTO
    stateful.value = OnOffAutoVideo.AUTO
    assert Path("state").read_text() == "auto"

    # Recover if text file corrupted
    Path("state").write_text("Qskldjfa;skldfjas\n\n\ndf")
    assert stateful.value == OnOffAutoVideo.AUTO
    stateful.value = OnOffAutoVideo.AUTO
    assert Path("state").read_text() == "auto"
    assert next(stateful) == "on"
    assert Path("state").read_text() == "on"

    # test initial values in new directory
    #
    os.chdir(mkdtemp())
    stateful = StatesCircle("state", states)
    assert stateful.value == OnOffAutoVideo.ON  # default default
    stateful.value = OnOffAutoVideo.ON  # write to file

    stateful = None
    stateful = StatesCircle("state", states, fallback=OnOffAutoVideo.OFF)
    assert stateful.value == OnOffAutoVideo.ON  # still "ON" as stored in file
    os.chdir(mkdtemp())

    stateful = None
    stateful = StatesCircle("state", states, fallback=OnOffAutoVideo.OFF)
    assert stateful.value == OnOffAutoVideo.OFF  # "OFF" as no file so uses initial
    assert next(stateful) == "auto"

    Path("state").write_text("off")
    assert stateful.value == OnOffAutoVideo.OFF
    Path("state").write_text("on")
    assert stateful.value == OnOffAutoVideo.ON
