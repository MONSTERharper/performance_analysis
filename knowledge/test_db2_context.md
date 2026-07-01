# test_db2 — MongoDB Schema & Relationship Reference

> **Purpose:** This document is the authoritative context for an LLM answering questions about scanner performance data in MongoDB database `test_db2`. Always refer to this document before querying or interpreting data.

---

## 1. Database Overview

| Property | Value |
|---|---|
| Database name | `test_db2` |
| Domain | Digital pathology whole-slide imaging (WSI) scanner performance |
| Collections | 15 |
| Approx. documents | ~141,900 |
| Primary database | Yes — largest and most complete analytics DB |

**What this data tracks:** Daily operational metrics from hospital/lab scanner sites — errors, downtime, load durations, scan quality, slide throughput, scanner configuration, and UI telemetry. Data is ingested from daily ZIP exports (`source_zip`).

**Other databases on same server (for reference only):**
- `local_analytics_db` — legacy analytics, different schema, overlapping concepts
- `test_db3` — subset of test_db2 with one extra collection (`scan_performance_log_statistics_detailed_records`)

---

## 2. Entity Hierarchy

```
Customer (e.g. Stanford, Techcyte)
  └── Site (site_key: stanford--stanford--001)
        └── Cluster (CS001 – CS013)
              └── Station / Position (1, 2, 3, or 4)
                    └── Load (loadIdentifier)
                          └── Slide (slideName)
```

**Cluster:** A group of up to 4 scanner stations sharing one robotic arm.
**Station / Position:** Individual scanner slot within a cluster (values 1–4).
**Load:** A batch of slides loaded into a physical basket for scanning.
**Slide:** A single glass slide being scanned (identified by `slideName` or `sysId`).

---

## 3. Join Keys & Data Conventions

### Primary join keys

| Key | Format | Example | Links |
|---|---|---|---|
| `site_key` | `customer--location--NNN` | `stanford--stanford--001` | **Main key** — connects all operational collections to `sites` |
| `site` | Human-readable name | `Stanford`, `IRM_Freehold` | Display name; may differ slightly from `sites.site_name` |
| `date_str` | `YYYY-MM-DD` | `2026-01-02` | Operational date the data belongs to |
| `source_zip` | File path | `DATA/common_data/2026-01-03/Stanford.zip` | Exact source file for a batch |
| `cluster` / `clusterId` | `CS00N` | `CS004` | Scanner cluster at a site |
| `loadIdentifier` | `CS00N-P-P-timestamp` | `CS003-1-1-1767225577429` | Unique load/batch ID |
| `ingested_at` | ISO timestamp | `2026-06-23T09:49:16` | When record was loaded into MongoDB |

### Batch grouping rule

All operational collections for the same daily export share:
```
site_key + date_str + source_zip
```

Example batch (`stanford--stanford--001`, `2026-01-02`, `Stanford.zip`) contains:
- 55 `scanner_stoppages`, 33 `load_time_analysis`, 12 `scanner_config`, 5 `Error_counts`, 1 each of `raw_error_logs`, `regression_metrics`, `scan_performance_log_statistics_detailed`, `slide_count_values`

### Common metadata fields (on all ingested collections)

| Field | Meaning |
|---|---|
| `site` | Human-readable site name |
| `site_key` | Canonical site identifier |
| `date_str` | Data date (`YYYY-MM-DD`) |
| `source_zip` | Source ZIP file path |
| `ingested_at` | MongoDB insert timestamp |

---

## 4. Collection Relationships

```
customers ──(customer_id / site_keys)──► sites
sites ──(site_key)──► [all operational collections]
scanners ──(scanner_serial_number)──► scan_performance_log_statistics_detailed.records[]
scanner_config ──(clusterId=cluster, position=station)──► scanner_stoppages
raw_error_logs ──(aggregated by error message)──► Error_counts
ingestion_reservation ──(same batch keys)──► ingestion_audit
```

### Relationship matrix

