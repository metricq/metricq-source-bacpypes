from typing import Optional

from pydantic import BaseModel
from pydantic.class_validators import validator
from pydantic.fields import Field
from pydantic.types import PositiveFloat, PositiveInt

_model_config = {"extra": "forbid", "frozen": True}
"""
Extra parameters are forbidden and will raise validation errors.
The parameters will not be mutable.
"""


class Metric(BaseModel, **_model_config):
    identifier: str
    """Object identifier, e.g. ``analogValue:190``"""
    description: str = ""
    """Description for metadata, will be merged with host description if available"""
    unit: Optional[str] = None
    """Unit for metadata"""
    chunk_size: Optional[int] = None
    """
    Chunk size. By default no chunking is configured except for intervals below 1s.
    For those, chunking will set to one chunk per second (1s/interval)
    """


class Group(BaseModel, **_model_config):
    """
    A group of metrics that will be queried together.
    The given metrics should be closely together in the register address space.
    """

    interval: PositiveFloat | PositiveInt | str | None = None
    """
    Query interval in seconds for the group.
    A string can also be used that will be parsed by MetricQ exactly, e.g. ``100ms``.
    If omitted, the global interval will be used.
    """
    metrics: dict[str, Metric]
    """Dictionary of metrics, keys are the metric names prefixed by the host name"""

    @validator("metrics")  # type: ignore
    def metrics_not_empty(cls, v: dict[str, Metric]) -> dict[str, Metric]:
        if len(v) == 0:
            raise ValueError("Group must have at least one metric")
        return v


class Device(BaseModel, **_model_config):
    address: str
    """Address of the device to query, e.g. ``192.168.10.28``"""
    prefix: str
    """
    The prefix of the metric name, e.g., ``LZR.K21.KKR00``.
    When expanded, the length must match the length of the ``hosts``.
    """
    description: str = ""
    """Description prefix for metadata"""
    groups: list[Group] = Field(..., min_length=1)
    """ List of query groups. """


# We cannot forbid because of magic couchdb fields in the config e.g. `_id`
class Source(BaseModel, extra="ignore", frozen=True):
    bacnetAddress: str
    """Address of the BacNet client used as source"""
    bacnetIdentifier: int
    """Identifier for the BacNet client used as source"""
    bacnetName: str
    """Name of the BacNet client used as source"""
    interval: PositiveFloat | PositiveInt | str | None = None
    """
    Default query interval in seconds.
    A string can also be used that will be parsed by MetricQ exactly, e.g. ``100ms``.
    If omitted, the global interval will be used.
    """
    devices: list[Device] = Field(..., min_length=1)
