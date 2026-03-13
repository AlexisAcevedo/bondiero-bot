"""
Integration test: validates the new ETA logic with real CABA API data.
Tests tripUpdates (with geographic matching), vehiclePositions, direction filtering, and deduplication.
Also tests: feed latency tracking, time-of-day fallback speed, and bus bunching detection.
"""

import asyncio
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()

import sys

sys.path.insert(0, os.path.dirname(__file__))
from bot import (
    haversine,
    get_nearest_stops,
    fetch_trip_updates,
    fetch_realtime_vehicles,
    get_etas_for_stops,
    calculate_eta_speed,
    calculate_eta_linear,
    get_fallback_speed_kmh,
    detect_bunching,
    DB_NAME,
)


async def test_full_flow():
    """Simulate a real user query: line 132 near Rivadavia 4296."""
    from geopy.geocoders import Nominatim

    print("=" * 60)
    print("TEST: Full ETA Flow — Línea 132, Rivadavia 4296")
    print("=" * 60)

    geolocator = Nominatim(user_agent="bondiero_test_eta")
    loc = geolocator.geocode(
        "rivadavia 4296, Ciudad Autónoma de Buenos Aires, Argentina", timeout=10
    )
    if not loc:
        print("❌ FAIL: Could not geocode address")
        return False
    print(f"\n✅ Geocoded: {loc.latitude}, {loc.longitude}")

    stops = get_nearest_stops("132", loc.latitude, loc.longitude)
    if not stops:
        print("❌ FAIL: No stops found for line 132")
        return False
    print(f"✅ Found {len(stops)} stops (one per direction)")
    for s in stops:
        dist = haversine(loc.latitude, loc.longitude, s["lat"], s["lon"])
        print(
            f"   Dir {s['direction_id']}: {s['stop_name']} → {s['headsign']} ({dist:.2f} km)"
        )

    print("\n--- Fetching ETAs ---")
    eta_data = await get_etas_for_stops(stops)

    all_good = True
    for stop in stops:
        data = eta_data.get(stop["stop_id"], {"etas": [], "source": "none"})
        etas = data["etas"]
        source = data["source"]
        headsign = stop["headsign"].title() if stop["headsign"] else "?"
        print(f"\n📍 Hacia {headsign} (dir {stop['direction_id']})")
        print(f"   Parada: {stop['stop_name']} (stop_id: {stop['stop_id']})")
        print(f"   Source: {source}")
        print(f"   ETAs: {etas}")

        if len(etas) != len(set(etas)):
            print("   ❌ DUPLICATE ETAs DETECTED!")
            all_good = False
        else:
            print("   ✅ No duplicates")

        for e in etas:
            if e < 0 or e > 120:
                print(f"   ❌ Unreasonable ETA: {e} min")
                all_good = False

    return all_good


async def test_trip_updates_geo_matching():
    """Test tripUpdates with geographic matching of stop IDs."""
    print("\n" + "=" * 60)
    print("TEST: tripUpdates Geographic Matching")
    print("=" * 60)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT route_id FROM routes WHERE route_short_name LIKE '132%'")
    route_ids = [r[0] for r in c.fetchall()]
    conn.close()

    # Build fake stops like get_nearest_stops would return
    from geopy.geocoders import Nominatim

    geolocator = Nominatim(user_agent="bondiero_test_eta2")
    loc = geolocator.geocode(
        "rivadavia 4296, Ciudad Autónoma de Buenos Aires, Argentina", timeout=10
    )
    stops = get_nearest_stops("132", loc.latitude, loc.longitude)

    print(f"  Route IDs: {route_ids}")
    print(
        f"  Stops: {[(s['stop_id'], s['stop_name'], s['direction_id']) for s in stops]}"
    )

    results, age = await fetch_trip_updates(route_ids, stops)
    print(f"  tripUpdates results: {len(results)} entries, feed age: {age}s")
    for stop_id, etas in results.items():
        print(f"    stop {stop_id} → {etas} min")

    if results:
        print("  ✅ tripUpdates found matches via geographic matching!")
    else:
        print("  ⚠️  No tripUpdates matches (may be normal at this hour)")

    return True


async def test_vehicle_positions_isolation():
    """Test vehiclePositions with direction filtering."""
    print("\n" + "=" * 60)
    print("TEST: vehiclePositions Direction Filtering")
    print("=" * 60)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT route_id FROM routes WHERE route_short_name LIKE '132%'")
    route_ids = [r[0] for r in c.fetchall()]
    conn.close()

    vehicles, age = await fetch_realtime_vehicles(route_ids)
    print(f"  Total vehicles for line 132: {len(vehicles)}, feed age: {age}s")

    dir_0 = [v for v in vehicles if v["direction_id"] == 0]
    dir_1 = [v for v in vehicles if v["direction_id"] == 1]
    dir_none = [v for v in vehicles if v["direction_id"] is None]
    print(f"  Direction 0: {len(dir_0)}")
    print(f"  Direction 1: {len(dir_1)}")
    print(f"  No direction: {len(dir_none)}")

    vehicle_ids = [v["vehicle_id"] for v in vehicles]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        print("  ❌ DUPLICATE vehicle IDs!")
        return False
    print("  ✅ No duplicate vehicles")
    return True


