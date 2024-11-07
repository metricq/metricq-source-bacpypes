# Copyright (c) 2023, ZIH, Technische Universitaet Dresden, Federal Republic of Germany
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright notice,
#       this list of conditions and the following disclaimer in the documentation
#       and/or other materials provided with the distribution.
#     * Neither the name of metricq nor the names of its contributors
#       may be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import asyncio
from contextlib import suppress
from itertools import chain
from typing import Any, Iterable, Optional, Sequence, cast

from bacpypes3.app import Application  # type: ignore
from bacpypes3.basetypes import PropertyIdentifier  # type: ignore
from bacpypes3.ipv4.app import NormalApplication  # type: ignore
from bacpypes3.local.device import DeviceObject  # type: ignore
from bacpypes3.pdu import Address, IPv4Address  # type: ignore
from bacpypes3.primitivedata import ObjectIdentifier  # type: ignore
from metricq import JsonDict, MetadataDict, Source, Timedelta, Timestamp, rpc_handler
from metricq.logging import get_logger

from . import config_model
from .version import __version__  # noqa: F401 # magic import for automatic version

logger = get_logger()


CONNECTION_FAILURE_RETRY_INTERVAL = 10
"""Interval in seconds to retry connecting to a host after a connection failure"""


def combine_name(prefix: str, name: str) -> str:
    prefix = prefix.rstrip(".")
    name = name.lstrip(".")
    assert name != ""

    if prefix == "":
        return name
    return f"{prefix}.{name}"


def extract_interval(
    config: config_model.Source | config_model.Group,
) -> Optional[Timedelta]:
    """
    To allow interval, rate or maybe period, and other types in the future,
    we have a separate function here.
    """
    # We could to that as a validator in the pydantic model, but that would mess up
    # the type safety as mypy still things the field can be any of the types.
    # Also, we cannot easily extend it to look at "rate" or "period" or whatever.
    if config.interval is None:
        return None
    if isinstance(config.interval, (int, float)):
        return Timedelta.from_s(config.interval)
    assert isinstance(config.interval, str)
    return Timedelta.from_string(config.interval)


class ConfigError(Exception):
    pass


class Metric:
    def __init__(
        self,
        name: str,
        *,
        group: "MetricGroup",
        config: config_model.Metric,
    ):
        self.group = group
        device = group.device

        self.description = config.description
        if device.description:
            self.description = f"{device.description} {self.description}"

        chunk_size = config.chunk_size
        if chunk_size is None and group.interval < Timedelta.from_s(1):
            # Default chunking to one update per second
            chunk_size = Timedelta.from_s(1) // group.interval

        self._source_metric = device.source[name]
        if chunk_size is not None:
            self._source_metric.chunk_size = chunk_size

        self.identifier = config.identifier
        self.unit = config.unit
        self._property_parameter = (
            ObjectIdentifier(self.identifier),
            PropertyIdentifier("presentValue"),
        )

    @property
    def name(self) -> str:
        return self._source_metric.id

    @property
    def metadata(self) -> JsonDict:
        metadata = {
            "description": self.description,
            "rate": 1 / self.group.interval.s,
            "interval": self.group.interval.precise_string,
            "address": self.group.device.address,
            "identifier": self.identifier,
        }
        if self.unit:
            metadata["unit"] = self.unit
        return metadata

    @property
    def property_parameter(self) -> tuple[ObjectIdentifier, PropertyIdentifier]:
        return self._property_parameter

    async def send_update(
        self,
        timestamp: Timestamp,
        response: list[tuple[ObjectIdentifier, PropertyIdentifier, int | None, Any]],
    ) -> None:
        for data in response:
            if data[0] == self.property_parameter[0]:
                await self._source_metric.send(timestamp, cast(float, data[3]))


