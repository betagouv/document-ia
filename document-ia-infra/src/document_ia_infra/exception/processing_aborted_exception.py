class ProcessingAbortedException(Exception):
    """Levée lorsqu'une écriture est tentée après l'avortement du traitement courant.

    Le watchdog a fencé cette tentative (délai d'étape ou d'exécution dépassé, bail
    d'exécution expiré). Un effet de bord persistant ne doit pas être écrit après
    coup, même si l'I/O reprend après un blocage : la tentative a été remplacée.
    """

    def __init__(self, detail: str = "") -> None:
        message = "Processing was aborted; refusing to persist"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)
