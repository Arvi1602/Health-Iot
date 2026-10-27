import itertools
import json
from unittest.mock import Mock

import httpx
import pytest

from app import simulator
from app.schemas import ReadingCreate


def test_generation_bounds_schema_and_gradual_variation():
    readings = list(itertools.islice(simulator.generate_readings(42, seed=42), 2000))
    for reading in readings:
        assert set(reading) == {"patient_id", "heart_rate", "spo2", "temperature_c"}
        assert reading["patient_id"] == 42
        assert 60 <= reading["heart_rate"] <= 100
        assert 95 <= reading["spo2"] <= 100
        assert 36.0 <= reading["temperature_c"] <= 37.5
        ReadingCreate.model_validate(reading)
    for previous, current in zip(readings, readings[1:]):
        assert abs(current["heart_rate"] - previous["heart_rate"]) <= 2
        assert abs(current["spo2"] - previous["spo2"]) <= 1
        assert abs(current["temperature_c"] - previous["temperature_c"]) <= 0.100001
    assert len({tuple(reading.values()) for reading in readings}) > 1


def test_random_seed_is_deterministic():
    first = list(itertools.islice(simulator.generate_readings(9, seed=42), 20))
    second = list(itertools.islice(simulator.generate_readings(9, seed=42), 20))
    different = list(itertools.islice(simulator.generate_readings(9, seed=43), 20))
    assert first == second
    assert first != different


@pytest.fixture
def mock_http(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(simulator.time, "sleep", sleep)

    def configure(status=201, error=None):
        requests = []

        def handler(request):
            requests.append(request)
            if error:
                raise error("private connection details", request=request)
            return httpx.Response(status, text="private server details")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        factory = Mock(return_value=client)
        monkeypatch.setattr(simulator.httpx, "Client", factory)
        return requests, client, factory, sleep

    return configure


def test_finite_count_endpoint_and_success_output(mock_http, capsys):
    requests, client, factory, sleep = mock_http()
    result = simulator.main(["--patient-id", "42", "--count", "5", "--interval", "0.5",
                             "--seed", "42", "--api-url", "http://example.test/api/readings"])
    assert result == 0
    assert len(requests) == 5
    assert all(request.method == "POST" for request in requests)
    assert all(str(request.url) == "http://example.test/api/readings" for request in requests)
    expected = list(itertools.islice(simulator.generate_readings(42, seed=42), 5))
    assert [json.loads(request.content) for request in requests] == expected
    assert all(request.headers["content-type"] == "application/json" for request in requests)
    factory.assert_called_once_with(timeout=5.0, follow_redirects=False)
    assert sleep.call_count == 4
    assert all(call.args == (0.5,) for call in sleep.call_args_list)
    assert client.is_closed
    output = capsys.readouterr().out
    assert output.count("HTTP 201") == 5
    assert "[5] Patient 42" in output
    assert "private server details" not in output


@pytest.mark.parametrize("status,message", [
    (404, "patient not found"), (422, "validation failed"),
    (500, "server error"), (503, "server error"),
    (302, "Unexpected API response"), (200, "Unexpected API response"),
])
def test_http_failures_stop_without_retry(mock_http, capsys, status, message):
    requests, client, _, sleep = mock_http(status=status)
    assert simulator.main(["--patient-id", "42", "--count", "5"]) == 1
    assert len(requests) == 1
    sleep.assert_not_called()
    assert client.is_closed
    output = capsys.readouterr()
    assert message in output.err
    assert str(status) in output.err
    assert "private server details" not in output.err
    assert "HTTP 201" not in output.out


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
def test_connection_and_timeout_failure(mock_http, capsys, error):
    requests, client, _, _ = mock_http(error=error)
    assert simulator.main(["--patient-id", "42", "--count", "1"]) == 1
    assert len(requests) == 1
    assert client.is_closed
    output = capsys.readouterr().err
    assert "Unable to reach HealthGuard API" in output
    assert "private connection details" not in output
    assert "Traceback" not in output


def test_continuous_mode_ctrl_c(mock_http, capsys):
    requests, client, _, sleep = mock_http()
    sleep.side_effect = [None, None, KeyboardInterrupt()]
    assert simulator.main(["--patient-id", "42"]) == 0
    assert len(requests) == 3
    assert all(call.args == (2.0,) for call in sleep.call_args_list)
    assert client.is_closed
    assert "Simulator stopped." in capsys.readouterr().out


@pytest.mark.parametrize("args", [
    [], ["--patient-id", "0"], ["--patient-id", "-1"], ["--patient-id", "abc"],
    ["--patient-id", "1.5"], ["--patient-id", str(2**63)],
    ["--patient-id", "1", "--count", "0"], ["--patient-id", "1", "--count", "-2"],
    ["--patient-id", "1", "--count", "1.5"],
    ["--patient-id", "1", "--interval", "0"], ["--patient-id", "1", "--interval", "-1"],
    ["--patient-id", "1", "--interval", "0.001"], ["--patient-id", "1", "--interval", "nan"],
    ["--patient-id", "1", "--interval", "inf"], ["--patient-id", "1", "--interval", "abc"],
    ["--patient-id", "1", "--interval", "86401"],
    ["--patient-id", "1", "--api-url", "not-a-url"],
    ["--patient-id", "1", "--api-url", "ftp://example.test/readings"],
    ["--patient-id", "1", "--api-url", "http://user:secret@example.test/readings"],
])
def test_invalid_cli_arguments(args, capsys):
    with pytest.raises(SystemExit) as exc:
        simulator.main(args)
    assert exc.value.code == 2
    assert "error:" in capsys.readouterr().err
