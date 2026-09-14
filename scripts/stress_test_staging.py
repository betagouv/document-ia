#!/usr/bin/env python3
"""
Script de test de charge (stress test) pour tester la robustesse mémoire du worker sur Staging.
1. Envoie X requêtes simultanées en POST multipart/form-data.
2. Récupère les execution_id dans data.execution_id.
3. Pool le statut via GET /api/v1/executions/{execution_id} jusqu'à la fin de TOUTES les exécutions (statut SUCCESS ou FAILED).
4. Abandonne et annule le suivi d'une requête si elle dépasse max_timeout (1 minute / 60s par défaut).
5. Mesure et affiche le temps de traitement exact (en ms et sec).
"""

import argparse
import asyncio
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx

DEFAULT_URL = (
    "https://api.staging.document-ia.beta.gouv.fr/api/v2/workflows/document-classification-extraction-v2/execute"
)
DEFAULT_OVERRIDE = '{\n  "extract_content_ocr" : [\n    {\n      "param" : "model",\n      "value" : "tesseract"\n    }\n  ]\n}'


def get_base_url(full_url: str) -> str:
    parsed = urlparse(full_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def extract_execution_id(res_json: dict) -> str | None:
    """Extrait l'execution_id de la réponse API v2 ou v1."""
    if not isinstance(res_json, dict):
        return None

    # v2 API response: {"status": "success", "data": {"execution_id": "...", ...}}
    data_field = res_json.get("data")
    if isinstance(data_field, dict):
        if "execution_id" in data_field:
            return str(data_field["execution_id"])
        if "id" in data_field:
            return str(data_field["id"])

    # Root fallback
    if "execution_id" in res_json:
        return str(res_json["execution_id"])
    if "id" in res_json:
        return str(res_json["id"])

    return None


async def poll_execution_status(
    client: httpx.AsyncClient,
    execution_id: str,
    base_url: str,
    api_key: str,
    req_id: int,
    poll_interval: float = 2.5,
    max_timeout: float = 60.0,
) -> tuple[str, float]:
    """Pool l'API GET /api/v1/executions/{execution_id} tant que status == 'STARTED' et < max_timeout."""
    poll_url = f"{base_url}/api/v1/executions/{execution_id}"
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_key,
    }
    start_poll = time.perf_counter()

    # Décalage léger (staggering) pour étaler les requêtes de polling et éviter de surcharger le serveur web API
    await asyncio.sleep((req_id % 5) * 0.3)

    while True:
        elapsed_so_far = time.perf_counter() - start_poll
        if elapsed_so_far >= max_timeout:
            total_ms = int(elapsed_so_far * 1000)
            print(
                f"   ⏰ Execution #{req_id:02d} [{execution_id[:8]}...] -> ABANDONNÉE suite au TIMEOUT de {elapsed_so_far:.1f}s ({total_ms}ms > limit {max_timeout:.0f}s)"
            )
            return "TIMEOUT", elapsed_so_far

        try:
            res = await client.get(poll_url, headers=headers, timeout=30.0)
            if res.status_code == 200:
                data = res.json()
                status = str(data.get("status", "")).upper()

                if status in ("STARTED", "PROCESSING", "PENDING"):
                    # L'analyse est encore en cours
                    pass
                else:
                    # L'analyse est terminée (statut != STARTED)
                    elapsed = time.perf_counter() - start_poll
                    total_ms = int(elapsed * 1000)
                    status_emoji = "✅" if status == "SUCCESS" else "❌"
                    print(
                        f"   {status_emoji} Execution #{req_id:02d} [{execution_id[:8]}...] -> TERMINÉE ({status}) en {elapsed:.2f}s ({total_ms}ms)"
                    )
                    return status, elapsed
            elif res.status_code in (502, 503, 504, 429):
                # Le serveur proxy/API est temporairement occupé -> attente douce sans faire échouer
                await asyncio.sleep(3.0)
                continue
            else:
                print(
                    f"   ⚠️ Polling #{req_id:02d} -> Code HTTP {res.status_code}: {res.text[:100]}"
                )
        except Exception as e:
            # Exception réseau temporaire durant le polling
            await asyncio.sleep(2.0)
            continue

        await asyncio.sleep(poll_interval)