| From | To | Join condition |
|---|---|---|
| `customers` | `sites` | `customers.site_keys` contains `sites.site_key` OR `customers.customer_id = sites.customer_id` |
| `sites` | all operational collections | `sites.site_key = collection.site_key` |
| `scanner_stoppages` | `scanner_config` | `site_key + date_str + cluster = clusterId + station = position` |
| `scanner_stoppages` | `load_time_analysis` | `site_key + date_str + cluster` (same day, same cluster) |
| `raw_error_logs` | `Error_counts` | `site_key + date_str`; Error_counts is aggregated by `error` message |
| `scanners` | `scan_performance_log_statistics_detailed` | `scanners.scanner_id = records[].scanner_serial_number` |
| `ingestion_reservation` | `ingestion_audit` | `collection_name + site_key + date_str + source_zip` |
| `slide_count_values` | `slide_count_values_totals` | `site_key` (daily cycle vs. lifetime totals) |

---

## 5. All 23 Sites

| site_key | site_name | customer |
|---|---|---|
| stanford--stanford--001 | Stanford | Stanford |
| vumc--nashville--001 | VUMC | VUMC |
| cleveland-clinic--cleveland--001 | Cleveland Clinic | Cleveland Clinic |
| moffit--tampa--001 | Moffit-CMS | Moffit |
| histowiz--new-york--001 | Histowiz | Histowiz |
| nordx--portland--001 | NorDx FDA | NorDx |
| intermountain--salt-lake-city--001 | IMHC | Intermountain |
| iron-mountain--earth-city--001 | Iron Mountain (Earth city) | Iron Mountain |
| ironmountain--freehold--001 | Iron Mountain (Freehold) | Ironmountain |
| klinikum--ludwigshafen--001 | Ludwigshafen | Klinikum |
| caris--qa--phoenix--001 | Caris QA | Caris |
| caris--production--phoenix--002 | Caris Production | Caris |
| spectrum-healthcare--portland--001 | Spectral HCP | Spectrum Healthcare |
| splice--worcester--001 | Splice | Splice |
| mayo--rochester--001 | Mayo-2 | Mayo |
| mayo--jacksonville--002 | Mayo-Jacksonville | Mayo |
| jpc--washington--001 | JPC | JPC |
| bd-lab--heidelberg--001 | BD-lab-heidelberg | BD-Lab |
| techcyte--salt-lake-city--001 | Techcyte (2 HT) | Techcyte |
| techcyte--salt-lake-city--002 | Techcyte (Manual 1) | Techcyte |
| techcyte--cytolab--karlsruhe--003 | Techcyte-cytolab | Techcyte |
| techcyte--optipath--frankfurt--004 | Techcyte-optipath | Techcyte |
| techcyte--tyrolpath-cytology--zams--005 | TyrolPath Cytology | Techcyte |

---

## 6. Collection Reference

---

### 6.1 `customers` (~17 docs) — Customer registry

**Purpose:** Top-level organization owning one or more sites.

| Field | Type | Meaning |
|---|---|---|
| `_id` | ObjectId | MongoDB document ID |
| `customer_id` | string | Slug, e.g. `stanford`, `techcyte` |
| `customer_name` | string | Display name |
| `name` | string | Same as customer_name |
| `site_keys` | array[string] | All site_key values for this customer |
| `sites` | array[object] | Embedded site info with aliases |
| `last_updated` | datetime/null | Last registry update |

---

### 6.2 `sites` (~23 docs) — Site registry

**Purpose:** Canonical registry of all scanner installation sites.

| Field | Type | Meaning |
|---|---|---|
| `site_key` | string | **Primary identifier** — `customer--city--NNN` |
| `site_name` | string | Short display name |
| `alias` | array[string] | Alternative names, e.g. `["IMHC", "IMH"]` |
| `customer_id` | string | Parent customer slug |
| `customer_name` | string | Parent customer display name |
| `location` | string | City |
| `total_scanners` | int | Total scanner count |
| `machines` | object | Machine type → count, e.g. `{"HT-4-960-lateral": 13}` |
| `automation_status` | string | Data automation setup status, e.g. `Completed` |
| `generates_report` | boolean | Whether site produces field reports |
| `site_key_map` | array[string] | Lowercase aliases for matching |
| `site_id` | string/null | Legacy site ID |
| `last_updated` | datetime/null | Last update |