async def test_eta_helpers():
    """Test helper calculation functions."""
    print("\n" + "=" * 60)
    print("TEST: ETA Helper Functions")
    print("=" * 60)

    eta = calculate_eta_speed(5.0, 30 / 3.6)
    assert eta == 10, f"Expected 10, got {eta}"
    print(f"  ✅ Speed-based: 5km at 30km/h = {eta} min")

    eta = calculate_eta_speed(5.0, 0)
    assert eta is None, f"Expected None, got {eta}"
    print("  ✅ Speed 0 returns None")

    eta = calculate_eta_linear(3.0)
    assert eta >= 1, f"Expected >= 1, got {eta}"
    print(f"  ✅ Linear: 3km at time-of-day speed = {eta} min")

    eta = calculate_eta_linear(0.05)
    assert eta >= 1, f"Expected >= 1, got {eta}"
    print("  ✅ Minimum ETA is 1 min")

    return True


async def test_fallback_speed_by_hour():
    """Test that get_fallback_speed_kmh returns sensible values for each time band."""
    print("\n" + "=" * 60)
    print("TEST: Fallback Speed by Hour")
    print("=" * 60)

    speed = get_fallback_speed_kmh()
    assert 10.0 <= speed <= 35.0, f"Speed {speed} out of plausible range"
    print(f"  ✅ Current hour speed: {speed} km/h (within plausible range)")

    expected_speeds = {14.0, 22.0, 13.0, 28.0}
    assert speed in expected_speeds, (
        f"Speed {speed} not in expected set {expected_speeds}"
    )
    print(f"  ✅ Speed belongs to expected set {expected_speeds}")

    return True


async def test_bunching_detection():
    """Test detect_bunching with controlled vehicle data."""
    print("\n" + "=" * 60)
    print("TEST: Bus Bunching Detection")
    print("=" * 60)

    # Two buses, same route+direction, ~200m apart (< 300m threshold) → bunching
    bunched = [
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6000,
            "longitude": -58.4500,
        },
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6010,
            "longitude": -58.4510,
        },
    ]
    assert detect_bunching(bunched) is True, "Expected bunching=True"
    print("  ✅ Bunching detected for buses ~200m apart")

    # Two buses, same route+direction, ~2km apart → no bunching
    spread = [
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6000,
            "longitude": -58.4500,
        },
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6200,
            "longitude": -58.4700,
        },
    ]
    assert detect_bunching(spread) is False, "Expected bunching=False"
    print("  ✅ No bunching for buses ~2km apart")

    # Opposite directions → no bunching even if close
    opposite_dirs = [
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6000,
            "longitude": -58.4500,
        },
        {
            "route_id": "100",
            "direction_id": 1,
            "latitude": -34.6001,
            "longitude": -58.4501,
        },
    ]
    assert detect_bunching(opposite_dirs) is False, (
        "Expected bunching=False for opposite dirs"
    )
    print("  ✅ No bunching for opposite directions")

    # Single vehicle → no bunching
    single = [
        {
            "route_id": "100",
            "direction_id": 0,
            "latitude": -34.6000,
            "longitude": -58.4500,
        }
    ]
    assert detect_bunching(single) is False, (
        "Expected bunching=False for single vehicle"
    )
    print("  ✅ No bunching with single vehicle")

    return True


async def test_feed_latency():
    """Test that get_etas_for_stops returns data_age_sec for each stop."""
    print("\n" + "=" * 60)
    print("TEST: Feed Latency Tracking")
    print("=" * 60)

    from geopy.geocoders import Nominatim

    geolocator = Nominatim(user_agent="bondiero_test_latency")
    loc = geolocator.geocode(
        "rivadavia 4296, Ciudad Autónoma de Buenos Aires, Argentina", timeout=10
    )
    if not loc:
        print("  ⚠️  Could not geocode — skipping latency test")
        return True

    stops = get_nearest_stops("132", loc.latitude, loc.longitude)
    if not stops:
        print("  ⚠️  No stops found — skipping latency test")
        return True

    eta_data = await get_etas_for_stops(stops)
    all_good = True
    for stop in stops:
        data = eta_data.get(stop["stop_id"], {})
        age = data.get("data_age_sec")
        headsign = stop["headsign"].title() if stop["headsign"] else "?"
        print(f"  Hacia {headsign}: data_age_sec = {age}")

        if age is not None:
            if age < 0:
                print(f"  ❌ Negative age ({age}s)")
                all_good = False
            elif age > 600:
                print(f"  ⚠️  Very stale feed ({age}s)")
            else:
                print(f"  ✅ Feed age reasonable ({age}s)")
        else:
            print("  ℹ️  age=None (no feed timestamp for this source)")
    return all_good


async def main():
    print("Bondiero Bot — ETA Integration Tests")
    print()

    results = []
    results.append(("ETA Helpers", await test_eta_helpers()))
    results.append(("Fallback Speed by Hour", await test_fallback_speed_by_hour()))
    results.append(("Bus Bunching Detection", await test_bunching_detection()))
    results.append(("Feed Latency Tracking", await test_feed_latency()))
    results.append(("tripUpdates Geo Matching", await test_trip_updates_geo_matching()))
    results.append(
        ("vehiclePositions Direction", await test_vehicle_positions_isolation())
    )
    results.append(("Full ETA Flow", await test_full_flow()))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_pass = False

    print(f"\n{'All tests passed!' if all_pass else 'Some tests FAILED!'}")
    return all_pass


if __name__ == "__main__":
    asyncio.run(main())
