"""Snippet generator helper for API integration code samples."""

import json
from typing import Any

CURL_TEMPLATE = """curl -X POST "{full_url}" \\
  -H "X-API-KEY: {api_key_str}" \\
  {file_code} \\
  {override_code} \\
  {metadata_code} \\
  -H "Accept: application/json"
"""

PYTHON_TEMPLATE = """import json
import requests

url = "{full_url}"
headers = {{
    "X-API-KEY": "{api_key_str}",
    "Accept": "application/json",
}}
{file_code}
{data_code}

response = requests.post(
    url,
    headers=headers,{files_arg}{data_arg}
)
response.raise_for_status()

print(response.json())
"""

TS_TEMPLATE = """import fetch from 'node-fetch'; // si < Node.js 18

const url = "{full_url}";
const apiKey = "{api_key_str}";

const formData = new FormData();
{file_code}
{override_code}
{metadata_code}

const response = await fetch(url, {{
  method: 'POST',
  headers: {{
    'X-API-KEY': apiKey,
  }},
  body: formData
}});

const data = await response.json();
console.log(data);
"""

JAVA_TEMPLATE = """import okhttp3.*;
import java.io.File;
import java.io.IOException;

public class DocumentIaClient {{
    public static void main(String[] args) throws IOException {{
        OkHttpClient client = new OkHttpClient().newBuilder().build();

        MultipartBody.Builder bodyBuilder = new MultipartBody.Builder()
            .setType(MultipartBody.FORM);

        {file_code}
        {override_code}
        {metadata_code}

        RequestBody body = bodyBuilder.build();

        Request request = new Request.Builder()
            .url("{full_url}")
            .post(body)
            .addHeader("X-API-KEY", "{api_key_str}")
            .addHeader("Accept", "application/json")
            .build();

        try (Response response = client.newCall(request).execute()) {{
            if (!response.isSuccessful()) throw new IOException("Unexpected code " + response);
            System.out.println(response.body().string());
        }}
    }}
}}
"""


def generate_code_snippets(
    base_url: str,
    workflow_id: str,
    sync_mode: bool,
    input_method: str,
    file_url: str | None = None,
    override: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    api_key_placeholder: str = "VOTRE_CLE_API",
) -> dict[str, str]:
    """Generate code snippets for cURL, Python, TypeScript, and Java OkHttp.

    Returns:
        dict[str, str]: Map of language -> code snippet
    """
    clean_base_url = base_url.rstrip("/") if base_url else "https://api.document-ia.beta.gouv.fr"
    endpoint_path = (
        f"/api/v2/workflows/{workflow_id}/execute-sync"
        if sync_mode
        else f"/api/v2/workflows/{workflow_id}/execute"
    )
    full_url = f"{clean_base_url}{endpoint_path}"

    override_json_str = json.dumps(override, ensure_ascii=False) if override else ""
    metadata_json_str = json.dumps(metadata, ensure_ascii=False) if metadata else ""

    override_escaped_java = override_json_str.replace('"', '\\"')
    metadata_escaped_java = metadata_json_str.replace('"', '\\"')

    doc_url = file_url if file_url else "https://example.com/document.pdf"

    # cURL snippet
    curl_file = (
        '-F "file=@/chemin/vers/votre/fichier.pdf"'
        if input_method == "Téléverser un fichier local"
        else f'-F "file_url={doc_url}"'
    )
    curl_override = f"-F 'override={override_json_str}'" if override else ""
    curl_metadata = f"-F 'metadata={metadata_json_str}'" if metadata else ""

    curl_code = (
        CURL_TEMPLATE.format(
            full_url=full_url,
            api_key_str=api_key_placeholder,
            file_code=curl_file,
            override_code=curl_override,
            metadata_code=curl_metadata,
        )
        .replace("  \n", "")
        .strip()
    )

    # Python snippet
    py_data_dict = {}
    if input_method != "Téléverser un fichier local" and doc_url:
        py_data_dict["file_url"] = doc_url
    if override:
        py_data_dict["override"] = override_json_str
    if metadata:
        py_data_dict["metadata"] = metadata_json_str

    if input_method == "Téléverser un fichier local":
        py_file_code = (
            '\nfiles = {\n'
            '    "file": ("document.pdf", open("/chemin/vers/votre/fichier.pdf", "rb"), "application/pdf")\n'
            '}'
        )
        py_files_arg = "\n    files=files,"
    else:
        py_file_code = ""
        py_files_arg = ""

    if py_data_dict:
        py_data_code = f"\ndata = {json.dumps(py_data_dict, indent=4, ensure_ascii=False)}"
        py_data_arg = "\n    data=data,"
    else:
        py_data_code = ""
        py_data_arg = ""

    python_code = PYTHON_TEMPLATE.format(
        full_url=full_url,
        api_key_str=api_key_placeholder,
        file_code=py_file_code,
        data_code=py_data_code,
        files_arg=py_files_arg,
        data_arg=py_data_arg,
    ).strip()

    # TypeScript snippet
    if input_method == "Téléverser un fichier local":
        ts_file_code = (
            "import fs from 'fs';\n"
            "const fileStream = fs.createReadStream('/chemin/vers/votre/fichier.pdf');\n"
            "formData.append('file', fileStream as any);"
        )
    else:
        ts_file_code = f"formData.append('file_url', '{doc_url}');"

    ts_override = f"formData.append('override', JSON.stringify({override_json_str}));" if override else ""
    ts_metadata = f"formData.append('metadata', JSON.stringify({metadata_json_str}));" if metadata else ""

    ts_code = TS_TEMPLATE.format(
        full_url=full_url,
        api_key_str=api_key_placeholder,
        file_code=ts_file_code,
        override_code=ts_override,
        metadata_code=ts_metadata,
    ).strip()

    # Java snippet
    if input_method == "Téléverser un fichier local":
        java_file_code = (
            'File file = new File("/chemin/vers/votre/fichier.pdf");\n'
            '        bodyBuilder.addFormDataPart("file", file.getName(),\n'
            '            RequestBody.create(file, MediaType.parse("application/pdf")));'
        )
    else:
        java_file_code = f'bodyBuilder.addFormDataPart("file_url", "{doc_url}");'

    java_override = (
        f'bodyBuilder.addFormDataPart("override", "{override_escaped_java}");' if override else ""
    )
    java_metadata = (
        f'bodyBuilder.addFormDataPart("metadata", "{metadata_escaped_java}");' if metadata else ""
    )

    java_code = JAVA_TEMPLATE.format(
        full_url=full_url,
        api_key_str=api_key_placeholder,
        file_code=java_file_code,
        override_code=java_override,
        metadata_code=java_metadata,
    ).strip()

    return {
        "bash": curl_code,
        "python": python_code,
        "typescript": ts_code,
        "java": java_code,
    }
