import requests

MISTY_IP = "10.42.0.197"

# Test 1 — drive/time endpoint
print("Test 1: drive/time")
r = requests.post(f"http://{MISTY_IP}/api/drive/time", json={
    "LinearVelocity": 0.3,
    "AngularVelocity": 0,
    "TimeMs": 2000
})
print(f"  Status : {r.status_code}")
print(f"  Response: {r.json()}")
print()

# Test 2 — plain drive endpoint (some firmware versions use this)
print("Test 2: drive")
r2 = requests.post(f"http://{MISTY_IP}/api/drive", json={
    "LinearVelocity": 0.3,
    "AngularVelocity": 0,
})
print(f"  Status : {r2.status_code}")
print(f"  Response: {r2.json()}")