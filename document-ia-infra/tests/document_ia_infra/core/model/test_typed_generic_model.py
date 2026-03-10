from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import pytest
from pydantic import BaseModel, Field

from document_ia_infra.core.model.typed_generic_model import GenericProperty


class SimpleModel(BaseModel):
    name: str
    age: int
    active: bool = True


class NestedModel(BaseModel):
    title: str
    simple: SimpleModel


class UserModel(BaseModel):
    first_name: str
    last_name: Optional[str] = None


class ModelWithList(BaseModel):
    users: list[UserModel]


class ModelWithDict(BaseModel):
    metadata: dict[str, str]


class ModelWithDate(BaseModel):
    created_at: date
    updated_at: datetime


class ModelWithDecimal(BaseModel):
    price: Decimal


class ModelWithOptional(BaseModel):
    required: str
    optional: Optional[str] = None


class TestGenericPropertyConvertPydanticModel:
    """Tests unitaires pour GenericProperty.convert_pydantic_model"""

    def test_convert_none_returns_empty_list(self):
        """Test que None retourne une liste vide"""
        result = GenericProperty.convert_pydantic_model(None)
        assert result == []

    def test_convert_simple_model(self):
        """Test conversion d'un modèle simple avec types primitifs"""
        model = SimpleModel(name="John", age=30, active=True)
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 3
        names = {prop.name for prop in result}
        assert names == {"name", "age", "active"}

        props_dict = {prop.name: prop for prop in result}
        assert props_dict["name"].value == "John"
        assert props_dict["name"].type == "string"
        assert props_dict["age"].value == 30
        assert props_dict["age"].type == "number"
        assert props_dict["active"].value is True
        assert props_dict["active"].type == "boolean"

    def test_convert_nested_model(self):
        """Test conversion d'un modèle avec modèle imbriqué"""
        simple = SimpleModel(name="Jane", age=25)
        model = NestedModel(title="Test", simple=simple)
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 2
        props_dict = {prop.name: prop for prop in result}
        assert props_dict["title"].value == "Test"
        assert props_dict["title"].type == "string"

        # Vérifier le modèle imbriqué
        nested_props = props_dict["simple"]
        assert nested_props.type == "object"
        assert isinstance(nested_props.value, list)
        assert len(nested_props.value) == 3

        nested_dict = {prop.name: prop for prop in nested_props.value}
        assert nested_dict["name"].value == "Jane"
        assert nested_dict["age"].value == 25

    def test_convert_list_of_basemodel(self):
        """Test conversion d'une liste de BaseModel"""
        users = [
            UserModel(first_name="Dupont", last_name="Jean"),
            UserModel(first_name="Martin", last_name="Sophie"),
        ]
        model = ModelWithList(users=users)
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 1
        props_dict = {prop.name: prop for prop in result}
        beneficiaires_prop = props_dict["users"]

        assert beneficiaires_prop.type == "list"
        assert isinstance(beneficiaires_prop.value, list)
        assert len(beneficiaires_prop.value) == 2

        # Vérifier le premier bénéficiaire
        first_item = beneficiaires_prop.value[0]
        assert first_item.name == "item"
        assert first_item.type == "object"
        assert isinstance(first_item.value, list)

        first_benef_dict = {prop.name: prop for prop in first_item.value}
        assert first_benef_dict["first_name"].value == "Dupont"
        assert first_benef_dict["last_name"].value == "Jean"

    def test_convert_empty_list_of_basemodel(self):
        """Test conversion d'une liste vide de BaseModel

        Note: Une liste vide ne peut pas être détectée comme liste de BaseModel
        au runtime, donc elle sera traitée comme une liste normale avec type "list"
        """
        model = ModelWithList(users=[])
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 1
        props_dict = {prop.name: prop for prop in result}
        beneficiaires_prop = props_dict["users"]

        # Une liste vide aura le type "list" mais pas de conversion spéciale
        # car on ne peut pas vérifier field_value[0] sur une liste vide
        assert beneficiaires_prop.type == "list"
        # La valeur sera la liste vide elle-même (pas convertie)
        assert beneficiaires_prop.value == []

    def test_convert_dict_str_str(self):
        """Test conversion d'un dictionnaire Dict[str, str]"""
        model = ModelWithDict(metadata={"key1": "value1", "key2": "value2"})
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 1
        props_dict = {prop.name: prop for prop in result}
        metadata_prop = props_dict["metadata"]

        assert metadata_prop.type == "object"
        assert isinstance(metadata_prop.value, list)
        assert len(metadata_prop.value) == 2

        metadata_dict = {prop.name: prop for prop in metadata_prop.value}
        assert metadata_dict["key1"].value == "value1"
        assert metadata_dict["key2"].value == "value2"

    # QUESTION: Est-ce qu'il s'agit d'un cas de test valide ?
    def test_convert_dict_invalid_type_raises_error(self):
        """Test qu'un dictionnaire avec valeurs non-string lève une erreur"""
        # Créer un modèle avec un dict invalide en contournant la validation Pydantic
        model = ModelWithDict(metadata={"key1": "value1"})
        # Modifier directement l'attribut pour avoir une valeur invalide
        model.metadata = {"key1": 123}  # type: ignore

        with pytest.raises(ValueError, match="Seuls les dictionnaires de type Dict\\[str, str\\] sont supportés"):
            GenericProperty.convert_pydantic_model(model)

    def test_convert_date(self):
        """Test conversion d'un champ date"""
        model = ModelWithDate(
            created_at=date(2024, 1, 15), updated_at=datetime(2024, 1, 15, 10, 30)
        )
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 2
        props_dict = {prop.name: prop for prop in result}
        assert props_dict["created_at"].type == "date"
        assert props_dict["created_at"].value == "2024-01-15"
        assert props_dict["updated_at"].type == "date"
        assert props_dict["updated_at"].value == "2024-01-15T10:30:00"

    def test_convert_decimal(self):
        """Test conversion d'un Decimal en float"""
        model = ModelWithDecimal(price=Decimal("123.45"))
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 1
        props_dict = {prop.name: prop for prop in result}
        assert props_dict["price"].type == "number"
        assert props_dict["price"].value == 123.45
        assert isinstance(props_dict["price"].value, float)

    def test_convert_optional_fields(self):
        """Test conversion de champs optionnels"""
        model = ModelWithOptional(required="test", optional=None)
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 2
        props_dict = {prop.name: prop for prop in result}
        assert props_dict["required"].value == "test"
        assert props_dict["optional"].value is None

    def test_convert_optional_fields_with_value(self):
        """Test conversion de champs optionnels avec valeur"""
        model = ModelWithOptional(required="test", optional="optional_value")
        result = GenericProperty.convert_pydantic_model(model)

        assert len(result) == 2
        props_dict = {prop.name: prop for prop in result}
        assert props_dict["required"].value == "test"
        assert props_dict["optional"].value == "optional_value"

    def test_convert_complex_model(self):
        """Test conversion d'un modèle temporaire vers GenericProperty."""
        class TempExperience(BaseModel):
            title: str = Field(description="Job title")
            company: str = Field(description="Company")
            sector: Optional[str] = Field(default=None, description="Sector")
            description: str = Field(description="Responsibilities")

        class TempCV(BaseModel):
            experiences: list[TempExperience]
            skills: list[str]

        model = TempCV(
            experiences=[
                TempExperience(
                    title="Charged de la renovation urbaine",
                    company="Direction Departementale des Territoires",
                    sector="Logement",
                    description="Propose des options strategiques et coordonne.",
                )
            ],
            skills=[
                "Promouvoir une action, une demarche",
                "Connaissance de la politique sociale du logement",
            ],
        )

        result = GenericProperty.convert_pydantic_model(model)

        assert isinstance(result, list)
        props_dict = {prop.name: prop for prop in result}
        assert set(props_dict.keys()) == {"experiences", "skills"}
        assert props_dict["skills"].type == "list"
        assert props_dict["skills"].value == [
            "Promouvoir une action, une demarche",
            "Connaissance de la politique sociale du logement",
        ]
