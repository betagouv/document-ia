# Standard library imports
import asyncio
import json
import queue
import threading
import time
from typing import Any, Protocol

# Third-party imports
import boto3
from document_ia_api.api.contracts.execution.types import ExecutionStatus
from document_ia_evals.utils.label_studio import create_task, generate_label_config, get_label_studio_client_legacy
import streamlit as st
from botocore.exceptions import ClientError
from label_studio_sdk import Client
from streamlit.runtime.uploaded_file_manager import UploadedFile

# Local imports
from document_ia_evals.utils.api import execute_workflow, wait_for_execution
from document_ia_evals.utils.config import config
from document_ia_infra.data.workflow.repository.worflow import workflow_repository
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema


# Protocol for S3 client type
class S3ClientProtocol(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> Any: ...



def upload_to_s3_with_task(
    s3_client: S3ClientProtocol,
    bucket: str,
    prefix: str,
    file_id: str,
    file_content: bytes,
    content_type: str,
    ground_truth: dict[str, Any] | None = None,
    retries: int = 3,
    delay: int = 1
) -> bool:
    """Upload raw file and task JSON to S3 in Label Studio format."""
    try:
        # Determine file extension
        ext = '.pdf' if 'pdf' in content_type.lower() else '.jpg' if 'jpeg' in content_type.lower() else '.png'
        
        # Upload raw file to source subdirectory
        raw_key = f"{prefix}/source/{file_id}{ext}"
        s3_client.put_object(
            Bucket=bucket,
            Key=raw_key,
            Body=file_content,
            ContentType=content_type
        )
        
        # Create Label Studio task
        pdf_url = f"s3://{bucket}/{raw_key}"
        task_data = create_task(pdf_url=pdf_url, ground_truth=ground_truth)
        
        # Upload JSON task
        json_key = f"{prefix}/tasks/{file_id}.json"
        json_data = json.dumps(task_data, ensure_ascii=False, indent=2)
        s3_client.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json_data.encode('utf-8'),
            ContentType='application/json'
        )
        
        return True
    except ClientError as e:
        if retries > 1:
            time.sleep(delay)
            return upload_to_s3_with_task(
                s3_client, bucket, prefix, file_id, file_content,
                content_type, ground_truth, retries - 1, delay * 2
            )
        else:
            raise Exception(f"Failed to upload {file_id} to S3: {e}")

def create_label_studio_project(
    dataset_name: str,
    doc_type: SupportedDocumentType,
    s3_prefix: str
) -> dict[str, Any]:
    """Create a Label Studio project with S3 storage integration."""
    
    # Get configuration
    label_studio_url = config.LABEL_STUDIO_URL
    api_key = config.LABEL_STUDIO_API_KEY
    
    if not label_studio_url or not api_key:
        raise ValueError("LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY must be set")
    
    # Get the Pydantic model for the document type
    schema = resolve_extract_schema(doc_type.value)
    model_class = schema.document_model
    
    # Generate label config
    label_config = generate_label_config(
        model_class,
        title=f"Extraction {schema.name}"
    )
    
    # Initialize Label Studio client
    ls = get_label_studio_client_legacy()
    
    # Create project
    project = ls.create_project( # type: ignore
        title=f"{dataset_name} - {schema.name}",
        description=f"Dataset: {dataset_name}\n\n" + "\n".join(schema.description),
        label_config=label_config
    )
    
    # Configure S3 source storage
    s3_params: dict[str, Any] = {
        's3_endpoint': config.S3_ENDPOINT,
        'bucket': config.S3_BUCKET_NAME,
        'aws_access_key_id': config.S3_ACCESS_KEY,
        'aws_secret_access_key': config.S3_SECRET_KEY,
        'region_name': config.S3_REGION
    }
    
    source_storage = project.connect_s3_import_storage(**s3_params, prefix=f"{s3_prefix}/tasks", presign=True, regex_filter=r'.*\.json$', use_blob_urls=False) # type: ignore
    target_storage = project.connect_s3_export_storage(**s3_params, prefix=f"{s3_prefix}/target") # type: ignore
    
    # Sync storage to import tasks
    project.sync_import_storage('s3', source_storage['id']) # type: ignore
    # Sync storage to export tasks
    project.sync_export_storage('s3', target_storage['id']) # type: ignore
    
    return {
        'project_id': project.id, # type: ignore
        'project_title': project.params.get('title'), # type: ignore
        'source_storage_id': source_storage['id'],
        'target_storage_id': target_storage['id'],
        'task_count': len(project.get_tasks()) # type: ignore
    }


