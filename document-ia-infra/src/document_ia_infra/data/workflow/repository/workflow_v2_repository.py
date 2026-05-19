import logging
from enum import Enum

import yaml
from pathlib import Path
from typing import List, Optional, Dict, Any

from document_ia_infra.data.workflow.dto.workflow_v2_dto import WorkflowV2Dto
import document_ia_infra.data.workflow.dto.enums as infra_enums
import document_ia_schemas as schemas

logger = logging.getLogger(__name__)

MODULES_SOURCES = [infra_enums, schemas]


def inject_constructor(_, node):
    variable_name = node.value

    # 3. On parcourt les modules un par un pour trouver la variable
    for module in MODULES_SOURCES:
        if hasattr(module, variable_name):
            obj = getattr(module, variable_name)

            if isinstance(obj, type) and issubclass(obj, Enum):
                return [item.value for item in obj]

            return obj

    # Si la boucle se termine sans rien trouver, on lève l'erreur
    error_msg = f"Impossible d'injecter '!inject {variable_name}' : introuvable dans infra_enums ni document_ia_schemas."
    logger.error(error_msg)
    raise AttributeError(error_msg)


# On enregistre le tag
yaml.SafeLoader.add_constructor("!inject", inject_constructor)


def _generate_mock_payload(raw_workflow: dict) -> dict:
    """
    Génère un faux objet d'exécution à partir du YAML pour tester Pydantic.
    Si une valeur par défaut manque, on pioche dans l'enum.
    """
    mock_workflow = {
        "id": raw_workflow.get("id", ""),
        "name": raw_workflow.get("name", ""),
        "description": raw_workflow.get("description", ""),
        "version": raw_workflow.get("version", ""),
        "enabled": raw_workflow.get("enabled", True),
        "supported_file_types": raw_workflow.get("supported_file_types", []),
        "max_file_size_mb": raw_workflow.get("max_file_size_mb", 0),
        "processing_timeout_minutes": raw_workflow.get("processing_timeout_minutes", 0),
        "steps": [],
    }

    for step in raw_workflow.get("steps", []):
        action = step.get("action")
        mock_params = {}

        # On parcourt les règles définies dans le YAML pour cette étape
        for param_name, rules in step.get("params", {}).items():
            if "default" in rules:
                # Cas classique : on utilise la valeur par défaut du YAML
                mock_params[param_name] = rules["default"]
            elif (
                "enum" in rules
                and isinstance(rules["enum"], list)
                and len(rules["enum"]) > 0
            ):
                # Cas de ton document_type : Pas de default, donc on prend
                # arbitrairement le 1er élément de l'enum pour tromper Pydantic
                mock_params[param_name] = rules["enum"][0]
            elif "oneOf" in rules:
                # secours pour les cas très complexes
                mock_params[param_name] = rules.get("default", "all")

        mock_workflow["steps"].append({"action": action, "params": mock_params})

    return mock_workflow


class WorkflowV2Repository:
    def __init__(self):
        current_dir = Path(__file__).parent
        data_package_dir = current_dir.parent
        self.workflows_file_path = data_package_dir / "data" / "workflows.yaml"

        # On garde DEUX représentations en mémoire
        self._raw_workflows: List[
            Dict[str, Any]
        ] = []  # Pour le frontend et la validation
        self._validated_workflows: List[
            WorkflowV2Dto
        ] = []  # Pour garantir que le YAML est sain

        self._load_workflows()

    def _load_workflows(self):
        try:
            if not self.workflows_file_path.exists():
                logger.error(f"Fichier YAML introuvable : {self.workflows_file_path}")
                return

            with open(self.workflows_file_path, "r", encoding="utf-8") as f:
                raw_yaml_data = yaml.safe_load(f)

            # 1. On stocke la donnée BRUTE (C'est ça qu'on renverra à l'API !)
            self._raw_workflows = raw_yaml_data.get("workflows", [])

            # 2. Le "Crash Test" intelligent
            self._validated_workflows = []
            for raw_workflow in self._raw_workflows:
                # On génère un faux payload d'exécution pour tester Pydantic
                mock_payload = _generate_mock_payload(raw_workflow)

                # On valide le mock. Si ça passe, ça veut dire que la structure YAML est saine !
                validated_dto = WorkflowV2Dto.model_validate(mock_payload)
                self._validated_workflows.append(validated_dto)

            logger.info(f"✅ {len(self._raw_workflows)} workflows chargés et validés.")

        except Exception as e:
            logger.error(f"❌ Erreur de structure YAML lors du crash test : {e}")
            raise

    def get_raw_workflows(self) -> List[Dict[str, Any]]:
        """
        Retourne la liste complète sous forme de dictionnaire.
        Parfait pour `GET /workflows` car ça inclut tous les enums et oneOf du YAML.
        """
        return self._raw_workflows

    def get_raw_workflow_by_id(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        for workflow in self._raw_workflows:
            if workflow.get("id") == workflow_id:
                return workflow
        return None


# Global workflow repository instance
workflow_v2_repository = WorkflowV2Repository()
