"""Entrypoint for the authenticated public API."""

import uvicorn

from autocamtracker.api.public_app import create_public_app
from autocamtracker.api.secrets import PublicApiSettings


def main() -> None:
    settings = PublicApiSettings.from_env()
    uvicorn.run(
        create_public_app(settings),
        host="0.0.0.0",
        port=8080,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
