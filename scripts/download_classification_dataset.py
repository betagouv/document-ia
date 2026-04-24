import os
import csv
import httpx
import tempfile
import shutil
from pathlib import Path

# Configuration via variables d'environnement
AUTH_COOKIE = os.getenv("AUTH_COOKIE")
CSV_PATH = os.getenv("CSV_PATH", "dataset.csv")
OUTPUT_DIR = Path("classification_dataset")
IS_DOWNLOADED_COL = "is_downloaded"

def save_progress(rows, fieldnames):
    """Sauvegarde l'état actuel dans le CSV de manière sécurisée."""
    temp_fd, temp_path = tempfile.mkstemp(suffix=".csv", dir=os.path.dirname(os.path.abspath(CSV_PATH)))
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8', newline='') as temp_file:
            writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        shutil.move(temp_path, CSV_PATH)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde du CSV : {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)

def download_dataset():
    """
    Télécharge les fichiers à partir d'un CSV et marque la progression.
    Supporte la reprise après interruption.
    """
    if not AUTH_COOKIE:
        print("Erreur: La variable d'environnement AUTH_COOKIE n'est pas définie.")
        print("Usage: AUTH_COOKIE=votre_session_id python scripts/download_classification_dataset.py")
        return

    if not Path(CSV_PATH).exists():
        print(f"Erreur: Le fichier CSV '{CSV_PATH}' est introuvable.")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Lecture initiale du CSV
    rows = []
    fieldnames = []
    with open(CSV_PATH, mode='r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []
        if IS_DOWNLOADED_COL not in fieldnames:
            fieldnames.append(IS_DOWNLOADED_COL)
        rows = list(reader)

    cookies = {"JSESSIONID": AUTH_COOKIE}
    headers = {
        "User-Agent": "Document-IA-Downloader/1.0",
        "Accept": "application/pdf,image/*"
    }

    # Initialisation des compteurs basés sur ce qui est déjà téléchargé
    subtype_counters = {}
    for row in rows:
        if row.get(IS_DOWNLOADED_COL) == "True":
            subtype = row.get('document_sub_category', 'unknown')
            safe_subtype = "".join([c if c.isalnum() else "_" for c in subtype])
            subtype_counters[safe_subtype] = subtype_counters.get(safe_subtype, 0) + 1

    downloaded_count = len([r for r in rows if r.get(IS_DOWNLOADED_COL) == 'True'])
    total_to_download = len(rows) - downloaded_count

    print(f"État actuel : {downloaded_count} déjà téléchargés, {total_to_download} restants.")

    try:
        for row in rows:
            # Sauter si déjà téléchargé
            if row.get(IS_DOWNLOADED_COL) == "True":
                continue

            subtype = row.get('document_sub_category', 'unknown')
            url = row.get('url')
            doc_id = row.get('document_id')

            if not url:
                continue

            safe_subtype = "".join([c if c.isalnum() else "_" for c in subtype])
            count = subtype_counters.get(safe_subtype, 0) + 1

            try:
                with httpx.Client(follow_redirects=True, timeout=30.0) as client:
                    response = client.get(url, cookies=cookies, headers=headers)
                    response.raise_for_status()

                    # Détection de l'extension
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "pdf" in content_type:
                        ext = ".pdf"
                    elif "png" in content_type:
                        ext = ".png"
                    elif "jpeg" in content_type or "jpg" in content_type:
                        ext = ".jpg"
                    else:
                        path_ext = os.path.splitext(url.split('?')[0])[1].lower()
                        ext = path_ext if path_ext in ['.pdf', '.png', '.jpg', '.jpeg'] else ".pdf"

                    filename = f"{safe_subtype}_{count:02d}{ext}"
                    filepath = OUTPUT_DIR / filename

                    with open(filepath, "wb") as out_file:
                        out_file.write(response.content)

                    # Marquer comme téléchargé et sauvegarder le CSV
                    row[IS_DOWNLOADED_COL] = "True"
                    subtype_counters[safe_subtype] = count
                    save_progress(rows, fieldnames)

                    print(f"OK: {filename} (ID: {doc_id})")

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    print("\nERREUR: Quota atteint (429). Arrêt pour aujourd'hui.")
                    return
                print(f"ERREUR HTTP {e.response.status_code} pour {url} (ID: {doc_id})")
            except Exception as e:
                print(f"ERREUR inattendue pour {url} (ID: {doc_id}): {e}")

    except KeyboardInterrupt:
        print("\nInterruption détectée. État sauvegardé.")
    finally:
        save_progress(rows, fieldnames)
        print("\nTravail terminé ou interrompu. Le CSV est à jour.")

if __name__ == "__main__":
    download_dataset()
