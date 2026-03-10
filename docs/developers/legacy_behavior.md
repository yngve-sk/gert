# ERT Legacy Behaviors

This document catalogs legacy behaviors extracted from the existing ERT codebase. These are concrete behaviors the current system exhibits that may affect compatibility, testing, failure semantics, and user workflows during migration to GERT.

---

## Behavior
Silent File Backups in Runpaths

### What happens
- Before ERT writes export files (like `parameters.txt`, `parameters.json`, or `jobs.json`) into a realization's runpath, it checks if the file already exists. If it does, ERT renames the existing file by appending `_backup_<timestamp>` to the filename.

### Where observed
- **files:** `src/ert/run_models/_create_run_path.py`
- **functions/classes/tests:** `_backup_if_existing()`, called before `_value_export_txt`, `_value_export_json`, and jobs/manifest JSON writes.

### Trigger / conditions
- Re-running an iteration, or any condition where `_create_run_path` targets an already-populated directory.

### Visible effect
- Accumulation of multiple `_backup_YYYYMMDDTHHMMSS` files in the runpath directories. 

### Evidence
- `new_path = path.parent / f"{path.name}_backup_{timestamp}"; path.rename(new_path)`

### Classification
- confirmed

### Likely importance
- incidental

### Compatibility note
- redesign (Modern systems using isolated execution sandboxes or clean scratch directories should not need this manual backup logic).

### Notes
- This looks like an accidental legacy quirk designed to prevent data loss when restarting jobs or running in dirty environments, rather than a strictly required simulation feature.

---

## Behavior
Forward Init Parameter Skipping

### What happens
- Parameters marked with `forward_init=True` are deliberately omitted from the `parameters.txt` and `parameters.json` files *only* during Iteration 0. Instead, their expected file paths are injected into a `manifest.json` file.

### Where observed
- **files:** `src/ert/run_models/_create_run_path.py`
- **functions/classes/tests:** `_generate_parameter_files()`, `_manifest_to_json()`

### Trigger / conditions
- Exporting parameters for a realization where `iteration == 0` and the parameter configuration has `forward_init=True`.

### Visible effect
- The forward model execution environment on iteration 0 lacks prior parameters; the forward model is expected to generate them itself.

### Evidence
- `if param.forward_init and iteration == 0: continue`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve exactly

### Notes
- This is a core ERT mechanism for allowing forward models (like reservoir simulators) to sample their own priors on the first run, rather than relying on ERT's `probabilit` sampling. 

---

## Behavior
Implicit LOG10 Transformation for GenKw Parameters

### What happens
- If a `GenKwConfig` parameter is defined with `LogNormalSettings` or `LogUnifSettings`, ERT automatically calculates the base-10 logarithm of the sampled value and exports it alongside the original value. The exported key is prefixed with `LOG10_<group_name>`.

### Where observed
- **files:** `src/ert/run_models/_create_run_path.py`
- **functions/classes/tests:** `_generate_parameter_files()`

### Trigger / conditions
- Serializing parameter sets containing logarithmic distributions.

### Visible effect
- `parameters.txt` and `parameters.json` will contain undocumented, synthetic keys (e.g., `LOG10_MYGROUP:MYPARAM`).

### Evidence
- `log_value = math.log10(scalar_value); log_export_values = {f"LOG10_{group_name}": {param.name: log_value}}`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve exactly

### Notes
- This is a strong example of hidden coupling. Legacy forward models likely rely on finding the pre-calculated `LOG10_...` variables in the `parameters.txt` file and will fail if the generic ERT runner stops injecting them.

---

## Behavior
Design Matrix Formatting Anomaly

### What happens
- When writing parameters to `parameters.txt`, standard parameters are formatted as `<group_name>:<parameter_name> <value>`. However, if the group is `<DESIGN_MATRIX>`, the group name and colon are deliberately omitted, writing only `<parameter_name> <value>`.

### Where observed
- **files:** `src/ert/run_models/_create_run_path.py`
- **functions/classes/tests:** `_value_export_txt()`

### Trigger / conditions
- Exporting a parameter belonging to the `DESIGN_MATRIX_GROUP`.

### Visible effect
- Inconsistent formatting in the `parameters.txt` file.

### Evidence
- `if key == DESIGN_MATRIX_GROUP: print(f"{param} {value_str}", file=f) else: print(f"{key}:{param} {value_str}", file=f)`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve approximately

### Notes
- Parsers in legacy forward models likely expect this specific (lack of) prefixing when a design matrix is utilized.

---

## Behavior
Runpath List Workflow Integration

### What happens
- ERT creates a file (by default `.ert_runpath_list`) at the root of the experiment, containing space-delimited rows of: `realization_id`, `runpath`, `jobname`, and `iteration_id`.

