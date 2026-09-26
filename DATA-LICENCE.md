# Data licence

The code in this repository is licensed under the Apache License 2.0 (see `LICENSE`).
That licence does **not** cover data.

## Data derived from third-party sources

Every file this repository imports, cuts or derives from a third-party source (for example `ground.json`,
the soil, environment and network extracts, and GPU receipts that carry source values) keeps the licence of
the source it came from. No licence in this repository grants rights over data that was never ours to license.

- The licence, licence link and required attribution statement of each source are recorded in the source
  manifests: `ground_sources.json`, `soil_sources.json`, `environment_sources.json`, `network_sources.json`
  and `restoration_sources.json`. Wherever derived data is shown or redistributed, carry the statement given
  there for every source it uses, and do not suggest that the publisher endorses the work.
- The sources imported by default are published under the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
  (British Geological Survey, Mining Remediation Authority, Environment Agency, Natural England, UK Centre for
  Ecology & Hydrology).
- Sources marked licensed, paid or view-only in the manifests are not imported, and their layers stay null.
  A publicly accessible document is not automatically open-licensed; network operator documents are cited,
  not republished.

## Our own written material

Documentation, receipts and reports written for this repository are licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/) (CC BY 4.0). Commercial use is allowed.
