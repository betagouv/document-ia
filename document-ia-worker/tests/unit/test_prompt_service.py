import os

import pytest

from document_ia_schemas.cni import CNIModel
from document_ia_worker.core.prompt.prompt_configuration import SupportedDocumentType
from document_ia_worker.core.prompt.prompt_service import PromptService
from document_ia_worker.exception.unsupported_document_type import UnsupportedDocumentType


class TestPromptService:

    def test_classification_prompt_injects_document_categories_and_descriptions(self):
        service = PromptService()

        # Given three supported document types
        doc_types = [
            SupportedDocumentType.CNI,
            SupportedDocumentType.PASSEPORT,
            SupportedDocumentType.PERMIS_CONDUIRE,
        ]

        # When rendering the classification prompt
        rendered = service.get_classification_prompt(doc_types)

        # Then the bullet list should include each category.type, plus only one category 'autre' (AUTRE)
        for dt in doc_types:
            schema = service._get_schema_class_instance(dt)
            assert f"- {schema.type}" in rendered
        # Category 'autre' (AUTRE) only once
        assert rendered.count("- autre") == 1

        # And the distinctive characteristics section should include headers and each description item
        for dt in doc_types:
            schema = service._get_schema_class_instance(dt)
            header = f"**{schema.name}** ({schema.type})"
            assert header in rendered
            for item in schema.description:
                assert f"- {item}" in rendered

        # And the response format JSON keys should be present
        assert '"document_type"' in rendered
        assert '"confidence"' in rendered
        assert '"explanation"' in rendered

    def test_classification_prompt_is_cwd_independent(self, tmp_path, monkeypatch):
        # Change CWD to a temporary directory to ensure PromptService resolves paths relative to its file
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            service = PromptService()
            rendered = service.get_classification_prompt([SupportedDocumentType.CNI])
            # Minimal assertions: contains the CNI type and the response JSON keys
            cni_schema = service._get_schema_class_instance(SupportedDocumentType.CNI)
            assert f"- {cni_schema.type}" in rendered
            assert '"document_type"' in rendered
            assert '"confidence"' in rendered
            assert '"explanation"' in rendered
        finally:
            os.chdir(old_cwd)

    def test_get_classification_prompt_raises_if_schema_missing(self, tmp_path):
        service = PromptService()

        # Instead of swapping a schemas_directory (no longer used), request a document type
        # for which no schema exists. We pass a lightweight object with a .value attribute.
        class FakeDocType:
            value = "this_schema_does_not_exist"

        with pytest.raises(UnsupportedDocumentType):
            service.get_classification_prompt([FakeDocType()])

    def test_get_extraction_prompt_returns_schema_and_model_for_cni(self):
        """Ensure get_extraction_prompt('cni') returns the schema content and the CNIExtract model class."""
        service = PromptService()

        prompt_text, model_class = service.get_extraction_prompt(SupportedDocumentType.CNI)

        # The model class should be the CNIExtract defined in the cni model module

        assert model_class is CNIModel

        schema_instance = service._get_schema_class_instance(SupportedDocumentType.CNI)

        # The template should have been rendered with the document name
        assert schema_instance.name in prompt_text

        # And each description item should appear in the prompt
        for desc in schema_instance.description:
            assert desc in prompt_text

        # The prompt should embed the explicit schema examples
        for key, value in schema_instance.examples[0].model_dump(mode="json").items():
            assert f'"{key}"' in prompt_text

        # The template iterates document_json_properties: ensure keys and property descriptions are present
        for key, prop in schema_instance.get_json_schema_dict().get("properties", {}).items():
            assert key in prompt_text
            if isinstance(prop, dict) and prop.get("description"):
                assert prop.get("description") in prompt_text
        
        # Assert the final prompt text is exactly as expected (snapshot test)
        assert prompt_text == """Tu es un agent spécialisé dans l'extraction de données à partir de Carte nationale d'identité. Ta mission est d'analyser le contenu d'un document obtenu par OCR et d'extraire avec précision la liste des informations suivantes demandées :

- **numero_document** : Identifiant unique de la carte d'identité (format alphanumérique)
- **date_delivrance** : Date d'émission du document (format JJ MM AAAA). Si absente, renseigner `null`.
- **date_expiration** : Date limite de validité du document (format JJ MM AAAA). Une carte d'identité est valide 10 ans. Si absente renseigner `null`.
- **nom** : Nom de famille du titulaire (en majuscules sur le document
- **prenom** : Prénom du titulaire, uniquement le premier s'il y en a plusieurs
- **date_naissance** : Date de naissance du titulaire (format JJ MM AAAA). Si absente renseigner `null`.
- **lieu_naissance** : Lieu de naissance du titulaire
- **nationalite** : Nationalité du titulaire (en majuscules sur le document)
- **bande_mrz** : Bande Mrz de la carte d'identité (Machine Readable Zone). Si absent, renseigné `null`.


## Contexte spécifique au document de type Carte nationale d'identité
- Document officiel français (carte nationale d'identité ou CNI)
- Contient des mentions comme "République Française"
- Présence d'informations : nom, prénom, date et lieu de naissance
- Numéro de carte à 12 chiffres
- Date de délivrance et date d'expiration
- Mention de l'autorité de délivrance (préfécture ou sous-préfécture)
- Peut contenir des codes MRZ (Machine Readable Zone) sous forme de lignes de caractères avec symboles <


## Contexte spécifique au résultat d'OCR
Les textes OCR peuvent contenir des erreurs, des imprécisions ou des zones illisibles. Tu dois faire preuve de discernement pour identifier correctement les informations même en présence d'imperfections.

## Instructions strictes concernant les données manquantes
- IMPORTANT: Si une information n'est PAS EXPLICITEMENT MENTIONNÉE dans le texte fourni, tu DOIS utiliser la valeur `null` (sans guillemets).
- NE JAMAIS INFÉRER, DEVINER OU INVENTER des informations qui ne sont pas clairement présentes dans le texte.
- Pour les dates en particulier, si elles ne sont pas explicitement indiquées, utilise IMPÉRATIVEMENT `null`.
- Le document peut ne pas contenir toutes les informations demandées. C'est normal et attendu.

## Instructions
1. Analyse minutieusement l'intégralité du texte fourni, qui est issu d'un OCR de Carte nationale d'identité
2. Identifie les informations en utilisant les indicateurs habituels (libellés, format, position relative des données)
3. Le format des dates présente dans le document est indiqué dans la liste des informations à extraire. Mais dans le json que tu renverras comme dans les examples, les dates doivent être au format ISO 8601 (YYYY-MM-DD) tu dois donc les convertir !
4. Si une information est absente, illisible ou ambiguë, définis la propriété comme `null` (sans guillemets)
5. Distingue clairement les informations relatives au document (numéro, dates) de celles relatives à la personne
6. Renvoie UNIQUEMENT un objet JSON conforme au schéma spécifié, sans texte explicatif ni commentaire

## Informations à extraire
- **numero_document**: Identifiant unique de la carte d'identité (format alphanumérique)
- **date_delivrance**: Date d'émission du document (format JJ MM AAAA). Si absente, renseigner `null`.
- **date_expiration**: Date limite de validité du document (format JJ MM AAAA). Une carte d'identité est valide 10 ans. Si absente renseigner `null`.
- **nom**: Nom de famille du titulaire (en majuscules sur le document
- **prenom**: Prénom du titulaire, uniquement le premier s'il y en a plusieurs
- **date_naissance**: Date de naissance du titulaire (format JJ MM AAAA). Si absente renseigner `null`.
- **lieu_naissance**: Lieu de naissance du titulaire
- **nationalite**: Nationalité du titulaire (en majuscules sur le document)
- **bande_mrz**: Bande Mrz de la carte d'identité (Machine Readable Zone). Si absent, renseigné `null`.

## Vérification finale avant réponse
- Vérifie une dernière fois que tu n'as PAS INVENTÉ de données manquantes.
- Confirme que les champs pour lesquels aucune information n'est disponible sont bien définis comme `null`.
- Vérifie particulièrement les dates, qui doivent être `null` si non explicitement mentionnées.

## Format de réponse
Réponds UNIQUEMENT avec un objet JSON au format suivant :

```json
{
  "numero_document": "string",
  "date_delivrance": "string",
  "date_expiration": "string",
  "nom": "string",
  "prenom": "string",
  "date_naissance": "string",
  "lieu_naissance": "string",
  "nationalite": "string",
  "bande_mrz": "string"
}
```

## Exemple de réponse

Voici des exemples de réponses attendues :

Exemple 1 :
{
  "numero_document": "123456789012",
  "date_delivrance": "2010-01-01",
  "date_expiration": "2020-01-01",
  "nom": "DUPONT",
  "prenom": "JEAN",
  "date_naissance": "1990-01-01",
  "lieu_naissance": "PARIS 15e",
  "nationalite": "FRANÇAISE",
  "bande_mrz": "IDFRADUPONT\u003c\u003cJEAN\u003cROBIN\u003cADRIEN\u003c\u003c\u003c\u003e\u003c\u003e\u003c\u003c\u003c\u003c\u003c\u003e\u003e\u003e123456789012FRA0002152F2809160\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c\u003c00"
}


N'ajoute pas de texte avant ou après le JSON final."""

    def test_get_extraction_prompt_raises_for_unknown_document(self):
        """Requesting a prompt for an unknown document type should raise UnsupportedDocumentType."""
        service = PromptService()
        with pytest.raises(UnsupportedDocumentType):
            service.get_extraction_prompt("type_inconnu")
