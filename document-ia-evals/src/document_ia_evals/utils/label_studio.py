"""Label Studio utility functions."""

import json
import os
from typing import Any, Optional, Type, get_origin

from dotenv import load_dotenv
from label_studio_sdk import Client, LabelStudio
from pydantic import BaseModel

from document_ia_evals.utils.config import config
from document_ia_schemas import SupportedDocumentType, resolve_extract_schema

load_dotenv()

def get_label_studio_client() -> LabelStudio:

    if config.ALLOW_INSECURE_REQUESTS is True:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False

    # Initialize Label Studio client
    ls_client = LabelStudio(base_url=config.LABEL_STUDIO_URL, api_key=config.LABEL_STUDIO_API_KEY)
    return ls_client

def get_label_studio_client_legacy() -> Optional[Client]: 
   
    client = Client(url=config.LABEL_STUDIO_URL, api_key=config.LABEL_STUDIO_API_KEY)
    if config.ALLOW_INSECURE_REQUESTS is True:
        import requests
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        session.verify = False
        client = Client(url=config.LABEL_STUDIO_URL, api_key=config.LABEL_STUDIO_API_KEY, session=session)
    return client


def get_label_studio_url() -> str:
    """Get the base Label Studio URL from environment."""
    url = os.getenv("LABEL_STUDIO_URL", "http://localhost:8080")
    # Remove trailing slash if present
    return url.rstrip('/')


def get_project_url(project_id: int) -> str:
    """
    Generate Label Studio project data URL.
    
    Args:
        project_id: Label Studio project ID
    
    Returns:
        str: URL to the project's data page
    
    Example:
        >>> get_project_url(10)
        'https://labeling.document-ia.beta.gouv.fr/projects/10/data'
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/data"


def get_task_url(project_id: int, task_id: int) -> str:
    """
    Generate Label Studio task URL.
    
    Args:
        project_id: Label Studio project ID
        task_id: Task ID
    
    Returns:
        str: URL to the specific task
    
    Example:
        >>> get_task_url(10, 123)
        'https://labeling.document-ia.beta.gouv.fr/projects/10/data?task=123'
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/data?task={task_id}"


def get_project_settings_url(project_id: int) -> str:
    """
    Generate Label Studio project settings URL.
    
    Args:
        project_id: Label Studio project ID
    
    Returns:
        str: URL to the project's settings page
    """
    base_url = get_label_studio_url()
    return f"{base_url}/projects/{project_id}/settings"



