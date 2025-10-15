from typing import Optional

from pydantic import BaseModel


class AvisImpositionExtract(BaseModel):
    annee_revenus: str
    revenu_fiscal_reference: float
    declarant_1_nom: str
    declarant_1_prenom: Optional[str] = None
    declarant_1_numero_fiscal: Optional[str] = None
    reference_avis: Optional[str] = None
    nombre_parts: Optional[float] = None
    date_mise_en_recouvrement: Optional[str] = None
    revenu_brut_global: Optional[float] = None
    revenu_imposable: Optional[float] = None
    impot_revenu_net_avant_corrections: Optional[float] = None
    montant_impot: Optional[float] = None