---

### 6.3 `scanners` (~413 docs) — Physical scanner hardware registry

**Purpose:** Hardware inventory of scanner devices.

| Field | Type | Meaning |
|---|---|---|
| `scanner_id` | string | Hardware serial number, e.g. `C02C25TA073P` |
| `scanner_type` | string | Generation: `A`, `B`, or `C` |
| `setup` | string | Physical config: `HT-4-960`, `HT4 Cubiq`, `M-Pro`, etc. |
| `workflow` | string | `Clinical` or other |
| `cluster` | string/null | Cluster assignment (mostly unpopulated) |
| `site_key` | string/null | Site assignment (mostly unpopulated) |
| `customer_id` | string/null | Customer assignment (mostly unpopulated) |

**Note:** `site_key` and `cluster` are mostly null. Link to performance data via `scanner_id = records[].scanner_serial_number` in `scan_performance_log_statistics_detailed`.

---

### 6.4 `ingestion_reservation` (~17,487 docs) — Pipeline lock table

**Purpose:** Tracks ingestion batch processing state (lock before insert).

| Field | Type | Meaning |
|---|---|---|
| `collection_name` | string | Target collection |
| `site_key` | string | Site being ingested |
| `date_str` | string | Data date |
| `source_zip` | string | Source file |
| `status` | string | `pending`, `completed`, or `failed` |
| `reserved_at` | datetime | Lock acquired |
| `completed_at` | datetime | Lock released |

**Status distribution:** completed 8,365 | failed 7,148 | pending 1,974

---

### 6.5 `ingestion_audit` (~8,365 docs) — Pipeline success log

**Purpose:** Confirms successful data inserts. All records have `status: inserted`.

| Field | Type | Meaning |
|---|---|---|
| `collection_name` | string | Collection that received data |
| `site_key` | string | Site |
| `date_str` | string | Data date |
| `source_zip` | string | Source file |
| `status` | string | Always `inserted` |
| `ingested_at` | datetime | Insert timestamp |

---

### 6.6 `scanner_stoppages` (~20,283 docs) — Scanner downtime events

**Purpose:** Records idle gaps between consecutive slide scans. Used to detect and diagnose scanner downtime.

| Field | Type | Meaning |
|---|---|---|
| `site` / `site_key` | string | Site identifiers |
| `date_str` | string | Operational date |
| `cluster` | string | Cluster ID, e.g. `CS004` |
| `station` | int | Scanner slot 1–4 within cluster |
| `slideName` | string | Last slide scanned before gap |
| `loadIdentifier` | string | Load batch ID |
| `sysId` | int | Slide system ID (sequential) |
| `prev_sysId` | float | Previous slide system ID |
| `datetime` | string | Stoppage event timestamp (with timezone) |
| `prev_datetime` | string | Previous scan timestamp |
| `createdAt` | float | Unix ms timestamp |
| `expected` | float | Expected timestamp (ms) |
| `diff` | float | Gap duration in **seconds** |
| `total_time` | int/float | Total stoppage time in **minutes** |
| `time_diff` | float | Minutes between consecutive scans |
| `same_load` | boolean | True if gap is within same load batch |
| `weekday` | int | Day of week (0=Monday, 4=Friday) |
| `message` | string | Human-readable stoppage reason |
| `error` | string/null | Error code if applicable |
| `index` | string/null | Primary error category |
| `sc_errors` | string | Scanner-controller errors (`"No error"` if none) |
| `ra_errors` | string | Robotic arm errors |
| `other_errors` | string | Other subsystem errors |
| `all_valid_errors` | string | JSON dict of error counts, e.g. `'{"E-300": 1}'` |

