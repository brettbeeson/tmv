# pylint: disable=broad-except,logging-fstring-interpolation,logging-not-lazy, dangerous-default-value
import logging
from pathlib import Path
import itertools

LOGGER = logging.getLogger("tmv.circstates")


class State():
    """[summary]
    """

    def __init__(self, value, **kwargs):
        self.value = value
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return str(self.value)

    # allow str comparison
    def __eq__(self, other):
        return str(self) == str(other)

    # allow str comparison
    def __ne__(self, other):
        return str(self) != str(other)


class StatesCircle:
    """[summary]
    """

    def __init__(self, path, _states, fallback=None):
        self.path = Path(path)
        self._states = _states
        self._circ_iter = itertools.cycle(self._states)
        if fallback:
            # set "initial" value as the fallback and overwrite with file, if available
            try:
                state = next(s for s in self._states if s.value == fallback)
                self._current = state
                # move the circular iterator to the right spot
                while next(self._circ_iter) != state:
                    pass

            except StopIteration as e:
                raise RuntimeError(f"Tried to set initial value of '{fallback}' which doesn't exist in {list(self._states)}") from e
        else:
            # create temp new iterator to store current so self.__next__ works as expected
            # if we set to _states[0] then __next__ returns ????
            self._current = next(iter(self._circ_iter))

        # update from file (will return "_current" if no file exists yet)
        try:
            self._current = self.value
        except PermissionError:
            # if we can't find a file
            pass

    def __iter__(self):
        return self._circ_iter

    def __next__(self):
        self._current = next(self._circ_iter)
        self.value = self._current  # write file
        return self._current

    def __eq__(self, other):
        return self._current == other

    def __nq__(self, other):
        return self._current != other

    @property
    def value(self) -> State:
        """
        Get the current state. Update from from the file if possible.
        """

        if self.path is None or not self.path.exists():
            # raise FileNotFoundError("No path set for Stateful.")
            return self._current

        s_str = self.path.read_text(encoding='UTF-8').strip('\n').lower()
        # find this str in states
        try:
            state = next(s for s in self._states if str(s.value) == s_str)
        except StopIteration:
            LOGGER.warning(f"'{s_str}' is not a key within {self._states}. Resetting to {self._current}.")
            self.path.write_text(str(self._current))
            return self._current

        # move iterator too so 'current' calls get this value
        # could shorten? self._current = next( s for s in self._states if ...
        i = 0
        while self._current != state:
            next(self)
            i += 1
            if i > len(self._states):
                raise KeyError(f"'{state}' is not a key within {self._states})")
        return state

    @value.setter
    def value(self, state):
        """ Set the value and update the file  """
        if self.path:
            if not self.path.exists():
                LOGGER.info(f"Creating {str(self.path)}")
            with self.path.open(mode="w") as f:
                f.write(str(state.value))