def consumer(
    file_queue: queue.Queue[UploadedFile],
    api_key: str,
    callback: queue.Queue[tuple[str, bool, str | None, str | None]],
    workflow_id: str,
    document_type: SupportedDocumentType | None = None,
    s3_prefix: str = "",
    is_fast_workflow: bool = False,
) -> None:
    """Process files: execute workflow, upload to S3 with ground truth annotations."""
    
    # Initialize S3 client
    s3_client = boto3.client(  # type: ignore
        's3',
        endpoint_url=config.S3_ENDPOINT,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        region_name=config.S3_REGION
    )
    bucket_name = config.S3_BUCKET_NAME or ''
    
    while True:
        try:
            uploaded_file: UploadedFile = file_queue.get(block=False)
        except queue.Empty:
            return
        
        file_id = uploaded_file.name.rsplit('.', 1)[0]  # Remove extension
        error_msg: str | None = None
        execution_id: str | None = None
        
        try:
            # Prepare extraction parameters for fast workflows
            extraction_parameters = None
            if is_fast_workflow and document_type:
                extraction_parameters = {"document-type": document_type.value}
            
            # Execute workflow to get ground truth
            workflow_execute_response = execute_workflow(
                workflow_id,
                uploaded_file,
                api_key,
                extraction_parameters=extraction_parameters,
            )
            
            execution_id = workflow_execute_response.data.execution_id
            if not execution_id:
                error_msg = "Failed to get execution_id from workflow response"
                callback.put((uploaded_file.name, False, error_msg, execution_id))
                continue
            execution_details = wait_for_execution(execution_id, api_key)
            
            # Check status (case-insensitive comparison)
            if not execution_details or execution_details.status != ExecutionStatus.SUCCESS:
                error_msg = f"Workflow failed with status: {execution_details} (execution_id: {execution_id})"
                callback.put((uploaded_file.name, False, error_msg, execution_id))
                continue
            
            # Extract the result from the execution details data
            workflow_data = execution_details.data

            # The properties field contains the actual extracted data
            extracted_fields = workflow_data.result.extraction
            if extracted_fields is None:
                error_msg = "Failed to get extracted_fields"
                callback.put((uploaded_file.name, False, error_msg, execution_id))
                continue

            # For dataset creation, we store the raw extracted data as ground truth
            # No validation needed - the data is the ground truth even if imperfect
            properties = extracted_fields.properties
            
            # Convert list format [{name, value, type}] to dict {name: value}
            # TODO: use annotation_results_to_dict ?
            result_data: dict[str, Any] = {
                item.name: item.value
                for item in properties
                if item.name and item.value
            }
            # Read file content
            uploaded_file.seek(0)
            file_content = uploaded_file.read()
            
            # Determine content type
            content_type = uploaded_file.type or 'application/octet-stream'
            
            # Upload to S3 with task JSON
            upload_to_s3_with_task(
                s3_client=s3_client,
                bucket=bucket_name,
                prefix=s3_prefix,
                file_id=file_id,
                file_content=file_content,
                content_type=content_type,
                ground_truth=result_data
            )
            
            callback.put((uploaded_file.name, True, None, execution_id))
            
        except Exception as e:
            error_msg = str(e)
            callback.put((uploaded_file.name, False, error_msg, execution_id))


def start_dataset_creation(
    n_workers: int,
    api_key: str,
    folder: list[UploadedFile],
    workflow_id: str,
    document_type: SupportedDocumentType | None = None,
    s3_prefix: str = "",
    is_fast_workflow: bool = False,
) -> dict[str, dict[str, Any]]:
    """Process files and upload to S3 with ground truth annotations."""
    
    results: dict[str, dict[str, Any]] = {}
    
    with st.spinner("Processing files and uploading to S3...", show_time=True):
        pbar = st.progress(0, text="Executing workflows and uploading...")
        threads: list[threading.Thread] = []
        file_queue: queue.Queue[UploadedFile] = queue.Queue()
        callback: queue.Queue[tuple[str, bool, str | None, str | None]] = queue.Queue()
        
        for file in folder:
            file_queue.put(file)
        
        for _ in range(min(n_workers, len(folder))):
            t = threading.Thread(
                target=consumer,
                args=(file_queue, api_key, callback, workflow_id, document_type, s3_prefix, is_fast_workflow),
                daemon=True
            )
            t.start()
            threads.append(t)
        
        for i in range(len(folder)):
            file_name, success, error, execution_id = callback.get()
            results[file_name] = {
                'success': success,
                'error': error,
                'execution_id': execution_id
            }
            pbar.progress((i + 1) / len(folder))
        
        for t in threads:
            t.join()
    
    return results