async def execute_and_wait(
    client: httpx.AsyncClient,
    req_id: int,
    url: str,
    base_url: str,
    api_key: str,
    file_bytes: bytes,
    file_name: str,
    override: str,
    poll_interval: float,
    max_timeout: float,
) -> dict:
    """Soumet la requête et attend la fin de l'exécution en polling."""
    submit_start = time.perf_counter()
    headers = {"X-Api-Key": api_key}
    files = {"file": (file_name, file_bytes, "application/pdf")}
    data = {"override": override}

    result = {
        "req_id": req_id,
        "execution_id": None,
        "submit_time": 0.0,
        "process_time": 0.0,
        "total_time": 0.0,
        "http_status": 500,
        "final_status": "FAILED",
    }

    try:
        response = await client.post(
            url, headers=headers, data=data, files=files, timeout=180.0
        )
        submit_elapsed = time.perf_counter() - submit_start
        result["submit_time"] = submit_elapsed
        result["http_status"] = response.status_code

        if 200 <= response.status_code < 300:
            res_json = response.json()
            execution_id = extract_execution_id(res_json)
            result["execution_id"] = execution_id

            if execution_id:
                print(
                    f"🚀 Soumission #{req_id:02d} OK -> execution_id: {execution_id} ({submit_elapsed:.2f}s)"
                )
                final_status, process_time = await poll_execution_status(
                    client,
                    execution_id,
                    base_url,
                    api_key,
                    req_id,
                    poll_interval,
                    max_timeout,
                )
                result["final_status"] = final_status
                result["process_time"] = process_time
                result["total_time"] = time.perf_counter() - submit_start
            else:
                print(
                    f"⚠️ Soumission #{req_id:02d} OK mais execution_id non trouvé dans la réponse: {res_json}"
                )
                result["final_status"] = "NO_EXECUTION_ID"
                result["total_time"] = submit_elapsed
        else:
            print(
                f"❌ Soumission #{req_id:02d} ÉCHOUÉE -> Code HTTP {response.status_code}: {response.text[:150]}"
            )
            result["total_time"] = submit_elapsed

    except Exception as e:
        submit_elapsed = time.perf_counter() - submit_start
        print(f"❌ Soumission #{req_id:02d} Exception: {e} ({submit_elapsed:.2f}s)")
        result["submit_time"] = submit_elapsed
        result["total_time"] = submit_elapsed

    return result


async def main():
    parser = argparse.ArgumentParser(
        description="Stress test worker Staging avec Polling d'exécution et Timeout"
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="URL d'exécution du workflow v2",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="Clé d'API X-Api-Key",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Chemin du fichier PDF à envoyer (obligatoire)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=10,
        help="Nombre de requêtes simultanées envoyées en même temps",
    )
    parser.add_argument(
        "-n",
        "--total-requests",
        type=int,
        default=10,
        help="Nombre total de requêtes à exécuter",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.5,
        help="Intervalle entre chaque polling en secondes (défaut: 2.5s)",
    )
    parser.add_argument(
        "--max-timeout",
        type=float,
        default=60.0,
        help="Temps maximum d'attente en secondes avant d'abandonner une requête (défaut: 60.0s)",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ Erreur: Le fichier est introuvable sur la machine: {file_path}")
        return

    base_url = get_base_url(args.url)
    file_bytes = file_path.read_bytes()
    file_name = file_path.name

    print("=" * 80)
    print("🚀 DÉMARRAGE DU STRESS TEST AVEC POLLING & TIMEOUT 60s")
    print(f"• URL d'exécution : {args.url}")
    print(f"• URL de Polling  : {base_url}/api/v1/executions/{{execution_id}}")
    print(f"• Fichier PDF     : {file_path}")
    print(f"• Concurrence     : {args.concurrency} requêtes simultanées")
    print(f"• Total requêtes  : {args.total_requests}")
    print(f"• Max Timeout     : {args.max_timeout} secondes")
    print("=" * 80)

    limits = httpx.Limits(
        max_keepalive_connections=args.concurrency * 2,
        max_connections=args.concurrency * 2,
    )
    async with httpx.AsyncClient(limits=limits, timeout=180.0) as client:
        semaphore = asyncio.Semaphore(args.concurrency)

        async def worker_task(req_id: int):
            async with semaphore:
                return await execute_and_wait(
                    client,
                    req_id,
                    args.url,
                    base_url,
                    args.api_key,
                    file_bytes,
                    file_name,
                    DEFAULT_OVERRIDE,
                    args.poll_interval,
                    args.max_timeout,
                )

        global_start = time.perf_counter()
        tasks = [worker_task(i + 1) for i in range(args.total_requests)]
        results = await asyncio.gather(*tasks)
        global_duration = time.perf_counter() - global_start

    print("=" * 80)
    print("📊 RÉSULTATS DÉTAILLÉS DU TEST DE CHARGE")
    print("=" * 80)

    successes = [r for r in results if r["final_status"] == "SUCCESS"]
    timeouts = [r for r in results if r["final_status"] == "TIMEOUT"]
    failures = [
        r for r in results if r["final_status"] not in ("SUCCESS", "TIMEOUT")
    ]

    total_reqs = len(results)
    print(f"• Succès globaux : {len(successes)} / {total_reqs}")
    print(f"• Timeouts (>60s): {len(timeouts)} / {total_reqs}")
    print(f"• Échecs         : {len(failures)} / {total_reqs}")
    print(
        f"⏱️ TEMPS GLOBAL DE TRAITEMENT (pour les {total_reqs} requêtes) : {global_duration:.2f}s ({global_duration*1000:.0f}ms)"
    )

    if successes:
        proc_times = [r["total_time"] for r in successes]
        avg_time = sum(proc_times) / len(proc_times)
        min_time = min(proc_times)
        max_time = max(proc_times)
        print(
            f"• Temps End-to-End par requête réussie : Moyenne={avg_time:.2f}s ({avg_time*1000:.0f}ms) | Min={min_time:.2f}s ({min_time*1000:.0f}ms) | Max={max_time:.2f}s ({max_time*1000:.0f}ms)"
        )

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
