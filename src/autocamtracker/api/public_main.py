"""Entrypoint for the authenticated public API."""

import uvicorn
from sqlalchemy import create_engine

from autocamtracker.api.public_app import create_public_app
from autocamtracker.api.secrets import PublicApiSettings
from autocamtracker.cloud.advanced import (
    BenchmarkSubmissionService,
    GoogleCloudRunBenchmarkLauncher,
    GooglePubSubPublisher,
    ModelRegistryService,
    PostgresAdvancedControlStore,
)


def main() -> None:
    settings = PublicApiSettings.from_env()
    advanced_engine = None
    benchmark_submissions = None
    model_registry = None
    if not settings.stateless_mode:
        advanced_engine = create_engine(settings.database_url, pool_pre_ping=True)
        advanced_store = PostgresAdvancedControlStore(advanced_engine)
        publisher = GooglePubSubPublisher(settings.firebase_project_id)
        benchmark_submissions = BenchmarkSubmissionService(
            advanced_store,
            GoogleCloudRunBenchmarkLauncher(
                settings.firebase_project_id,
                cpu_region=settings.cloud_region,
                gpu_region=settings.gpu_region,
            ),
            publisher,
        )
        model_registry = ModelRegistryService(advanced_store, publisher)
    app = create_public_app(
        settings,
        benchmark_submissions=benchmark_submissions,
        model_registry=model_registry,
    )
    if advanced_engine is not None:
        @app.on_event("shutdown")
        def close_advanced_engine() -> None:
            advanced_engine.dispose()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
