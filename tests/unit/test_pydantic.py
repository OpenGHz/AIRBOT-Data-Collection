"""Pydantic generic-model behavior (extra=forbid, cached_property, generic wrapper).

Pure software. Was previously a module-level script that only printed values.
"""

from functools import cached_property
from typing import Generic, TypeVar

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

pytestmark = pytest.mark.software

T = TypeVar("T")


class Component(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    name: T

    @cached_property
    def unique_key(self) -> str:
        return self.name.upper()


class Config(BaseModel, Generic[T]):
    item: Component[T]


def test_component_dump_and_cached_key():
    comp = Component(name="test")
    assert comp.model_dump() == {"name": "test"}
    assert comp.unique_key == "TEST"


def test_generic_config_wraps_component():
    comp = Component(name="test")
    cfg = Config[str](item=comp)
    # pydantic may re-wrap the instance as Component[str], so compare by value.
    assert cfg.item.name == "test"
    assert cfg.item.model_dump() == comp.model_dump()


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        Component(name="test", surprise=1)
