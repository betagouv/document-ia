from fastapi import FastAPI, UploadFile, File
import torch
from transformers import AutoModel
from PIL import Image
import io

app = FastAPI()

# Chargement unique au démarrage
print("Chargement du modèle Jina-v4 sur MPS...")
model = AutoModel.from_pretrained(
    "jinaai/jina-embeddings-v4",
    trust_remote_code=True,
    dtype=torch.bfloat16
).to("mps")


@app.post("/embed")
async def get_embedding(file: UploadFile = File(...)):
    # Lecture de l'image reçue
    request_object_content = await file.read()
    image = Image.open(io.BytesIO(request_object_content)).convert("RGB")

    # Inférence
    with torch.no_grad():
        embedding = model.encode_image(image, task="retrieval", max_pixels=512*512)

        # Réduction à 1024 dimensions (Troncature Matryoshka)
        # On prend les 1024 premières valeurs
        reduced_embedding = embedding[:1024]

        # Optionnel : Normalisation
        # Il est recommandé de normaliser après une troncature pour le k-NN
        norm = (reduced_embedding ** 2).sum() ** 0.5
        reduced_embedding = reduced_embedding / norm

    return {"embedding": reduced_embedding.tolist()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8093)
