from typing import Any

from document_ia_schemas.utils.pydantic_utils import get_max_examples_count, build_example_at_index


class TestMaxExamplesCount:

    def test_get_max_examples_count_empty_or_no_examples(self):
        """Test le comptage quand il n'y a aucun exemple ou des champs vides."""
        properties: dict[str, Any] = {
            "name": {"type": "string"},
            "age": {"type": "integer"}
        }
        defs: dict[str, Any] = {}

        assert get_max_examples_count(properties, defs) == 0


    def test_get_max_examples_count_uneven_lists(self):
        """Test le comptage avec des listes d'exemples de tailles différentes (doit retourner le max)."""
        properties: dict[str, Any] = {
            "field_with_2": {"type": "string", "examples": ["A", "B"]},
            "field_with_4": {"type": "integer", "examples": [1, 2, 3, 4]},
            "field_with_1": {"type": "string", "examples": ["Seul"]}
        }
        defs: dict[str, Any] = {}

        assert get_max_examples_count(properties, defs) == 4


    def test_get_max_examples_count_nested_models(self):
        """Test le comptage à travers des modèles imbriqués et des tableaux de modèles."""
        properties: dict[str, Any] = {
            "direct_field": {"type": "string", "examples": ["A", "B"]},  # max 2 ici
            "experiences": {
                "type": "array",
                "items": {"$ref": "#/$defs/Experience"}
            },
            "address": {
                "$ref": "#/$defs/Address"
            }
        }
        defs: dict[str, Any] = {
            "Experience": {
                "properties": {
                    "company": {"type": "string", "examples": ["Google", "Apple", "Microsoft"]}  # max 3 ici
                }
            },
            "Address": {
                "properties": {
                    "city": {"type": "string", "examples": ["Paris"]}  # max 1 ici
                }
            }
        }

        # Le maximum global doit être 3 (celui de company dans Experience)
        assert get_max_examples_count(properties, defs) == 3


class TestBuildExampleAtIndex:

    def test_build_example_uneven_counts(self):
        """
        Test crucial : Comportement avec des nombres d'exemples différents.
        Si on demande l'index 2 (le 3ème), le champ qui n'en a que 2 doit répéter son dernier (index 1).
        """
        properties: dict[str, Any] = {
            "title": {"type": "string", "examples": ["Dev", "Lead", "CTO"]},  # 3 exemples
            "company": {"type": "string", "examples": ["Google", "Apple"]},  # 2 exemples
            "country": {"type": "string", "examples": ["France"]}  # 1 exemple
        }
        defs: dict[str, Any] = {}

        # Index 0 : Tout le monde prend son 1er exemple
        assert build_example_at_index(properties, defs, 0) == {
            "title": "Dev",
            "company": "Google",
            "country": "France"
        }

        # Index 1 : Le country n'a pas de 2ème exemple, il répète "France"
        assert build_example_at_index(properties, defs, 1) == {
            "title": "Lead",
            "company": "Apple",
            "country": "France"
        }

        # Index 2 : title prend son 3ème, company répète son 2ème, country répète son 1er
        assert build_example_at_index(properties, defs, 2) == {
            "title": "CTO",
            "company": "Apple",
            "country": "France"
        }


    def test_build_example_fallback_types(self):
        """Test le fallback automatique si AUCUN exemple n'est fourni pour un champ."""
        properties: dict[str, Any] = {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "is_active": {"type": "boolean"},
            "unknown_type": {"type": "weird_stuff"}
        }
        defs: dict[str, Any] = {}

        result = build_example_at_index(properties, defs, 0)

        assert result == {
            "name": "...",
            "age": 0,
            "is_active": True,
            "unknown_type": None
        }


    def test_build_example_nested_objects(self):
        """Test la génération d'exemples pour les objets imbriqués ($ref)."""
        properties: dict[str, Any] = {
            "user_address": {"$ref": "#/$defs/Address"}
        }
        defs: dict[str, Any] = {
            "Address": {
                "properties": {
                    "city": {"type": "string", "examples": ["Paris", "Lyon"]}
                }
            }
        }

        assert build_example_at_index(properties, defs, 0) == {"user_address": {"city": "Paris"}}
        assert build_example_at_index(properties, defs, 1) == {"user_address": {"city": "Lyon"}}


    def test_build_example_array_of_objects(self):
        """Test la génération d'exemples pour les tableaux d'objets (comme les expériences)."""
        properties: dict[str, Any] = {
            "experiences": {
                "type": "array",
                "items": {"$ref": "#/$defs/Experience"}
            }
        }
        defs: dict[str, Any] = {
            "Experience": {
                "properties": {
                    "title": {"type": "string", "examples": ["Dev", "CTO"]}
                }
            }
        }

        # Il doit créer un tableau contenant 1 objet, lui-même généré à partir de l'index
        assert build_example_at_index(properties, defs, 0) == {
            "experiences": [{"title": "Dev"}]
        }
        assert build_example_at_index(properties, defs, 1) == {
            "experiences": [{"title": "CTO"}]
        }


    def test_build_example_array_fallback(self):
        """Test le fallback si on a un tableau simple (sans $ref) et sans exemples."""
        properties: dict[str, Any] = {
            "skills": {
                "type": "array",
                "items": {"type": "string"}  # Pas d'examples fournis directement à la racine de la propriété
            }
        }
        defs: dict[str, Any] = {}

        # Sans exemples à la racine, un tableau simple tombe dans le fallback -> []
        assert build_example_at_index(properties, defs, 0) == {
            "skills": []
        }


    def test_build_example_array_with_examples_direct(self):
        """Test un tableau simple qui a ses exemples fournis directement (comme list[str] de Pydantic)."""
        properties: dict[str, Any] = {
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "examples": [
                    ["Python", "Go"],
                    ["Java", "C++"]
                ]
            }
        }
        defs: dict[str, Any] = {}

        # Le script détecte la clé "examples" en priorité (règle n°1 de ta fonction)
        assert build_example_at_index(properties, defs, 0) == {"skills": ["Python", "Go"]}
        assert build_example_at_index(properties, defs, 1) == {"skills": ["Java", "C++"]}
        assert build_example_at_index(properties, defs, 2) == {"skills": ["Java", "C++"]}  # Fallback au dernier index
