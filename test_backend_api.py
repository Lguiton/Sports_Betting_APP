import requests

url = "http://localhost:8000/chat/sports"
payload = {
    "message": "Analyze the spread and calculate the +EV market edge, Poisson Matchup, and optimal Kelly Criterion sizing for the cowboys vs eagles game",
    "thread_id": "default_session",
    "bankroll": 1000,
    "risk_profile": "Moderate"
}

# NOTE: /chat/sports is a Server-Sent Events (SSE) stream, not a single JSON
# response -- response.json() will fail against it. Read it line-by-line
# like the frontend does instead.
with requests.post(url, json=payload, stream=True) as response:
    response.raise_for_status()
    print(f"Status: {response.status_code}\n")
    for line in response.iter_lines(decode_unicode=True):
        if line:
            print(line)
