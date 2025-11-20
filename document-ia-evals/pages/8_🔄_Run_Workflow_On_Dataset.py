# Standard library imports
import asyncio
import base64
import io
import json
import queue
import threading
import time
from typing import Any, List
from urllib.parse import urlparse, parse_qs

# Third-party imports
import boto3
from document_ia_evals.utils.label_studio import dict_to_annotation_result
import streamlit as st
from botocore.exceptions import ClientError
from label_studio_sdk import LabelStudio
from label_studio_sdk.types import Project

# Local imports
from document_ia_evals.utils.config import config
from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_schemas import SupportedDocumentType

def download_from_s3(s3_url: str) -> tuple[bytes, str] | None:
    """Download a file from S3 given an s3:// URL.
    
    Args:
        s3_url: S3 URL in format s3://bucket/key
        
    Returns:
        Tuple of (file_content, filename) or None if failed
    """
    try:
        # Parse s3:// URL
        if not s3_url.startswith('s3://'):
            raise ValueError(f"Invalid S3 URL: {s3_url}")
        
        # Remove s3:// prefix and split bucket/key
        path = s3_url[5:]  # Remove 's3://'
        parts = path.split('/', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid S3 URL format: {s3_url}")
        
        bucket, key = parts
        
        # Initialize S3 client
        s3_client = boto3.client(  # type: ignore
            's3',
            endpoint_url=config.S3_ENDPOINT,
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_KEY,
            region_name=config.S3_REGION
        )
        
        # Download file
        response = s3_client.get_object(Bucket=bucket, Key=key)
        file_content = response['Body'].read()
        
        # Extract filename from key
        filename = key.split('/')[-1]
        
        return file_content, filename
        
    except Exception as e:
        st.error(f"Failed to download {s3_url}: {e}")
        return None


def process_task(
    task: Any,  # Task object from Label Studio SDK
    workflow_id: str,
    api_key: str,
    ls_client: LabelStudio,
    project_id: int,
    callback: queue.Queue[tuple[int, bool, str | None, str | None]],
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
) -> None:
    """Process a single task: download file, execute workflow, create annotation."""
    task_id = task.id
    error_msg: str | None = None
    execution_id: str | None = None
    
    try:
        # Get URL from task data
        pdf_url = task.data.get('pdf') if task.data else None
        if not pdf_url:
            error_msg = "No PDF URL found in task data"
            callback.put((task_id, False, error_msg, execution_id))
            return
        
        # Extract and decode the S3 URL from fileuri parameter
        s3_url = pdf_url
        
        if 'fileuri=' in pdf_url:
            # Extract fileuri parameter value
            parsed = urlparse(pdf_url)
            query_params = parse_qs(parsed.query)
            fileuri_encoded = query_params.get('fileuri', [None])[0]
            
            if fileuri_encoded:
                try:
                    # Add padding if needed for base64
                    missing_padding = len(fileuri_encoded) % 4
                    if missing_padding:
                        fileuri_encoded += '=' * (4 - missing_padding)
                    s3_url = base64.b64decode(fileuri_encoded).decode('utf-8')
                except Exception as e:
                    error_msg = f"Failed to decode fileuri parameter: {e}"
                    callback.put((task_id, False, error_msg, execution_id))
                    return
        elif not pdf_url.startswith('s3://'):
            # Try to decode if it's base64 encoded directly
            try:
                missing_padding = len(pdf_url) % 4
                if missing_padding:
                    pdf_url += '=' * (4 - missing_padding)
                s3_url = base64.b64decode(pdf_url).decode('utf-8')
            except Exception:
                # If decoding fails, use as-is
                pass
        
        # Download file from S3
        download_result = download_from_s3(s3_url)
        if not download_result:
            error_msg = f"Failed to download file from {s3_url}"
            callback.put((task_id, False, error_msg, execution_id))
            return
        
        file_content, filename = download_result
        
        # Determine content type from filename
        if filename.lower().endswith('.pdf'):
            content_type = 'application/pdf'
        elif filename.lower().endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif filename.lower().endswith('.png'):
            content_type = 'image/png'
        else:
            content_type = 'application/octet-stream'
        
        # Create file-like object for API (matching the working implementation)
        file_obj = io.BytesIO(file_content)
        file_obj.name = filename
        file_obj.type = content_type  # type: ignore  # Add type attribute like UploadedFile
        
        # Execute workflow
        st.info(f"Task {task_id}: Executing workflow '{workflow_id}' on file '{filename}'")
        workflow_execute_response = execute_workflow(
            workflow_id,
            file_obj,
            api_key,
            extraction_parameters=extraction_parameters,
        )
        
        execution_id = workflow_execute_response.data.get("execution_id")
        if not execution_id:
            error_msg = "Failed to get execution_id from workflow response"
            callback.put((task_id, False, error_msg, execution_id))
            return
        
        execution_details = wait_for_execution(execution_id, api_key)
        
        # Check status
        if not execution_details or execution_details.status.upper() != "SUCCESS":
            error_msg = f"Workflow failed with status: {execution_details.status if execution_details else 'unknown'} (execution_id: {execution_id})"
            callback.put((task_id, False, error_msg, execution_id))
            return
        
        # Extract the result from execution details
        workflow_data = execution_details.data
        if 'result' not in workflow_data:
            error_msg = f"Invalid workflow result structure (execution_id: {execution_id})"
            callback.put((task_id, False, error_msg, execution_id))
            return
        
        # Get extracted fields from the new workflow structure
        result_data = workflow_data['result']
        
        # Extract properties from extraction.properties array
        annotation_data: dict[str, Any] = {}
        if 'extraction' in result_data and 'properties' in result_data['extraction']:
            # Convert array of {name, value, type} objects to dict
            properties_array = result_data['extraction']['properties']
            for prop in properties_array:
                if 'name' in prop and 'value' in prop:
                    annotation_data[prop['name']] = prop['value']
        
        # Create prediction result
        prediction_result = dict_to_annotation_result(annotation_data)
        
        # Create prediction in Label Studio using the predictions API
        ls_client.predictions.create(  # type: ignore
            task=task_id,
            result=prediction_result,
            model_version=model_version or workflow_id
        )
        
        callback.put((task_id, True, None, execution_id))
        
    except Exception as e:
        error_msg = str(e)
        callback.put((task_id, False, error_msg, execution_id))


def consumer(
    task_queue: queue.Queue[Any],  # Queue of Task objects
    workflow_id: str,
    api_key: str,
    ls_client: LabelStudio,
    project_id: int,
    callback: queue.Queue[tuple[int, bool, str | None, str | None]],
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
) -> None:
    """Consumer thread to process tasks."""
    while True:
        try:
            task = task_queue.get(block=False)
        except queue.Empty:
            return
        
        process_task(task, workflow_id, api_key, ls_client, project_id, callback, model_version, extraction_parameters)


def run_workflow_on_dataset(
    workflow_id: str,
    project_id: int,
    api_key: str,
    ls_client: LabelStudio,
    n_workers: int = 5,
    model_version: str | None = None,
    extraction_parameters: dict[str, Any] | None = None,
) -> dict[int, dict[str, Any]]:
    """Run workflow on all tasks in a Label Studio project."""
    
    # Get all tasks from the project
    # project = ls_client.get_project(project_id)  # type: ignore
    tasks = [task for task in ls_client.tasks.list(project=project_id, fields='all')]
    
    if not tasks:
        st.warning("No tasks found in the selected dataset.")
        return {}
    
    results: dict[int, dict[str, Any]] = {}
    
    with st.spinner(f"Processing {len(tasks)} tasks...", show_time=True):
        pbar = st.progress(0, text="Executing workflows and creating annotations...")
        threads: list[threading.Thread] = []
        task_queue: queue.Queue[Any] = queue.Queue()  # Queue of Task objects
        callback: queue.Queue[tuple[int, bool, str | None, str | None]] = queue.Queue()
        
        # Fill task queue
        for task in tasks:
            task_queue.put(task)
        
        # Start worker threads
        for _ in range(min(n_workers, len(tasks))):
            t = threading.Thread(
                target=consumer,
                args=(task_queue, workflow_id, api_key, ls_client, project_id, callback, model_version, extraction_parameters),
                daemon=True
            )
            t.start()
            threads.append(t)
        
        # Collect results
        for i in range(len(tasks)):
            task_id, success, error, execution_id = callback.get()
            results[task_id] = {
                'success': success,
                'error': error,
                'execution_id': execution_id
            }
            pbar.progress((i + 1) / len(tasks))
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
    
    return results


def main() -> None:
    title = "Exécuter un workflow sur un dataset"
    st.set_page_config(page_title=title, page_icon="🔄")
    st.title(title)
    
    st.markdown("""
    Cette page vous permet d'exécuter un workflow sur tous les fichiers d'un dataset Label Studio existant :
    1. Sélection du workflow à exécuter
    2. Sélection du dataset Label Studio
    3. Exécution du workflow sur chaque fichier
    4. Création d'une nouvelle annotation avec les résultats
    """)
    
    # Check API key
    api_key = config.DOCUMENT_IA_API_KEY
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY environment variable is not set.")
        return
    
    # Check S3 configuration
    s3_vars = {
        'S3_ENDPOINT': config.S3_ENDPOINT,
        'S3_ACCESS_KEY': config.S3_ACCESS_KEY,
        'S3_SECRET_KEY': config.S3_SECRET_KEY,
        'S3_BUCKET_NAME': config.S3_BUCKET_NAME,
        'S3_REGION': config.S3_REGION
    }
    missing_s3 = [var for var, val in s3_vars.items() if not val]
    if missing_s3:
        st.warning(f"⚠️ Missing S3 configuration: {', '.join(missing_s3)}")
        return
    
    # Check Label Studio configuration
    label_studio_url = config.LABEL_STUDIO_URL
    label_studio_api_key = config.LABEL_STUDIO_API_KEY
    
    if not label_studio_url or not label_studio_api_key:
        st.warning("⚠️ LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY must be set")
        return
    
    # Initialize Label Studio client
    ls_client = LabelStudio(base_url=label_studio_url, api_key=label_studio_api_key)
    
    # Fetch workflows
    workflows_list = asyncio.run(workflow_repository.get_all_workflows())
    
    if not workflows_list:
        st.error("❌ No workflows found")
        return
    
    # Workflow selector
    workflow_options = {w.id: f"{w.name} (v{w.version})" for w in workflows_list}
    selected_workflow_id = st.selectbox(
        "Sélectionnez un workflow",
        options=list(workflow_options.keys()),
        format_func=lambda x: workflow_options[x],
        index=0,
    )
    
    # Display workflow details
    selected_workflow = next(w for w in workflows_list if w.id == selected_workflow_id)
    with st.expander("Détails du workflow"):
        st.write(f"**Description:** {selected_workflow.description}")
        st.write(f"**Steps:** {', '.join(selected_workflow.steps)}")
        st.write(f"**Model:** {selected_workflow.llm_model}")
        st.write(f"**Supported file types:** {', '.join(selected_workflow.supported_file_types)}")
    
    # Check if it's a fast workflow
    is_fast_workflow = "-fast" in selected_workflow_id or "fast" in selected_workflow_id.lower()
    
    # Document type selector (for fast workflows)
    doc_type_options = list(SupportedDocumentType)
    selected_doc_type: SupportedDocumentType = st.selectbox(
        "Type de document (requis pour les workflows fast)",
        options=doc_type_options,
        format_func=lambda x: x.name.replace("_", " ").title(),
        index=0,
        help="Spécifiez le type de document pour les workflows qui n'incluent pas de classification"
    )
    
    # Show extraction parameters info for fast workflows
    if is_fast_workflow:
        extraction_params_preview = {"document-type": selected_doc_type.value}
        st.info(f"ℹ️ Workflow fast détecté - Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")
    
    # Fetch Label Studio projects
    try:
        projects = ls_client.projects.list()  # type: ignore
        
        if not projects:
            st.warning("⚠️ No Label Studio projects found")
            return
        # Project selector
        project_options = {p.id: p.title or f"Project {p.id}" for p in projects}
        selected_project_id: int = st.selectbox(
            "Sélectionnez un dataset Label Studio",
            options=list(project_options.keys()),
            format_func=lambda x: project_options[x],
            index=0,
        )
        
        # Display project details
        selected_project = next(p for p in projects if p.id == selected_project_id)
        with st.expander("Détails du dataset"):
            st.write(f"**Title:** {selected_project.title}")
            st.write(f"**Description:** {selected_project.description or 'N/A'}")
            
            # Get task count
            s = ls_client.projects.get(selected_project_id)  # type: ignore
            tasks = [task for task in ls_client.tasks.list(project=selected_project_id, fields='all')]  # type: ignore
            st.write(f"**Number of tasks:** {len(tasks)}")
        
    except Exception as e:
        st.error(f"❌ Failed to fetch Label Studio projects: {e}")
        return
    
    # Number of workers
    n_workers = st.number_input(
        "Nombre de tâches à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )
    
    # Model version / annotation name
    model_version = st.text_input(
        "Nom de l'annotation (model version)",
        value=selected_workflow_id,
        help="Nom affiché pour cette annotation dans Label Studio. Par défaut: ID du workflow"
    )
    
    # Run workflow button
    if st.button("Lancer l'exécution du workflow", type="primary"):
        # Prepare extraction parameters for fast workflows
        extraction_parameters = None
        if is_fast_workflow:
            extraction_parameters = {"document-type": selected_doc_type.value}
        
        st.info(f"🚀 Exécution du workflow '{selected_workflow.id}' sur le dataset '{project_options[selected_project_id]}'...")
        
        processing_results = run_workflow_on_dataset(
            workflow_id=selected_workflow_id,
            project_id=selected_project_id,
            api_key=api_key,
            ls_client=ls_client,
            n_workers=n_workers,
            model_version=model_version if model_version else None,
            extraction_parameters=extraction_parameters,
        )
        
        # Show results
        if processing_results:
            success_count = sum(1 for r in processing_results.values() if r['success'])
            st.success(f"✅ {success_count}/{len(processing_results)} tâches traitées avec succès")
            
            if success_count < len(processing_results):
                st.warning("⚠️ Certaines tâches n'ont pas pu être traitées:")
                for task_id, result in processing_results.items():
                    if not result['success']:
                        execution_id = result.get('execution_id', 'N/A')
                        st.error(f"- Task {task_id}: {result['error']}")
                        if execution_id != 'N/A':
                            st.info(f"  Execution ID: `{execution_id}`")
            
            # Display project link
            project_url = f"{label_studio_url}/projects/{selected_project_id}"
            st.markdown(f"🔗 [Voir les annotations dans Label Studio]({project_url})")
            
            # Show detailed results
            with st.expander("Détails des résultats"):
                st.json(processing_results)


if __name__ == "__main__":
    main()