**Top `message` values:**
| message | count | interpretation |
|---|---:|---|
| Different Load | 13,469 | Normal gap between load batches |
| Unknown Issue | 3,891 | Unexplained gap — investigate |
| No Scans | 1,838 | No scanning activity in period |
| Banding detected... | 240 | Quality issue — consecutive banding |
| An internal server error... | 202 | Robotic arm stopped |

**Top `error` codes:** `E-300`, `E-208`, `SCDJ_WHITE_NOT_DETECT`, `HC_UNREACHABLE`, `CONTROLLER_CARD_USB_NOT_DETECTED`

---

### 6.7 `raw_error_logs` (~26,156 docs) — Individual error events

**Purpose:** Granular error records from scanner backend microservices.

| Field | Type | Meaning |
|---|---|---|
| `entityId` | string | Failing entity ID |
| `entityType` | string | `slide` (54%), `scanner` (42%), `roboticArm`, `dropBasket`, `cluster`, `pickBasket` |
| `errorCode` | string | Machine error code |
| `errorRootCause` | string | Human-readable explanation |
| `status` | string | `error` |
| `serviceName` | string | Backend service that logged the error |
| `serviceVersion` | string | Service version, e.g. `v5.25.9` |
| `clusterId` / `cluster` | string | Affected cluster |
| `position` | int | Scanner station position |
| `criticality` | int | `5` = critical (95%), `4` = high |
| `resolved` | boolean | Whether error was resolved |
| `isSyncWithCms` | boolean | Synced to CMS |
| `logsPath` | string | Source log file path on scanner |
| `createdAt` / `updatedAt` | int | Unix ms timestamps |
| `createdAtDate` | string | Human-readable timestamp |
| `pendingDate` | string | When error became pending |
| `errOnSlideName` | string/null | Slide name if slide-specific |
| `apiName` | string/null | API endpoint involved |
| `pageUrl` | string/null | UI page where error occurred |

**Top error codes:**
| errorCode | count | likely meaning |
|---|---:|---|
| DT_CLS_SSD_SLIDE_NOT_FOUND | 10,959 | Slide not found on SSD during transfer |
| MONGO_CONNECTION_ERROR | 3,553 | MongoDB connection failure |
| SCANNER_ACTION_TIMEOUT | 1,590 | Scanner action timed out |
| E-300 | 1,566 | Generic scanner error |
| LABEL_LED_MALFUNCTION | 1,306 | Label LED hardware issue |
| E-208 | 141 | Drop basket not empty |

**Top services:** `data_transfer_consumer`, `wsi_backend`, `viewer_backend`, `cluster_backend`, `wsi_image_processing_service`

---

### 6.8 `Error_counts` (~3,758 docs) — Aggregated daily error frequency

**Purpose:** Daily rollup of error message occurrence counts per site, with cluster/station breakdown.

| Field | Type | Meaning |
|---|---|---|
| `error` | string | Human-readable error message |
| `count` | int | Total occurrences that day |
| `Distribution` | string | Per-cluster/station breakdown, e.g. `'{"CS004_S1": 2}'` = 2 on CS004 station 1 |

**Relationship:** Aggregated view of `raw_error_logs` grouped by `error` message for same `site_key + date_str`.

---

### 6.9 `load_time_analysis` (~14,020 docs) — Per-load scan duration

**Purpose:** How long each slide load batch took from start to finish.

| Field | Type | Meaning |
|---|---|---|
| `clusterId` | string | Cluster, e.g. `CS003` |
| `loadIdentifier` | string | Unique load ID |
| `basket_type` | string | `pramana_basket` (63%), `sakura_basket` (22%), `vertical_basket` (15%) |
| `load_started` | string | Load start timestamp |
| `load_ended` | string | Load end timestamp |
| `duration_seconds` | float | Total duration in seconds |
| `duration_hours` | float | Duration in decimal hours |
| `duration_hms` | string | Duration as `N days HH:MM:SS` |
| `slides_scanned` | int | Total slides in load |
| `slidecount_S1`–`S4` | int | Slides scanned per station 1–4 |

---

### 6.10 `regression_metrics` (~993 docs) — Scan time vs. tissue area correlation

