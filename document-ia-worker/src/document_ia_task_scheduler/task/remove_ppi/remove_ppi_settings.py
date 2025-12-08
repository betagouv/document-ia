from pydantic import Field

from document_ia_infra.core.BaseDocumentIaSettings import BaseDocumentIaSettings


class RemovePPISettings(BaseDocumentIaSettings):
    EVENT_STORE_PPI_RETENTION_DAYS: int = Field(
        default=7,
        description="Number of days to retain PPI data in the event store",
        validation_alias="EVENT_STORE_PPI_RETENTION_DAYS",
    )


remove_ppi_settings = RemovePPISettings()