METADATA_KEY = '__metadata__'
def dict_to_annotation_result(data: dict[str, Any], metadata: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Convert workflow result data to Label Studio annotation structure."""
    results: list[dict[str, Any]] = []
    
    for field_name, value in data.items():
        if value is not None:
            results.append({
                'value': {'text': [str(value)]},
                'from_name': field_name,
                'to_name': 'pdf',
                'type': 'textarea',
                'readonly': False
            })
    if metadata is not None:
        results.append({
            'value': {'text': [json.dumps(metadata)]},
            'from_name': METADATA_KEY,
            'to_name': 'pdf',
            'type': 'textarea',
            'readonly': True
        })
        

    
    return results

def annotation_results_to_dict(annotation_results: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Convert Label Studio annotation results back to a dictionary.
    
    This is the reverse operation of dict_to_annotation_result.
    
    Args:
        annotation_results: List of Label Studio annotation result objects
        
    Returns:
        dict: Dictionary mapping field names to their values
        
    Example:
        >>> results = [
        ...     {
        ...         'value': {'text': ['John Doe']},
        ...         'from_name': 'name',
        ...         'to_name': 'pdf',
        ...         'type': 'textarea'
        ...     }
        ... ]
        >>> annotation_results_to_dict(results)
        {'name': 'John Doe'}
    """
    data: dict[str, Any] = {}
    metadata: dict[str, Any] | None = None
    for result in annotation_results:
        field_name = result.get('from_name')
                    
        # Extract the value from the nested structure
        value_obj = result.get('value', {})
        text_list = value_obj.get('text', [])
        
        if field_name and text_list:
            if field_name == METADATA_KEY:
                metadata = json.loads(text_list[0])
            else:
                data[field_name] = text_list[0]
    
    return data, metadata


# label studio fromat

def create_task(pdf_url: str, ground_truth: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a complete Label Studio task from Pydantic models."""
    task: dict[str, Any] = {
        'data': {
            'pdf': pdf_url
        }
    }
    # Ground truth as annotation
    if ground_truth:
        annotation_result = dict_to_annotation_result(ground_truth)
        task['annotations'] = [{
            'result': annotation_result,
            'ground_truth': True
        }]
    
    return task

def field_name_to_label(field_name: str) -> str:
    """Convert a field name to a readable label."""
    return field_name.replace('_', ' ').title()


def is_optional(field_type: Any) -> bool:
    """Check if a field is Optional."""
    origin = get_origin(field_type)
    if origin is not None:
        args = getattr(field_type, '__args__', ())
        return type(None) in args
    return False


def generate_label_config(model: Type[BaseModel], title: str = "Document Extraction") -> str:
    """Generate Label Studio XML configuration from a Pydantic model."""
    
    fields_xml: list[str] = []

    for field_name, field_info in model.model_fields.items():
        field_type = field_info.annotation
        required = not is_optional(field_type)
        label = field_name_to_label(field_name)
        
        field_xml = f"""
      <View style="margin-bottom: 20px;">
        <Text name="{field_name}_label" value="{label}:" style="font-weight: bold; margin-bottom: 5px;"/>
        <Textarea name="{field_name}" toName="pdf" 
                  placeholder="Entrez {label.lower()}" 
                  rows="1" 
                  editable="true"
                  required="{str(required).lower()}"
                  maxSubmissions="1"
                  showSubmitButton="false"/>
      </View>"""
        fields_xml.append(field_xml)
    
    label_config = f"""<View>
  <Header value="{title}"/>
  
  <View style="display: flex; flex-direction: row; height: calc(100vh - 100px);">
    <!-- Image à gauche -->
    <View style="flex: 0 0 50%; min-width: 300px; max-width: 80%; margin-right: 20px; resize: horizontal; overflow: auto; border-right: 2px solid #ccc;">
      <Pdf name="pdf" value="$pdf" zoom="true" zoomControl="true"/>
    </View>
    
    <!-- Champs à droite -->
    <View style="flex: 1; overflow-y: auto; padding-right: 10px;">
      <Header value="Informations extraites"/>
      {''.join(fields_xml)}
    </View>
  </View>
</View>"""
    
    return label_config


def create_label_studio_project(
    dataset_name: str,
    doc_type: SupportedDocumentType,
    s3_prefix: str
) -> dict[str, Any]:
    """
    Create a Label Studio project with S3 storage integration.
    
    Args:
        dataset_name: Name for the dataset/project
        doc_type: Type of document being processed
        s3_prefix: S3 prefix where files are stored
    
    Returns:
        Dictionary with project information including:
        - project_id: Label Studio project ID
        - project_title: Project title
        - source_storage_id: S3 import storage ID
        - target_storage_id: S3 export storage ID
        - task_count: Number of tasks imported
    
    Raises:
        ValueError: If Label Studio configuration is missing
    """
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
    project = ls.create_project(  # type: ignore
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
    
    source_storage = project.connect_s3_import_storage(  # type: ignore
        **s3_params,
        prefix=f"{s3_prefix}/tasks",
        presign=True,
        regex_filter=r'.*\.json$',
        use_blob_urls=False
    )
    target_storage = project.connect_s3_export_storage(  # type: ignore
        **s3_params,
        prefix=f"{s3_prefix}/target"
    )
    
    # Sync storage to import tasks
    project.sync_import_storage('s3', source_storage['id'])  # type: ignore
    # Sync storage to export tasks
    project.sync_export_storage('s3', target_storage['id'])  # type: ignore
    
    return {
        'project_id': project.id,  # type: ignore
        'project_title': project.params.get('title'),  # type: ignore
        'source_storage_id': source_storage['id'],
        'target_storage_id': target_storage['id'],
        'task_count': len(project.get_tasks())  # type: ignore
    }
