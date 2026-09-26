# Soil

Ground properties for cable thermal calculations and environmental restoration, prioritising southern England and East Anglia. This repository separates measured observations, model outputs, network design assumptions and hypothetical scenarios.

## Working components

- `import_soil.py`: bounded UKCEH metadata import. The identified observations archive exceeded the download cap; numeric observations are still pending, and no soil conductivity is inferred.
- `import_environment.py`: bounded Natural England SSSI polygon import for conservation context. Designation is not habitat condition or restoration potential.
- `import_network.py`: local study cache of publicly available network thermal-design documents. Failed and blocked requests remain visible; documents are not redistributed.
- `thermal.py`: validated thermal conductivity **W/(m K)** ↔ reciprocal thermal resistivity **K m/W**. Electrical resistivity **ohm m** is a different quantity.
- `gpu_check.py`: CuPy polygon membership checked against an independent CPU winding-angle calculation, plus labelled thermal-unit fixtures.
- `import_ground.py`: bounded, sequential import of open (OGL) ground records for one BNG box (BGS 625k geology, BGS borehole index with scan links, coal Development High Risk Area, EA source protection zones) to `E:\lidar-out\<site>\ground.json`; licences verified in `ground_sources.json`, and licensed or view-only layers (BGS 50k, aquifer designation, mine entries, GeoSure, radon potential, Soilscapes) stay null.
- `ground_check.py`: seeded points in the ground box classified against every imported polygon by a CuPy kernel and a CPU winding-angle witness; zero disagreements required; LF receipt beside `ground.json`.
- `test_ground.py`: offline tests for box clipping, borehole length handling and the ground licence manifest.

All downloaded records and GPU outputs go under ignored `.local/`. Source manifests record scope and rights. A publicly accessible PDF is not automatically open-licensed content.

## Run

Use Python 3.12+. `import_environment.py` uses the standard library. `import_network.py` needs PyMuPDF. GPU verification needs a compatible NVIDIA driver, CUDA/CuPy and NumPy.

```text
python import_environment.py
python import_soil.py
python import_network.py
python -m unittest test_thermal.py test_ground.py
python gpu_check.py
python import_ground.py
python ground_check.py
```

Use the Python interpreter where CuPy is installed for the final command. Imports are bounded, explicit commands; no nationwide crawler or scheduled workflow is enabled.

## Data contract

Retain location/CRS or stated spatial limitation, sampling depth, date, property, value, unit, measured/modelled/scenario status, source and licence. Preserve moisture basis, dry bulk density, temperature and test method wherever supplied. Missing data stays missing. See `thermal_contract.json`.

Soil texture, moisture and density are useful covariates; they are not automatically thermal resistivity. Topsoil samples do not establish conditions at cable depth. Regional defaults do not establish a measured trench value. Thermal conversion alone does not calculate cable ampacity.

## Integration

GridAtlas selects the location. This repository supplies sourced ground/context records. The cable geometry visualiser supplies verified or explicitly estimated dimensions and trench geometry. The graphics engine displays the common coordinates and compact calculated results.

`restoration_sources.json` tracks further transport, water, ecology and farming sources. Catalogue entries explicitly marked discovery are not functioning imports or downloaded datasets.