**Purpose:** Daily statistical model per site: does larger scan area predict longer scan time?

| Field | Type | Meaning |
|---|---|---|
| `average_scan_time` | float | Mean scan duration in **seconds** |
| `average_scan_area` | float | Mean scanned tissue area in **mm²** |
| `median_scan_time` | float | Median scan duration (seconds) |
| `median_scan_area` | float | Median scan area (mm²) |
| `count` | int | Number of slides in regression sample |
| `slope` | float | Regression slope (sec per mm²) |
| `intercept` | float | Regression y-intercept |
| `pearson_correlation` | float | R value — fit quality (0.97+ = strong linear relationship) |
| `prediction_225` | float | Predicted scan time at 225 mm² area (seconds) |
| `date` | datetime | Analysis date |

**Interpretation:** High `pearson_correlation` (>0.95) means scan time scales predictably with tissue area. Use `prediction_225` to benchmark expected scan time.

---

### 6.11 `scan_performance_log_statistics_detailed` (~907 docs) — Per-scanner quality stats

**Purpose:** One document per site per day. Contains embedded `records` array with one entry per physical scanner serial number.

**Top-level fields:**
| Field | Type | Meaning |
|---|---|---|
| `site`, `site_key`, `date_str` | string | Identifiers |
| `records` | array[object] | Per-scanner statistical summaries |
| `date` | datetime | Analysis date |

**Each `records[]` entry:**
| Field | Meaning |
|---|---|
| `scanner_serial_number` | Hardware ID, e.g. `C02F25TA112P` |
| `sample_count` | Slides analyzed |
| `missingAoiCount_mean/median/mode` | Missing Areas of Interest statistics |
| `thick_content_ratio_mean/median/mode` | Tissue thickness ratio stats |
| `stain_percentage_mean/median/mode` | Stain coverage percentage stats |
| `total_Acq_Time_mean/median/mode` | Image acquisition time (seconds) |
| `total_PostProcessing_Time_mean/median/mode` | Post-processing time (seconds) |
| `total_Acq_Area_mean/median/mode` | Scanned area (mm²) |
| `rescan_FOVs_mean/median/mode` | Fields of view rescanned |
| `probed_Points_mean/median/mode` | Autofocus probe points used |
| `slide_total_rows_mean/median/mode` | Image row count |
| `total_snap_miss_count_mean/median/mode` | Missed image snap count |
| `fusion_status_counts` | Image fusion quality: `{optimal: N, acceptable: N}` |
| `focus_metric_dist_status_counts` | Focus quality: `{acceptable: N, warning: N}` |
| `displacement_status_counts` | Stage displacement: `{passed: N, failed: N}` |
| `stack_shift_status_counts` | Z-stack alignment status |
| `slide_prep_grade_counts` | `{Good slide preparation: N, Poor Slide Preparation: N}` |
| `floater_flag_counts` | Tissue floater detection: `{No floater: N, Possible floater: N}` |
| `magnification_counts` | Magnification used: `{40: N, 60: N}` |
| `acquired_magnification_counts` | Acquired magnification: `{40x: N, 60x: N}` |
| `rescanBecauseOfOutOfFocus_counts` | Rescans due to focus issues |
| `image_capturing_error_counts` | Image capture failures |
| `log_file_present_counts` | Whether scan log file was available |

---

### 6.12 `scanner_config` (~15,948 docs) — Scanner settings snapshot

**Purpose:** Configuration state of each cluster station on a given day.

