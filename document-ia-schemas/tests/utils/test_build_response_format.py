from document_ia_schemas.utils.pydantic_utils import build_response_format


class TestBuildResponseFormat:
    def test_build_simple_fields(self):
        """Test la construction d'un format pour des types simples (string, integer, etc.)."""
        properties = {
            "first_name": {"type": "string"},
            "age": {"type": "integer"},
            "is_active": {"type": "boolean"}
        }
        defs = {}

        result = build_response_format(properties, defs)

        assert result == {
            "first_name": "string",
            "age": "integer",
            "is_active": "boolean"
        }

    def test_build_array_of_simple_types(self):
        """Test la construction pour des tableaux contenant des types simples (ex: list[str])."""
        properties = {
            "skills": {
                "type": "array",
                "items": {"type": "string"}
            },
            "scores": {
                "type": "array",
                "items": {"type": "number"}
            }
        }
        defs = {}

        result = build_response_format(properties, defs)

        assert result == {
            "skills": ["string"],
            "scores": ["number"]
        }

    def test_build_nested_object(self):
        """Test la construction pour un sous-modèle unique (un objet imbriqué)."""
        properties = {
            "address": {
                "$ref": "#/$defs/AddressModel"
            }
        }
        defs = {
            "AddressModel": {
                "properties": {
                    "city": {"type": "string"},
                    "zip_code": {"type": "integer"}
                }
            }
        }

        result = build_response_format(properties, defs)

        assert result == {
            "address": {
                "city": "string",
                "zip_code": "integer"
            }
        }

    def test_build_array_of_nested_objects(self):
        """Test la construction pour un tableau de sous-modèles (ex: List[CVExperienceModel])."""
        properties = {
            "experiences": {
                "type": "array",
                "items": {
                    "$ref": "#/$defs/CVExperienceModel"
                }
            }
        }
        defs = {
            "CVExperienceModel": {
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"}
                }
            }
        }

        result = build_response_format(properties, defs)

        assert result == {
            "experiences": [
                {
                    "title": "string",
                    "company": "string"
                }
            ]
        }

    def test_build_deeply_nested_objects(self):
        """Test la construction avec plusieurs niveaux d'imbrication."""
        properties = {
            "portfolio": {
                "$ref": "#/$defs/PortfolioModel"
            }
        }
        defs = {
            "PortfolioModel": {
                "properties": {
                    "projects": {
                        "type": "array",
                        "items": {
                            "$ref": "#/$defs/ProjectModel"
                        }
                    }
                }
            },
            "ProjectModel": {
                "properties": {
                    "name": {"type": "string"}
                }
            }
        }

        result = build_response_format(properties, defs)

        assert result == {
            "portfolio": {
                "projects": [
                    {
                        "name": "string"
                    }
                ]
            }
        }

    def test_build_fallback_malformed_data(self):
        """Test le comportement face à des schémas mal formés ou incomplets."""
        properties = {
            # Propriété qui n'est pas un dictionnaire
            "invalid_field": "Ceci devrait fallback sur string",

            # Tableau dont le champ 'items' n'est pas un dict
            "bad_array_items": {
                "type": "array",
                "items": "not a dict"
            },

            # Tableau sans spécifier les 'items' du tout
            "empty_array_def": {
                "type": "array"
            }
        }
        defs = {}

        result = build_response_format(properties, defs)

        assert result == {
            "invalid_field": "string",  # Fallback direct
            "bad_array_items": ["string"],  # Fallback de la liste si items n'est pas un dictionnaire
            "empty_array_def": "array"  # Fallback sur la string 'array' s'il n'y a pas la clé 'items'
        }

    def test_build_missing_ref(self):
        """Test le comportement si un objet cible un $ref qui n'existe pas dans les définitions."""
        properties = {
            "broken_ref": {
                "$ref": "#/$defs/MissingModel"
            }
        }
        defs = {}  # MissingModel n'est pas défini ici

        result = build_response_format(properties, defs)

        # Il doit créer un dictionnaire vide car il ne trouve pas les 'properties' du sub_def
        assert result == {
            "broken_ref": {}
        }
