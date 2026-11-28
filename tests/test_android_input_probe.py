"""Failed or incomplete producers must not be presented as zero input events."""
import json

import pytest

from tools.research.android_input_probe import InputProbeError, parse_counts


def output(**changes):
    return {"syn_reports": 0, "x_records": 0, "y_records": 0,
            "contact_starts": 0, "contact_ends": 0,
            "producer_status": 124, "status_markers": 1, **changes}


def test_bounded_zero_sample_is_a_counter_result_not_a_failed_producer():
    value = output()
    assert parse_counts(json.dumps(value)) == value


def test_measured_device_status_requires_the_explicit_calibration_result():
    value = output(producer_status=142)
    with pytest.raises(InputProbeError, match="deadline"):
        parse_counts(json.dumps(value))
    assert parse_counts(json.dumps(value), expected_status=142) == value
    with pytest.raises(InputProbeError, match="deadline"):
        parse_counts(json.dumps(output()), expected_status=142)


@pytest.mark.parametrize("status", [-1, 0, 137, True])
def test_arbitrary_exit_status_cannot_be_declared_a_successful_timeout(status):
    with pytest.raises(InputProbeError, match="calibrated"):
        parse_counts(json.dumps(output()), expected_status=status)


def test_coordinate_and_keyboard_payloads_are_not_accepted_as_counter_fields():
    with pytest.raises(InputProbeError, match="fields differ"):
        parse_counts(json.dumps(output(x=300, key="sample")))


@pytest.mark.parametrize("changes", [
    {"producer_status": 0}, {"producer_status": 1}, {"producer_status": True},
    {"status_markers": 0}, {"status_markers": 2}, {"status_markers": True},
    {"x_records": -1}, {"x_records": 100_001}, {"x_records": True},
])
def test_failed_or_malformed_capture_is_not_a_valid_zero_sample(changes):
    with pytest.raises(InputProbeError):
        parse_counts(json.dumps(output(**changes)))


@pytest.mark.parametrize("raw", ["", "not json", "null", "[]", "{}", "x" * 4097])
def test_non_counter_output_is_rejected(raw):
    with pytest.raises(InputProbeError):
        parse_counts(raw)
