"""
Pydantic schemas for the TI WEBENCH provider.

The models normalize the reverse-engineered WEBENCH Power Designer API
into stable Python objects before app skills reshape them for users.
They deliberately avoid importing app-specific classes so the provider
can be reused by future electronics skills.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


PowerSupplyType = Literal["dc", "ac"]


class TIWebenchAdvancedInputs(BaseModel):
    """Optional WEBENCH advanced power-design constraints."""

    vinNom: Optional[float] = None
    useInputFilter: bool = False
    cisprStandard: str = ""
    cisprClass: str = ""
    voutMaxRipple: List[float] = Field(default_factory=list)
    ioutNom: Optional[float] = None
    desiredFrequency: Optional[float] = None
    hasExternalFrequencySync: bool = False
    syncPreferredFreq: Optional[float] = None
    minPackageSize: str = ""
    maxComponentHeight: Optional[float] = None
    softStartTime: Optional[float] = None
    useOnlyCeramicCaps: bool = False
    useOnlyShieldedInductors: bool = False


class TIWebenchPowerSearchRequest(BaseModel):
    """Request body accepted by WEBENCH Power Designer solution search."""

    vinMin: float
    vinMax: float
    vout: List[float]
    iout: List[float]
    ambientTemp: float = 30
    isIsolated: bool = False
    powerSupply: PowerSupplyType = "dc"
    optimizationSetting: int = 3
    hasAdvancedOptions: bool = False
    advancedOptionsOrigin: str = "HDI"
    advancedInputs: TIWebenchAdvancedInputs = Field(
        default_factory=TIWebenchAdvancedInputs
    )
    acFrequency: str = "60 Hz"

    @field_validator("vout", "iout")
    @classmethod
    def require_single_output_value(cls, value: List[float]) -> List[float]:
        """WEBENCH accepts arrays; the first Electronics skill supports one rail."""
        if not value:
            raise ValueError("At least one output value is required")
        return value


class TIWebenchDevice(BaseModel):
    """Device metadata returned by a WEBENCH solution."""

    deviceId: Optional[int] = None
    partNumber: str
    basePn: str
    pf_name: Optional[str] = None
    price: Optional[float] = None
    regType: Optional[str] = None
    controlModeName: Optional[str] = None
    topology: Optional[str] = None
    outputType: Optional[str] = None
    vinMin: Optional[float] = None
    vinMax: Optional[float] = None
    voutMin: Optional[float] = None
    voutMax: Optional[float] = None
    appType: Optional[str] = None
    flavor: Optional[str] = None
    isEnablePin: Optional[bool] = None
    isPowerGood: Optional[bool] = None
    isAutomotive: Optional[bool] = None
    isSoftStart: Optional[bool] = None
    isExtSync: Optional[bool] = None
    isLightLoad: Optional[bool] = None
    isSyncSwitch: Optional[bool] = None
    isolated: Optional[str] = None
    package: Optional[str] = None
    ioutMax: Optional[float] = None


class TIWebenchSolutionInfo(BaseModel):
    """Performance and BOM summary returned by WEBENCH."""

    device: TIWebenchDevice
    footprint: Optional[float] = None
    bomCost: Optional[float] = None
    efficiency: Optional[float] = None
    nominalEfficiency: Optional[float] = None
    bomCount: Optional[int] = None
    frequency: Optional[float] = None
    vOutPkPk: Optional[float] = None
    crossoverFreq: Optional[float] = None
    phaseMargin: Optional[float] = None
    topology: Optional[str] = None
    temperature: Optional[float] = None
    maxIout: Optional[float] = None
    isBOMEstimated: Optional[bool] = None
    inductorPkPk: Optional[float] = None
    inputNoiseFilterAdded: Optional[bool] = None


class TIWebenchPowerSolution(BaseModel):
    """A single WEBENCH power solution."""

    id: str
    rank: int
    considerations: Optional[str] = None
    info: TIWebenchSolutionInfo
    raw: Optional[Dict[str, Any]] = None
