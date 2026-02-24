"""Unified patient data model for eGK and KVK/PKV cards."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class PatientData:
    """Unified data model holding patient and insurance data from either card type."""

    # Personal data
    vorname: str = ""
    nachname: str = ""
    geburtsdatum: str = ""  # DD.MM.YYYY
    titel: str = ""
    namenszusatz: str = ""
    vorsatzwort: str = ""
    geschlecht: str = ""  # M/W/D/X (eGK only)

    # Address
    strasse: str = ""
    hausnummer: str = ""
    plz: str = ""
    ort: str = ""
    wohnsitzlaendercode: str = "D"

    # Insurance data
    krankenkasse_name: str = ""
    krankenkassen_nummer: str = ""  # Kostenträgerkennung / IK-Nummer
    versichertennummer: str = ""  # KVNR (eGK) or Versichertennummer (KVK)
    versichertenstatus: str = ""
    versichertenart: str = ""  # 1=Mitglied, 3=Familie, 5=Rentner
    gueltig_bis: str = ""  # MM/YYYY or YYYY-MM-DD

    # KVK-specific
    vknr: str = ""  # VKNR/WOP code
    status_ergaenzung: str = ""

    # Metadata
    card_type: str = ""  # "eGK" or "KVK"
    read_timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M, %d.%m.%Y"))

    @property
    def full_name(self) -> str:
        parts = []
        if self.nachname:
            parts.append(self.nachname)
        if self.vorname:
            parts.append(self.vorname)
        name = ", ".join(parts)
        if self.titel:
            name = f"{name} {self.titel}"
        return name

    @property
    def full_address(self) -> str:
        street = self.strasse
        if self.hausnummer and self.hausnummer not in self.strasse:
            street = f"{self.strasse} {self.hausnummer}"
        return f"{street}, {self.plz} {self.ort}".strip(", ")

    def to_dict(self) -> dict:
        """Serialize to dict for JSON API responses."""
        return asdict(self)

    @classmethod
    def demo_data(cls) -> "PatientData":
        """Create sample data for development/demo mode."""
        return cls(
            vorname="Max",
            nachname="Mustermann",
            geburtsdatum="01.01.1990",
            titel="Dr.",
            strasse="Musterstraße",
            hausnummer="1",
            plz="12345",
            ort="Musterstadt",
            krankenkasse_name="AOK Bayern",
            krankenkassen_nummer="108018007",
            versichertennummer="A123456789",
            versichertenstatus="1",
            versichertenart="1",
            gueltig_bis="12/2026",
            card_type="eGK",
        )