| Field | Type | Meaning |
|---|---|---|
| `clusterId` | string | Cluster, e.g. `CS001` |
| `position` | int | Station/slot number 1–4 |
| `isAutoQCEnabled` | boolean | Auto quality control enabled |
| `isAutoTransferEnabled` | boolean | Auto cloud transfer enabled |
| `autoQCGridCriteria` | string | QC grid method, e.g. `multi` |
| `autoTransferToCloudForAutoQC` | boolean | Transfer after auto QC pass |
| `autoTransferToCloudForManualQC` | boolean | Transfer after manual QC |
| `bufferBetweenQCAndTransfer` | string | Wait between QC and transfer, e.g. `120M` |
| `shouldAutoQCRescanErredSlides` | boolean | Auto-rescan slides failing QC |
| `shouldAutoQCPassUnstainedSlides` | boolean | Pass unstained slides through QC |
| `isDeleteSlideAfterTransferToCloudEnabled` | boolean | Delete local copy after cloud transfer |
| `zStack` / `zStackSize` | bool/int | Z-stack imaging enabled and depth |
| `slotCount` | int | Number of slide slots (typically 4) |
| `bufferSlidesCountToRunPOST` | int | Slides before POST calibration |
| `bufferTimeToRunPost` | int | Hours between POST calibrations |
| `available_magnifications` | string (JSON) | Objective/magnification configs per slot |
| `slideQCCriteria.focusErrorPercentage.range` | string | QC threshold for focus error, e.g. `[0, 0.5]` |
| `slideQCCriteria.stitchingErrorPercentage.range` | string | QC threshold for stitching error |
| `slideQCCriteria.bandingGrade.range` | string | QC threshold for banding grade |
| `macroImageAutoPreviewList` | string (JSON) | Auto-preview image types |
| `createdAt` / `updatedAt` | float | Config timestamps (Unix ms) |

---

### 6.13 `slide_count_values` (~1,942 docs) — Daily slide throughput per cycle

**Purpose:** Slide processing counts for a specific reporting cycle at a site.

| Field | Type | Meaning |
|---|---|---|
| `Date range` | string | Reporting window, e.g. `2025-12-31 to 2026-01-01` |
| `Current Slides Queue` | int | Slides waiting in queue |
| `Specified cycle slides scanned` | int | Scanned in this cycle |
| `Specified cycle slides transfered` | int | Transferred to cloud |
| `Specified cycle slides scanned and transfered` | int | Both scanned and transferred |
| `Specified cycle slides transfer pending` | int | Awaiting transfer |
| `Specified cycle slides unreviewed` | int | Not yet reviewed by pathologist |
| `Specified cycle slides marked for rescan` | int | Flagged for rescan |
| `Specified cycle Auto QC count` | int | Auto QC processed |
| `Specified cycle Auto QC percentage` | float | Auto QC rate |
| `Specified cycle withheld count` | int | Held back slides |
| `Specified cycle deid error count` | int | De-identification errors |

---

### 6.14 `slide_count_values_totals` (~17 docs) — Lifetime cumulative totals

**Purpose:** One record per site with all-time running totals (not per-day).

| Field | Type | Meaning |
|---|---|---|
| `Total slides scanned` | int | All-time scanned count |
| `Total slides reviewed` | int | Reviewed by pathologist |
| `Total slides unreviewed` | int | Pending review |
| `Total Slides marked for rescan` | int | Flagged for rescan |
| `Total Slides marked for terminated` | int | Terminated/cancelled |
| `Total Slides marked for Expert Review` | int | Sent to expert review |
| `Total Slides transferred` | int | Sent to cloud |
| `Total Slides NOT transferred` | int | Failed/pending transfer |
| `Total Slides DEID pending` | int | Awaiting de-identification |
| `Total Slides DEID error` | int | De-ID failures |

---

### 6.15 `extracted_cta_logs` (~31,575 docs) — UI click/action telemetry

**Purpose:** User interaction logs from the scanner dashboard (CTA = Click-Through Action).

| Field | Type | Meaning |
|---|---|---|
| `level` | string | `info` (80%), `CTA` (19%), `error` (<1%) |
| `message` | string | Action description, e.g. `Clicked on menu /hts/slides` |
| `timestamp` | string | Action time (ISO 8601) |
| `workflow` | string | UI workflow, e.g. `Dashboard` |
| `module` | string | Source module (always `ui` in current data) |
| `clusterID` | string | Cluster where action occurred |
| `entityID` / `entityType` | string | Entity acted upon |
| `tabID` | string | Browser tab session ID |
| `siteOrigin` | string | Site name as seen in UI |
| `createdAt` / `updatedAt` | float | Unix ms timestamps |

