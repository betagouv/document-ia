from pydantic import Field

from document_ia_infra.data.data_settings import AnalyticsDatabaseSettings


class ReplicateAnalyticsSettings(AnalyticsDatabaseSettings):
    """Settings for the analytics replication task.

    Inherits the analytics destination connection settings (ANALYTICS_* env
    vars) and adds task-specific tuning.
    """

    EVENT_BATCH_SIZE: int = Field(
        default=2000,
        description="Number of events replicated per keyset-paged bulk insert",
        validation_alias="ANALYTICS_EVENT_BATCH_SIZE",
    )


replicate_analytics_settings = ReplicateAnalyticsSettings()
