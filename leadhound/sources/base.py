"""Shared helpers for sources."""
from __future__ import annotations

from ..net import FetchError


class PartialFailure(Exception):
    """Some sub-requests failed; `leads` holds what was collected anyway."""

    def __init__(self, leads: list, errors: list):
        super().__init__("; ".join(errors))
        self.leads = leads
        self.errors = errors


def collect_each(items, fn) -> list:
    """Run fn(item) -> list[Lead] for each item. One failing item does not lose the others."""
    leads, errors = [], []
    for item in items:
        try:
            leads += fn(item)
        except (FetchError, ValueError, KeyError) as e:
            errors.append(f"{item}: {e}"[:200])
        except Exception as e:  # malformed XML etc.
            errors.append(f"{item}: {type(e).__name__}: {e}"[:200])
    if errors and leads:
        raise PartialFailure(leads, errors)
    if errors:
        raise FetchError("; ".join(errors))
    return leads
