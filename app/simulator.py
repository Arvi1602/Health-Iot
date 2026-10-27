"""Standalone HTTP sensor simulator. Synthetic demo values, not clinical data."""

import argparse
import math
import random
import sys
import time

import httpx

DEFAULT_API_URL = "http://127.0.0.1:8000/api/readings"


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def interval_seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number of seconds") from None
    if not math.isfinite(number) or not 0.1 <= number <= 86400:
        raise argparse.ArgumentTypeError("must be between 0.1 and 86400 seconds")
    return number


def endpoint_url(value: str) -> str:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise argparse.ArgumentTypeError("must be an absolute HTTP or HTTPS URL") from None
    if url.scheme not in ("http", "https") or not url.host:
        raise argparse.ArgumentTypeError("must be an absolute HTTP or HTTPS URL")
    if url.userinfo or url.query or url.fragment:
        raise argparse.ArgumentTypeError("use an endpoint URL without credentials, query, or fragment")
    return str(url)


def generate_readings(patient_id: int, seed: int | None = None):
    """Yield a bounded random walk using only the ingestion API's required fields."""
    rng = random.Random(seed)
    heart_rate, spo2, temperature_c = 78, 98, 36.8
    while True:
        yield {
            "patient_id": patient_id,
            "heart_rate": heart_rate,
            "spo2": spo2,
            "temperature_c": temperature_c,
        }
        heart_rate = min(100, max(60, heart_rate + rng.randint(-2, 2)))
        spo2 = min(100, max(95, spo2 + rng.choice((-1, 0, 0, 1))))
        temperature_c = round(min(37.5, max(36.0, temperature_c + rng.choice((-0.1, 0, 0.1)))), 1)


def run_simulator(patient_id: int, api_url: str, interval: float,
                  count: int | None = None, seed: int | None = None) -> int:
    print("HealthGuard Sensor Simulator — synthetic demo data only", flush=True)
    print(f"Patient: {patient_id}\nEndpoint: {api_url}\nInterval: {interval:g} seconds", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    with httpx.Client(timeout=5.0, follow_redirects=False) as client:
        for number, payload in enumerate(generate_readings(patient_id, seed), start=1):
            try:
                response = client.post(api_url, json=payload)
            except httpx.RequestError:
                print(f"Unable to reach HealthGuard API at {api_url}; request failed or timed out. No retry attempted.", file=sys.stderr)
                return 1

            if response.status_code != 201:
                if response.status_code == 404:
                    message = "Reading rejected: patient not found (check patient ID and endpoint)."
                elif response.status_code == 422:
                    message = "Reading rejected: payload validation failed."
                elif response.status_code >= 500:
                    message = "HealthGuard API server error."
                else:
                    message = "Unexpected API response; reading not confirmed."
                print(f"{message} HTTP {response.status_code}. Simulator stopped.", file=sys.stderr)
                return 1

            print(f"[{number}] Patient {patient_id} | HR: {payload['heart_rate']} bpm | "
                  f"SpO2: {payload['spo2']}% | Temp: {payload['temperature_c']:.1f}°C | HTTP 201", flush=True)
            if count is not None and number >= count:
                return 0
            time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send synthetic demo readings to HealthGuard over HTTP.")
    parser.add_argument("--patient-id", type=positive_integer, required=True, help="existing patient ID")
    parser.add_argument("--api-url", type=endpoint_url, default=DEFAULT_API_URL, help="full ingestion endpoint URL")
    parser.add_argument("--interval", type=interval_seconds, default=2.0, help="seconds between requests (0.1–86400; default: 2)")
    parser.add_argument("--count", type=positive_integer, help="number of readings; omit to run until Ctrl+C")
    parser.add_argument("--seed", type=int, help="random seed for reproducible simulation")
    args = parser.parse_args(argv)
    if args.patient_id > 9223372036854775807:
        parser.error("--patient-id exceeds the API's supported integer range")
    try:
        return run_simulator(args.patient_id, args.api_url, args.interval, args.count, args.seed)
    except KeyboardInterrupt:
        print("\nSimulator stopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
