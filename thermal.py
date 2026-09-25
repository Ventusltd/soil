"""Scalar/isotropic soil thermal-property conversion; no cable ampacity model.

All numerical inputs to conductivity_to_resistivity are W/(m K). Outputs are
K m/W. Unknown/missing values must be retained separately, never changed to zero.
No site thermal property is inferred from soil texture or other covariates.
"""

from copy import deepcopy
import math
from numbers import Real

CONDUCTIVITY_UNIT = "W/(m K)"
RESISTIVITY_UNIT = "K m/W"
STATUSES = frozenset(("measured", "modelled", "scenario"))


def _positive_finite(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite positive number")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def conductivity_to_resistivity(values):
    """Return a list of reciprocals for a 1-D iterable of positive conductivities.

    This checks the arithmetic only. Use convert_record to retain property status,
    source and conditioning information. A tensor requires a matrix inverse and
    is outside this scalar API. Reject reciprocal overflow instead of emitting inf.
    """
    result = []
    for index, raw in enumerate(values):
        conductivity = _positive_finite(raw, f"conductivity[{index}]")
        resistivity = 1.0 / conductivity
        if not math.isfinite(resistivity) or resistivity <= 0:
            raise ValueError(f"conductivity[{index}] has an unrepresentable reciprocal")
        result.append(resistivity)
    return result


def convert_record(record):
    """Copy a sourced conductivity record and add derived thermal resistivity.

    A 'measured' input remains measured-source evidence; its reciprocal is marked
    derived, rather than represented as an independently measured resistivity.
    Unknown conditioning fields can be null; they cannot imply suitability for
    a particular cable burial depth, moisture state or temperature.
    """
    if not isinstance(record, dict):
        raise ValueError("record must be an object")
    if record.get("conductivity_unit") != CONDUCTIVITY_UNIT:
        raise ValueError(f"conductivity_unit must be {CONDUCTIVITY_UNIT}")
    if record.get("status") not in STATUSES:
        raise ValueError("status must be measured, modelled or scenario")
    source = record.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("a nonempty source citation or scenario identifier is required")
    if record["status"] == "modelled":
        model = record.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("modelled conductivity requires a model identifier/version")
    value = conductivity_to_resistivity([record.get("conductivity")])[0]
    output = deepcopy(record)
    output.update(thermal_resistivity=value, thermal_resistivity_unit=RESISTIVITY_UNIT,
                  thermal_resistivity_derivation="1 / conductivity",
                  thermal_resistivity_evidence="derived_from_" + record["status"],
                  ampacity_calculated=False)
    return output
