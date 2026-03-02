from document_ia_schemas.utils.pydantic_utils import extract_fields_info


class TestExtractFieldsInfo:

    def test_extract_simple_fields(self):
        """Test l'extraction de propriétés simples sans imbrication."""
        properties = {
            "first_name": {"type": "string", "description": "Prénom de la personne"},
            "age": {"type": "integer"}  # Pas de description
        }
        defs = {}

        result = extract_fields_info(properties, defs)

        assert len(result) == 2
        assert result[0] == {"name": "first_name", "description": "Prénom de la personne", "level": 0}
        assert result[1] == {"name": "age", "description": "", "level": 0}

    def test_extract_array_of_simple_fields(self):
        """Test l'extraction d'une liste contenant des types simples (ex: List[str])."""
        properties = {
            "skills": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Liste de compétences"
            }
        }
        defs = {}

        result = extract_fields_info(properties, defs)

        assert len(result) == 1
        assert result[0] == {"name": "skills", "description": "Liste de compétences", "level": 0}

    def test_extract_nested_object(self):
        """Test l'extraction d'un modèle imbriqué (Objet unique)."""
        properties = {
            "address": {
                "$ref": "#/$defs/AddressModel",
                "description": "Adresse complète"
            }
        }
        defs = {
            "AddressModel": {
                "properties": {
                    "city": {"type": "string", "description": "Ville"}
                }
            }
        }

        result = extract_fields_info(properties, defs)

        assert len(result) == 2
        assert result[0] == {"name": "address (Objet)", "description": "Adresse complète", "level": 0}
        assert result[1] == {"name": "city", "description": "Ville", "level": 1}

    def test_extract_array_of_nested_objects(self):
        """Test l'extraction d'une liste de modèles (ex: Liste d'expériences)."""
        properties = {
            "experiences": {
                "type": "array",
                "items": {"$ref": "#/$defs/ExperienceModel"},
                "description": "Liste des expériences"
            }
        }
        defs = {
            "ExperienceModel": {
                "properties": {
                    "title": {"type": "string", "description": "Titre du poste"},
                    "company": {"type": "string", "description": "Entreprise"}
                }
            }
        }

        result = extract_fields_info(properties, defs)

        assert len(result) == 3
        assert result[0] == {"name": "experiences (Liste)", "description": "Liste des expériences", "level": 0}
        assert result[1] == {"name": "title", "description": "Titre du poste", "level": 1}
        assert result[2] == {"name": "company", "description": "Entreprise", "level": 1}

    def test_extract_deeply_nested_objects(self):
        """Test l'extraction avec plusieurs niveaux d'imbrication."""
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
                        "items": {"$ref": "#/$defs/ProjectModel"},
                        "description": "Projets réalisés"
                    }
                }
            },
            "ProjectModel": {
                "properties": {
                    "name": {"type": "string", "description": "Nom du projet"}
                }
            }
        }

        result = extract_fields_info(properties, defs)

        assert len(result) == 3
        assert result[0] == {"name": "portfolio (Objet)", "description": "", "level": 0}
        assert result[1] == {"name": "projects (Liste)", "description": "Projets réalisés", "level": 1}
        assert result[2] == {"name": "name", "description": "Nom du projet", "level": 2}

    def test_handle_missing_refs_gracefully(self):
        """Test le comportement si la définition (le $ref) est introuvable dans $defs."""
        properties = {
            "missing_ref": {
                "$ref": "#/$defs/UnknownModel",
                "description": "Référence cassée"
            }
        }
        defs = {}  # defs est vide, UnknownModel n'existe pas

        result = extract_fields_info(properties, defs)

        # Il doit ajouter le parent, mais comme la ref est introuvable, il n'ajoutera pas d'enfants
        assert len(result) == 1
        assert result[0] == {"name": "missing_ref (Objet)", "description": "Référence cassée", "level": 0}

    def test_ignore_non_dict_properties(self):
        """Test que la fonction ignore les propriétés qui ne sont pas des dictionnaires."""
        properties = {
            "valid_field": {"type": "string", "description": "OK"},
            "invalid_field": "Ceci n'est pas un dictionnaire"
        }
        defs = {}

        result = extract_fields_info(properties, defs)

        assert len(result) == 1
        assert result[0]["name"] == "valid_field"