---

## 7. Domain Glossary

| Term | Definition |
|---|---|
| WSI | Whole Slide Imaging — digitizing glass pathology slides |
| Cluster (CS00N) | Group of up to 4 scanner stations sharing one robotic arm |
| Station / Position | Individual scanner slot (1–4) within a cluster |
| Load | Batch of slides loaded into a basket for scanning |
| Basket type | Physical slide holder: Pramana, Sakura, or Vertical |
| Stoppage | Idle gap between consecutive scans; may indicate a problem |
| AOI | Area of Interest — tissue region selected for scanning |
| FOV | Field of View — individual image tile captured during scan |
| QC | Quality Control — automated or manual slide image review |
| DEID | De-identification — removing patient info from slide images |
| POST | Periodic Optical System Test — scanner calibration routine |
| CTA | Click-Through Action — UI telemetry event |
| Pramana / Sakura / Vertical | Physical basket/slide holder types |
| sysId | Sequential slide system identifier within a site |
| source_zip | Daily data export ZIP from a site |
| site_key | Canonical identifier: `customer--location--NNN` |

---

## 8. Example MongoDB Queries

### Get all data for a site on a specific date
```javascript
db.scanner_stoppages.find({ site_key: "stanford--stanford--001", date_str: "2026-01-02" })
```

### Top error codes across all sites
```javascript
db.raw_error_logs.aggregate([
  { $group: { _id: "$errorCode", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 10 }
])
```

### Average load duration by site
```javascript
db.load_time_analysis.aggregate([
  { $group: { _id: "$site", avg_duration: { $avg: "$duration_seconds" }, loads: { $sum: 1 } } },
  { $sort: { avg_duration: -1 } }
])
```

### Stoppages with actual errors (excluding normal "Different Load")
```javascript
db.scanner_stoppages.find({
  error: { $ne: null },
  message: { $nin: ["Different Load", "No Scans"] }
})
```

### Regression metrics for a site over time
```javascript
db.regression_metrics.find({ site_key: "stanford--stanford--001" }).sort({ date_str: 1 })
```

### Join stoppages to errors for same cluster on same day
```javascript
// Step 1: get stoppages
db.scanner_stoppages.find({ site_key: "stanford--stanford--001", date_str: "2026-01-02", cluster: "CS004" })
// Step 2: get errors for same
db.raw_error_logs.find({ site_key: "stanford--stanford--001", date_str: "2026-01-02", clusterId: "CS004" })
```

### Site lifetime slide totals
```javascript
db.slide_count_values_totals.find({ site_key: "stanford--stanford--001" })
```

### Scanner config for all clusters at a site on a date
```javascript
db.scanner_config.find({ site_key: "stanford--stanford--001", date_str: "2026-01-02" })
```

---

## 9. Important Notes for the LLM

1. **Always use `site_key`** (not `site` name) for reliable joins — site names can have inconsistent formatting (`IRM_Freehold` vs `IRM-Freehold`).
2. **`date_str` is the operational date**, not necessarily the ingestion date (`ingested_at`). Data for `2026-01-02` may come from a ZIP dated `2026-01-03`.
3. **`scanner_stoppages.message = "Different Load"`** is normal operation (13,469 records) — not an error. Filter it out when analyzing real problems.
4. **`slide_count_values`** is per-cycle daily data; **`slide_count_values_totals`** is lifetime per-site (only 17 records, one per site).
5. **`scanners` collection** has mostly null `site_key` — link via `scanner_serial_number` in performance records instead.
6. **`ingestion_reservation`** has many `failed` records (7,148) — these are pipeline retries, not data errors.
7. **Units:** `diff` in stoppages = seconds; `total_time` = minutes; `duration_seconds` in load_time = seconds; scan times in regression = seconds; scan area = mm².
8. **Database to query:** Always use `test_db2` unless explicitly asked about other databases.