def main() -> None:
    title = "Création d'un jeu de données terrain"
    st.set_page_config(page_title=title, page_icon="📝")
    st.title(title)
    st.caption(f"Using: API endpoint: {config.DOCUMENT_IA_BASE_URL}, S3 endpoint: {config.S3_ENDPOINT}/{config.S3_BUCKET_NAME}, Label Studio URL: {config.LABEL_STUDIO_URL}")
    
    st.markdown("""
    Cette page vous permet de créer un jeu de données pré-annoté avec Label Studio :
    1. Upload de fichiers et exécution du workflow pour obtenir les annotations de référence
    2. Upload vers S3 au format Label Studio
    3. Création automatique du projet Label Studio
    """)
    
    # Check API key
    api_key = config.DOCUMENT_IA_API_KEY
    if not api_key:
        st.warning("⚠️ DOCUMENT_IA_API_KEY not found in configuration.")
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
    if not config.LABEL_STUDIO_URL or not config.LABEL_STUDIO_API_KEY:
        st.warning("⚠️ LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY must be set in configuration")
        return

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

    # Dataset name input
    dataset_name = st.text_input(
        "Nom du dataset",
        value="",
        placeholder="ex: tax_notices_batch_1",
        help="Nom unique pour identifier ce dataset"
    )

    # Check if it's a fast workflow
    is_fast_workflow = "-fast" in selected_workflow_id or "fast" in selected_workflow_id.lower()
    
    # Document type selector
    doc_type_options = list(SupportedDocumentType)
    selected_doc_type: SupportedDocumentType = st.selectbox(
        "Type de document",
        options=doc_type_options,
        format_func=lambda x: x.name.replace("_", " ").title(),
        index=0,
    )
    
    # Show extraction parameters info for fast workflows
    if is_fast_workflow:
        extraction_params_preview = {"document-type": selected_doc_type.value}
        st.info(f"ℹ️ Workflow fast détecté - Paramètres d'extraction qui seront envoyés: `{json.dumps(extraction_params_preview)}`")

    # S3 prefix (computed, read-only)
    s3_prefix = f"{dataset_name}_{selected_doc_type.value}" if dataset_name else ""
    st.text_input(
        "Préfixe S3",
        value=s3_prefix,
        disabled=True,
        help="Chemin où les fichiers seront stockés dans S3"
    )
    
    # File uploader
    folder = st.file_uploader(
        "Sélectionnez des fichiers (PDF ou image)",
        accept_multiple_files=True,
        type=['pdf', 'jpg', 'jpeg', 'png']
    )
    
    # Number of workers
    n_workers = st.number_input(
        "Nombre de documents à traiter en parallèle",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
    )
    
    # Create dataset button
    if st.button("Lancer la création de dataset", type="primary"):
        if not dataset_name:
            st.warning("⚠️ Veuillez entrer un nom pour le dataset.")
            return
        
        if not folder:
            st.warning("⚠️ Aucun fichier sélectionné. Veuillez choisir des fichiers.")
            return
        
        # Step 1: Process files and upload to S3
        st.info(f"📤 Étape 1/2: Traitement de {len(folder)} fichiers et upload vers S3...")
        upload_results = start_dataset_creation(
            n_workers=n_workers,
            api_key=api_key,
            folder=folder,
            workflow_id=selected_workflow_id,
            document_type=selected_doc_type,
            s3_prefix=s3_prefix,
            is_fast_workflow=is_fast_workflow,
        )
        
        # Show upload results
        success_count = sum(1 for r in upload_results.values() if r['success'])
        st.success(f"✅ {success_count}/{len(folder)} fichiers traités avec succès")
        
        if success_count < len(folder):
            st.warning("⚠️ Certains fichiers n'ont pas pu être traités:")
            print("xXxXxX = upload_results", upload_results)
            for name, result in upload_results.items():
                if not result['success']:
                    execution_id = result.get('execution_id', 'N/A')
                    st.error(f"- {name}: {result['error']}")
                    if execution_id != 'N/A':
                        st.info(f"  Execution ID: `{execution_id}`")
        
        # Step 2: Create Label Studio project
        if success_count > 0:
            st.info("📊 Étape 2/2: Création du projet Label Studio...")
            try:
                project_info = create_label_studio_project(
                    dataset_name=dataset_name,
                    doc_type=selected_doc_type,
                    s3_prefix=s3_prefix
                )
                
                st.success("✅ Projet Label Studio créé avec succès!")
                st.json(project_info)
                
                # Display project link
                label_studio_url = config.LABEL_STUDIO_URL
                project_url = f"{label_studio_url}/projects/{project_info['project_id']}"
                st.markdown(f"🔗 [Ouvrir le projet dans Label Studio]({project_url})")
                
            except Exception as e:
                st.error(f"❌ Erreur lors de la création du projet Label Studio: {e}")
        
        # Show detailed results
        with st.expander("Détails des résultats"):
            st.json(upload_results)


if __name__ == "__main__":
    main()