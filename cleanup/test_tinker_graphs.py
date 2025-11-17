"""
Tinker test for mobile graphs endpoint.
This is a lightweight script (not full pytest) intended to be run manually
to verify the new `/api/mobile/graphs` endpoint returns an image when
authenticated.

Usage: run with the dev server running. It mirrors the style of `test_mobile_api.py`.
"""
import requests
import json
import urllib3

BASE_URL = "https://localhost:8080/api/mobile"
TEST_USERNAME = "Seth Herod"
TEST_PASSWORD = "5454"
TEST_TEAM_NUMBER = 5454

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def run():
	print("Requesting token...")
	resp = requests.post(f"{BASE_URL}/auth/login", json={"username": TEST_USERNAME, "team_number": TEST_TEAM_NUMBER, "password": TEST_PASSWORD}, verify=False)
	print(f"Login status: {resp.status_code}")
	try:
		data = resp.json()
	except Exception:
		print(resp.text)
		return
	if not data.get('success'):
		print('Login failed:', data)
		return
	token = data.get('token')
	headers = {"Authorization": f"Bearer {token}"}

	# Request a simple line graph for the test team
	payload = {
		"team_number": TEST_TEAM_NUMBER,
		"graph_type": "line",
		"metric": "total_points",
		"mode": "match_by_match"
	}

	print("Requesting graph image...")
	r = requests.post(f"{BASE_URL}/graphs", json=payload, headers=headers, verify=False)
	print(f"Graph status: {r.status_code}")
	if r.status_code == 200 and r.headers.get('Content-Type') == 'image/png':
		print('Received PNG image, saving to tinker_graph.png')
		with open('tinker_graph.png', 'wb') as f:
			f.write(r.content)
	else:
		try:
			print('Response:', r.json())
		except Exception:
			print('Response text:', r.text)


if __name__ == '__main__':
	run()