### Where observed
- **files:** `src/ert/runpaths.py`
- **functions/classes/tests:** `write_runpath_list()`

### Trigger / conditions
- After generating the realization runpaths for an iteration.

### Visible effect
- A physical file named `.ert_runpath_list` is created in the base directory.

### Evidence
- Docstring: "The runpath list file is parsed by some workflows in order to find which path was used by each iteration and ensemble."

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve exactly

### Notes
- Highly coupled to external user workflows (likely shell scripts) that grep/awk this text file to locate realization output directories. If GERT removes this file, those workflows will break.

---

## Behavior
Interleaved General Observation Files

### What happens
- When `GENERAL_OBSERVATION` configurations reference an `OBS_FILE`, ERT parses the text file as a 1D array using `np.loadtxt` and expects it to be an interleaved list of `[value1, std_dev1, value2, std_dev2, ...]`.

### Where observed
- **files:** `src/ert/config/_observations.py`
- **functions/classes/tests:** `GeneralObservation.from_obs_dict()`

### Trigger / conditions
- Parsing a user configuration that uses `GENERAL_OBSERVATION` with an `OBS_FILE`.

### Visible effect
- Enforces an implicitly strict layout for plain text observation files.

### Evidence
- `values = file_values[::2]; stds = file_values[1::2]`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve exactly

### Notes
- Users have large historical datasets formatted using this specific interleaving. A generic parser must emulate this exact `numpy` slicing to maintain backward compatibility with old `.txt` observation files.

---

## Behavior
Rejection of RMS "Missing Data" Markers (-1 / 0)

### What happens
- If an RFT observation CSV contains a row where the value is `-1` and the error is `0`, ERT will refuse to parse it and raises a fatal `ObservationConfigError`, forcing the user to manually remove the data.

### Where observed
- **files:** `src/ert/config/_observations.py`
- **functions/classes/tests:** `RFTObservation.from_csv()`

### Trigger / conditions
- Loading an RFT CSV file.

### Visible effect
- Hard crash/validation failure during setup.

### Evidence
- `if rft_observation.value == -1 and rft_observation.error == 0: invalid_observations.append(...)` and comment: `used by fmu.tools.rms create_rft_ertobs to indicate missing data.`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve exactly

### Notes
- This is a direct, hardcoded coupling to the behavior of an external Equinor tool (`fmu.tools.rms`). ERT actively protects the mathematical update steps from digesting these dummy "missing data" values.

---

## Behavior
Parse-Time Evaluation of Error Modes

### What happens
- The concepts of relative errors (`REL`, `RELMIN`) are not preserved as system state. When ERT parses an observation configuration, it immediately calculates the absolute error value using the provided `VALUE` and `ERROR` inputs, and stores only the resulting absolute float. 

### Where observed
- **files:** `src/ert/config/_observations.py`
- **functions/classes/tests:** `SummaryObservation.from_obs_dict()`

### Trigger / conditions
- Instantiating a `SummaryObservation`.

### Visible effect
- The internal Pydantic models (and presumably the storage layer) only know about absolute error standard deviations.

### Evidence
- `match error_mode: case ErrorModes.REL: error = validate_positive_float(np.abs(value) * input_error ...)`

### Classification
- confirmed

### Likely importance
- essential

### Compatibility note
- preserve approximately

### Notes
- This means GERT's `Observation` objects only need a `std_dev` property (as established in previous architectural discussions), because the conversion from relative percentages to absolute standard deviation happens immediately at parse time. 

---

## Summary of highest-priority legacy behaviors
- **Forward Init Skipping**: Parameters marked `forward_init` are omitted from the parameter file injections on Iteration 0.
- **Log10 Injections**: Generating undocumented `LOG10_<group>` parameter variables for LogNormal/LogUniform distributions.
- **Runpath List Text File**: Creating the `.ert_runpath_list` file for external shell scripts to grep.
- **Interleaved Arrays**: Reading `GENERAL_OBSERVATION` flat text files as interleaved `[value, std, value, std]` arrays.

## Behaviors strongly coupled to specific forward models
- **RMS Missing Data Rejection**: Crashing when RFT files contain the `fmu.tools.rms` missing data marker (`value=-1`, `error=0`).
- **Design Matrix formatting**: Removing the group prefix in `parameters.txt` exclusively for the `DESIGN_MATRIX` group.

## Behaviors that look like accidental legacy quirks
- **Silent File Backups**: Appending `_backup_<timestamp>` to files in the scratch directory instead of cleaning the directory or failing safely.

## Behaviors likely to affect new test design
- Ensure tests for parsing `GeneralObservation` provide flat arrays with even lengths, checking `[::2]` and `[1::2]` slicing logic.
- Ensure the `LOG10_` variables are explicitly asserted in parameter export integration tests.