# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Roberto Locatelli
"""qraft_ra._compat — the Italian names of 0.2.0 as DEPRECATED aliases of the English API of 0.3.0.

Every use of an old name (module, class, function, keyword argument, field) emits a DeprecationWarning that names the
new one, so a migration can be measured (`python -W error::DeprecationWarning` fails on any old name). The aliases are
removed in a later release; nothing new should use them. Modules: `qraft_ra.intervallo_garantito`,
`rotore_spettro`, `scqubits_adattatore`, `rotore_sferico_garantito`, `molecola_iperfine_garantita`, `multiporta`.
"""
from __future__ import annotations

import functools
import warnings
from typing import Dict, Optional


def _warn(old: str, new: str) -> None:
    warnings.warn(f"{old} is deprecated since qraft-ra 0.3.0: use {new}", DeprecationWarning, stacklevel=3)


def deprecated_module(old: str, new: str) -> None:
    """Called at import time by an old-named module."""
    warnings.warn(f"qraft_ra.{old} is deprecated since qraft-ra 0.3.0: use qraft_ra.{new}", DeprecationWarning,
                  stacklevel=3)


def deprecated_function(new, old_name: str, kwmap: Optional[Dict[str, str]] = None):
    """A function that warns, translates the Italian keyword arguments with `kwmap` and calls `new`."""
    kwmap = dict(kwmap or {})

    @functools.wraps(new)
    def wrapper(*args, **kwargs):
        _warn(old_name, new.__name__)
        return new(*args, **{kwmap.get(k, k): v for k, v in kwargs.items()})
    wrapper.__name__ = old_name
    wrapper.__qualname__ = old_name
    return wrapper


def deprecated_class(new: type, old_name: str, kwmap: Optional[Dict[str, str]] = None) -> type:
    """A subclass of `new` (so isinstance checks on the new class still hold) whose constructor warns and translates
    the Italian keyword arguments."""
    kwmap = dict(kwmap or {})

    def __init__(self, *args, **kwargs):
        _warn(old_name, new.__name__)
        new.__init__(self, *args, **{kwmap.get(k, k): v for k, v in kwargs.items()})
    return type(old_name, (new,), {"__init__": __init__, "__doc__": f"Deprecated alias of {new.__name__}.",
                                   "__module__": new.__module__})


def add_field_aliases(cls: type, aliases: Dict[str, str]) -> None:
    """Italian field names as read-only properties that warn and return the English field."""
    for old, new in aliases.items():
        def getter(self, _old=old, _new=new):
            warnings.warn(f"{cls.__name__}.{_old} is deprecated since qraft-ra 0.3.0: use .{_new}", DeprecationWarning,
                          stacklevel=2)
            return getattr(self, _new)
        setattr(cls, old, property(getter))
