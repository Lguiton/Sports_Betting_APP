import requests
import json

url = "http://localhost:8000/chat/sports"
payload = {
    "message": "Analyze the spread and calculate the +EV market edge, Poisson Matchup, and optimal Kelly Criterion sizing for the cowboys vs eagles game",
    "thread_id": "default_session",
    "bankroll": 1000,
    "risk_profile": "Moderate"
}

response = requests.post(url, json=payload)
try:
    data = response.json()
    print("Response JSON:")
    print(json.dumps(data, indent=2))
except Exception as e:
    print("Failed to parse JSON response:", e)
    print("Raw response text:")
    print(response.text)
