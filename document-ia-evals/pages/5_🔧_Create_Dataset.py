import threading
import queue
import os
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile
from document_ia_evals.utils.api import execute_workflow, wait_for_execution, ExecutionModel


def consumer(file_queue: queue.Queue, api_key: str, callback: queue.Queue):
    """Continuously take jobs from the queue and process them."""
    while True:
        try:
            uploaded_file: UploadedFile = file_queue.get(block=False)
        except queue.Empty:
            # Stop signal
            return

        # TODO: create a dedicated workflow for dataset creation
        # in workflows.json
        #
        # This should be the same workflow as document-extraction-v1
        # but without the classification step
        # The input schema should be selectable from the streamlit app
        workflow_name = "document-extraction-v1"
        try:
            workflow_execute_response = execute_workflow(
                workflow_name,
                uploaded_file,
                api_key,
            )
        except Exception:
            callback.put((uploaded_file.name, None))
            continue

        execution_id: str = workflow_execute_response.data.get("execution_id")
        execution_details = wait_for_execution(execution_id, api_key)
        callback.put((uploaded_file.name, execution_details))


def start_dataset_annotation(n_workers: int, api_key: str, folder: list[UploadedFile]) -> dict[str, ExecutionModel | None]:
    """Start dataset annotation.

    Create a thread pool and process the uploaded files in parallel.

    Args:
        n_workers (int): Number of parallel workers.
        api_key (str): The API key for authentication.
        folder (list[UploadedFile]): List of uploaded files to process.
    """
    execution_details = {}
    with st.spinner("En cours...", show_time=True):
        pbar = st.progress(0, text="Executing workflow on files...")
        threads = []
        file_queue = queue.Queue()
        # Callback is a queue to retrieve file names and execution_details
        callback = queue.Queue()

        for file in folder:
            file_queue.put(file)

        for _ in range(min(n_workers, len(folder))):
            t = threading.Thread(target=consumer, args=(file_queue, api_key, callback), daemon=True)
            t.start()
            threads.append(t)

        for i in range(len(folder)):
            uploaded_file_name, _execution_details = callback.get()
            execution_details[uploaded_file_name] = _execution_details
            pbar.progress((i + 1) / len(folder))

        for t in threads:
            t.join()

    return execution_details


def main():
    title = "Création d'un jeu de données annoté"
    st.set_page_config(page_title=title, page_icon="📝")
    st.title(title)

    st.markdown("Cette page vous permet de créer un jeu de données en utilisant l'API de Document IA.")

    api_key = os.getenv("DOCUMENT_IA_API_KEY")
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return None

    # TODO: Using a file_uploader for development, but will replace it
    # with an S3 path later.
    folder = st.file_uploader(
        "Sélectionnez un dossier (PDF ou image)",
        accept_multiple_files="directory"
    )
    n_workers = st.number_input(
        "Nombre de documents à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )

    # TODO: Use label studio client to create a project here

    # End TODO
    if st.button("Lancer la création de dataset"):
        execution_details = start_dataset_annotation(n_workers, api_key, folder)
        st.json(execution_details)


if __name__ == "__main__":
    main()