class MetricGroup:
    """
    Represents a set of metrics
    - same device (implicitly)
    - same interval (implicitly)
    """

    def _create_metrics(self, metrics: dict[str, config_model.Metric]) -> list[Metric]:
        return [
            Metric(
                combine_name(self.device.metric_prefix, metric_name),
                group=self,
                config=metric_config,
            )
            for metric_name, metric_config in metrics.items()
        ]

    def __init__(self, device: "Device", config: config_model.Group) -> None:
        self.device = device

        interval = extract_interval(config)
        if interval is None:
            interval = device.source.default_interval
            if interval is None:
                raise ConfigError("missing interval")
        self.interval: Timedelta = interval

        # Must be exactly here because we initialize `self.interval` before
        # and use `self._metrics` later
        self._metrics = self._create_metrics(config.metrics)

    @property
    def metadata(self) -> dict[str, MetadataDict]:
        return {metric.name: metric.metadata for metric in self._metrics}

    @property
    def _sampling_interval(self) -> Timedelta:
        return self.interval

    async def task(
        self,
        stop_future: asyncio.Future[None],
        app: Application,
    ) -> None:
        # Similar code as to metricq.IntervalSource.task, but for individual MetricGroups
        deadline = Timestamp.now()
        deadline -= (
            deadline % self._sampling_interval
        )  # Align deadlines to the interval
        while True:
            await self._update(app)

            now = Timestamp.now()
            deadline += self._sampling_interval

            if (missed := (now - deadline)) > Timedelta(0):
                missed_intervals = 1 + (missed // self._sampling_interval)
                logger.warning(
                    "Missed deadline {} by {} it is now {} (x{})",
                    deadline,
                    missed,
                    now,
                    missed_intervals,
                )
                deadline += self._sampling_interval * missed_intervals

            timeout = deadline - now
            done, pending = await asyncio.wait(
                (asyncio.create_task(asyncio.sleep(timeout.s)), stop_future),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_future in done:
                for task in pending:  # cancel pending sleep task
                    task.cancel()
                stop_future.result()  # potentially raise exceptions
                return

    async def _update(
        self,
        app: Application,
    ) -> None:
        timestamp = Timestamp.now()

        try:
            response = await app.read_property_multiple(
                self.device.bacnet_address,
                list(chain(*[metric.property_parameter for metric in self._metrics])),
            )
        except Exception as e:
            logger.exception("Failed to read property: {}", e)
            return

        if response is None:
            logger.error("Failed to read property. Result is None.")
            return

        duration = Timestamp.now() - timestamp
        logger.debug(f"Request finished successfully in {duration}")

        # TODO insert small sleep and see if that helps align stuff

        await asyncio.gather(
            *(metric.send_update(timestamp, response) for metric in self._metrics)
        )


class Device:
    def __init__(
        self,
        source: "BacpypesSource",
        *,
        config: config_model.Device,
    ):
        self.source = source
        self._address = config.address
        self.bacnet_address = Address(self._address)
        self.metric_prefix = config.prefix
        self.description = config.description

        self._groups = [
            MetricGroup(self, group_config) for group_config in config.groups
        ]

    @classmethod
    def _create_from_device_config(
        cls,
        source: "BacpypesSource",
        device_config: config_model.Device,
    ) -> Iterable["Device"]:
        yield Device(source=source, config=device_config)

    @classmethod
    def create_from_device_configs(
        cls, source: "BacpypesSource", device_configs: Sequence[config_model.Device]
    ) -> Iterable["Device"]:
        for host_config in device_configs:
            yield from cls._create_from_device_config(source, host_config)

    @property
    def address(self) -> str:
        return self._address

    @property
    def metadata(self) -> dict[str, MetadataDict]:
        return {
            metric: metadata
            for group in self._groups
            for metric, metadata in group.metadata.items()
        }

    async def task(self, app: Application, stop_future: asyncio.Future[None]) -> None:
        retry = True
        while retry:
            try:
                await asyncio.gather(
                    *[group.task(stop_future, app) for group in self._groups]
                )
                retry = False
            except Exception as e:
                logger.error(
                    "Error in Device {} task: {} ({})", self.address, e, type(e)
                )
                await asyncio.sleep(CONNECTION_FAILURE_RETRY_INTERVAL)


class BacpypesSource(Source):
    default_interval: Optional[Timedelta] = None
    devices: Optional[list[Device]] = None
    _device_task_stop_future: Optional[asyncio.Future[None]] = None
    _device_task: Optional[asyncio.Task[None]] = None
    bacnet: Optional[Application] = None

    @rpc_handler("config")
    async def _on_config(
        self,
        **kwargs: Any,
    ) -> None:
        config = config_model.Source(**kwargs)
        self.default_interval = extract_interval(config)

        if self.devices is not None:
            await self._stop_device_tasks()
            if self.bacnet is not None:
                # If the connect somewhat failed, close will raise an attribute error
                with suppress(AttributeError):
                    self.bacnet.close()
                self.bacnet = None

        this_device = DeviceObject(
            objectName=config.bacnetName,
            objectIdentifier=config.bacnetIdentifier,
            vendorIdentifier=15,
            maxApduLengthAccepted=1476,  # was like that in ye olden scriptures
        )

        self.bacnet = NormalApplication(this_device, IPv4Address(config.bacnetAddress))

        self.devices = list(Device.create_from_device_configs(self, config.devices))

        await self.declare_metrics(
            {
                metric: metadata
                for device in self.devices
                for metric, metadata in device.metadata.items()
            }
        )

        self._create_host_tasks()

    async def _stop_device_tasks(self) -> None:
        assert self._device_task_stop_future is not None
        assert self._device_task is not None
        self._device_task_stop_future.set_result(None)
        try:
            await asyncio.wait_for(self._device_task, timeout=30)
        except asyncio.TimeoutError:
            # wait_for also cancels the task
            logger.error("Host tasks did not stop in time")
        self.devices = None
        self._device_task_stop_future = None
        self._device_task = None

    def _create_host_tasks(self) -> None:
        assert self.devices is not None
        assert self._device_task_stop_future is None
        assert self._device_task is None
        self._device_task_stop_future = asyncio.Future()
        self._device_task = asyncio.create_task(self._run_device_tasks())

    async def _run_device_tasks(self) -> None:
        assert self._device_task_stop_future is not None
        assert self.devices is not None
        assert self.bacnet is not None
        await asyncio.gather(
            *(
                device.task(self.bacnet, self._device_task_stop_future)
                for device in self.devices
            )
        )

    async def task(self) -> None:
        """
        Just wait for the global task_stop_future and propagate it to the host tasks.
        """
        assert self.task_stop_future is not None
        await self.task_stop_future
        await self._stop_device_tasks()
