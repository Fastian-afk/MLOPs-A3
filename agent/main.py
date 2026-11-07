"""Command line client for the authenticated conversational API."""

import argparse
import os

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message")
    parser.add_argument("--session", default="cli")
    parser.add_argument("--confirmation-token")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    token = os.environ.get("MLOPS_API_TOKEN", "")
    if not token:
        parser.error("Set MLOPS_API_TOKEN securely")
    response = httpx.post(
        args.url + "/agent/chat",
        timeout=120,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": args.message,
            "session_id": args.session,
            "confirmation_token": args.confirmation_token,
        },
    )
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()
