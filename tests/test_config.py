import pytest
from pydantic import ValidationError

from metricq_source_bacpypes import config_model


def test_simple() -> None:
    source = config_model.Source(
        **{
            "interval": "100ms",
            "bacnetAddress": "123.45.67.89",
            "devices": [
                {
                    "address": "test[1-3]",
                    "prefix": "example.test[1-3]",
                    "description": "Test",
                    "groups": [
                        {
                            "metrics": {
                                "foo": {
                                    "identifier": "analogValue:190",
                                    "description": "Some foo example",
                                    "unit": "W",
                                }
                            }
                        }
                    ],
                },
            ],
        }
    )
    assert source.devices[0].groups[0].metrics["foo"].identifier == "analogValue:190"


def test_minimal() -> None:
    """Not actually semantically valid because of missing interval"""
    config_model.Source(
        **{
            "_ref": "abcd",
            "_rev": "efgh",
            "bacnetAddress": "123.45.67.89",
            "devices": [
                {
                    "address": "test",
                    "prefix": "example.test",
                    "groups": [
                        {
                            "metrics": {
                                "foo": {
                                    "identifier": "analogValue:123",
                                }
                            }
                        }
                    ],
                },
            ],
        }
    )


def test_long() -> None:
    config_model.Source(
        **{
            "interval": "100ms",
            "bacnetAddress": "123.45.67.89",
            "devices": [
                {
                    "address": "test",
                    "prefix": "example.test",
                    "description": "Test",
                    "groups": [
                        {
                            "metrics": {
                                "foo.power": {
                                    "identifier": "analogValue:123",
                                    "description": "Some foo example",
                                    "unit": "W",
                                }
                            }
                        },
                        {
                            "metrics": {
                                "bar.power": {
                                    "identifier": "analogValue:143",
                                    "description": "Some bar example",
                                    "unit": "W",
                                }
                            }
                        },
                    ],
                },
                {
                    "address": "toast",
                    "prefix": "example.toast",
                    "description": "Nice and crispy",
                    "groups": [
                        {
                            "interval": "200ms",
                            "metrics": {
                                "foo.power": {
                                    "identifier": "analogValue:123",
                                    "description": "Some foo example",
                                    "unit": "W",
                                },
                                "bar.power": {
                                    "identifier": "analogValue:124",
                                    "description": "Some bar example",
                                    "unit": "W",
                                },
                            },
                        }
                    ],
                },
            ],
        }
    )


def test_extra() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "hosts": [
                    {
                        "hosts": "test[1-3]",
                        "names": "example.test[1-3]",
                        "slave_id": 1,
                        "groups": [
                            {
                                "metrics": {
                                    "foo": {
                                        "address": 0,
                                        "descryption": "Find the tpyo",
                                    }
                                }
                            }
                        ],
                    },
                ],
            }
        )


def test_missing_address() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "interval": "100ms",
                "hosts": [
                    {
                        "hosts": "test[1-3]",
                        "names": "example.test[1-3]",
                        "slave_id": 1,
                        "groups": [{"metrics": {"foo": {}}}],
                    },
                ],
            }
        )


def test_wrong_address_type() -> None:
    """Pydantic will convert wrong types if possible"""
    config = config_model.Source(
        **{
            "interval": "100ms",
            "bacnetAddress": "123.45.67.89",
            "devices": [
                {
                    "address": "test",
                    "prefix": "example.test",
                    "groups": [{"metrics": {"foo": {"identifier": "analogValue:123"}}}],
                },
            ],
        }
    )
    assert config.devices[0].groups[0].metrics["foo"].identifier == "analogValue:123"
    assert isinstance(config.devices[0].groups[0].metrics["foo"].identifier, str)


def test_invalid_address() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "interval": "100ms",
                "hosts": [
                    {
                        "hosts": "test[1-3]",
                        "names": "example.test[1-3]",
                        "groups": [{"metrics": {"foo": {"address": ""}}}],
                    },
                ],
            }
        )


def test_empty_metrics() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "interval": "100ms",
                "hosts": [
                    {
                        "hosts": "test[1-3]",
                        "names": "example.test[1-3]",
                        "slave_id": 1,
                        "groups": [{"metrics": {}}],
                    },
                ],
            }
        )


def test_empty_groups() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "interval": "100ms",
                "hosts": [
                    {
                        "hosts": "test[1-3]",
                        "names": "example.test[1-3]",
                        "slave_id": 1,
                        "groups": [],
                    },
                ],
            }
        )


def test_empty_hosts() -> None:
    with pytest.raises(ValidationError):
        config_model.Source(
            **{
                "interval": "100ms",
                "hosts": [],
            }
        )
