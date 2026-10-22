# OpenRad-Agent: complete beginner’s guide for hackathon judges

**Code inspected:** [`7f09598`](https://github.com/MYT2004/OpenRad-Agent/commit/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb) (efficiency improvements and regression evidence). Documentation reviewed 23 October 2026. Later revisions may change controls or results.

This guide revises the Antigravity-supplied evaluator draft against the actual implementation. It is the detailed companion to the [root README](../../README.md), not a second application specification. Examples use synthetic data or clearly marked placeholders. No patient files, credentials or private audit details are included.

**Start here:** [five-minute tour](#five-minute-tour) · [all nine menus](#menu-index) · [fresh installation](#18-for-a-judge-starting-on-a-fresh-computer) · [data sources and citations](../DATA_SOURCES.md)

## Five-minute tour

If the app is not running, use the fresh-installation instructions below first. This tour needs no Gemini account or real patient data.

1. Open `http://127.0.0.1:8501/`. In **Patient-file Verification**, enter `data/demo/01_clean_case`, pseudonym `judge-demo-001`, and leave **Decode image and dose pixels** checked. Click **Verify patient files**. Expect `READY_FOR_RESEARCH_ANALYSIS`, not treatment approval.
2. Click **Continue to DVH and structure review**. Select **Brainstem** and **PTV**, keep the mapping `{}`, and click **Compute DVH**. Inspect two cumulative dose-volume curves, units and limitations. Save a Markdown report if useful.
3. Return to **Patient-file Verification**, enter `data/demo/02_missing_image` and click **Verify patient files**. Expect `BLOCKED` and an action requesting a complete referenced image export. The disabled DVH handoff is intended behavior. Do not combine clean and defective case folders.
4. In **Gamma Index QA (AAPM TG-218)**, use reference `data/demo/01_clean_case/synthetic_dose.dcm` and evaluated `data/demo/05_gamma_controls/small_controlled_difference.dcm`. Keep 3% / 2 mm / 10% and spacing `[]`. Click **Evaluate Gamma Index**: expect 100%. Replace only the evaluated file with `large_controlled_difference.dcm`: expect 0%. These are constructed controls, not independent patient-model validation.
5. To return to a clean demonstration, verify `data/demo/01_clean_case` again. Use its handoff or rescan it in the sidebar before another DVH calculation.

An expected refusal is a successful negative test. An unexpected exception or missing result is a separate software/configuration issue to investigate.

## Menu index

| Workflow | Detailed instructions |
|---|---|
| Patient-file Verification | [Menu 1](#6-menu-1-patient-file-verification) |
| 🤖 Dynamic Agent Copilot | [Menu 2](#7-menu-2-dynamic-agent-copilot) |
| DICOM-RT & DVH Analyzer | [Menu 3](#8-menu-3-dicom-rt--dvh-analyzer) |
| Gamma Index QA (AAPM TG-218) | [Menu 4](#9-menu-4-gamma-index-qa-aapm-tg-218) |
| TOPAS Monte Carlo Deck Generator | [Menu 5](#10-menu-5-topas-monte-carlo-deck-generator) |
| Radiobiology (TCP / NTCP) | [Menu 6](#11-menu-6-radiobiology-tcp--ntcp) |
| Model Evaluation & Triage | [Menu 7](#12-menu-7-model-evaluation--triage) |
| Interactive Agent Query | [Menu 8](#13-menu-8-interactive-agent-query) |
| Stateful Python REPL Sandbox | [Menu 9](#14-menu-9-stateful-python-repl-sandbox) |

## 1. What you are testing

OpenRad-Agent is a research prototype that brings several radiation-physics tools into one interface. You can inspect a set of medical-image files, calculate descriptive dose statistics, compare two dose distributions, prepare a radiation-simulation input file, and review supplied model predictions against rules.

You are **not** testing a clinically commissioned treatment planning system. A green result never authorizes treatment. You are also not testing an app that trains or runs every uploaded AI model. In its Model Evaluation menu, the model’s predicted arrays must already exist.

For the beginner demonstration, use the bundled **synthetic teaching files**. They depict artificial regions and dose values, not an actual patient or a clinically valid treatment prescription. They let you test both working calculations and deliberate data problems without medical expertise.

The current local app is at **http://127.0.0.1:8501/**. `127.0.0.1` means “this computer.” That address will not open this machine’s app on another judge’s computer. A remote judge must start their own copy or use an appropriately hosted instance supplied by the team.

## 2. A small vocabulary before you click

| Term | Meaning for this demonstration |
|---|---|
| DICOM | A standard format for medical images and related information. Usually represented here by `.dcm` files. |
| CT | A stack of cross-sectional images. Several slices form a 3D image volume. |
| RTPLAN | A radiotherapy plan object. It identifies the planned treatment and references related objects. Its presence alone does not prove a deliverable or clinically appropriate treatment. |
| RTSTRUCT | Structure contours: outlines identifying regions in image coordinates. |
| RTDOSE | A grid of calculated radiation-dose values. |
| Dose | Energy absorbed per unit mass. Here its unit is gray, abbreviated **Gy**. |
| Voxel | A 3D pixel. A dose grid contains one dose value per voxel. |
| ROI | Region of interest: a selected outlined area or volume. |
| PTV | Planning target volume. In the teaching example it is just an illustrative artificial region. |
| OAR | Organ at risk: a region whose exposure needs assessment. A name alone cannot establish correct anatomy. |
| DVH | Dose-volume histogram. It summarizes how much of a region receives a given dose. It loses spatial location information. |
| Frame of reference | An identifier associating coordinates with a common spatial frame. A mismatch needs investigation or validated registration. |
| Gamma | A mathematical comparison of two dose distributions using dose difference and spatial distance together. |
| TOPAS / Geant4 | External software for particle-transport simulation. OpenRad prepares a parameter template; this UI does not run the transport calculation. |
| TCP / NTCP | Model estimates of tumor control / normal-tissue complication probability, conditional on supplied assumptions and calibration. |
| JSON | Structured text with braces, quoted keys and values. It is not ordinary prose. |
| NPY | A NumPy array file, ending `.npy`. It contains numerical arrays. Renaming a DICOM file to `.npy` does not convert it. |
| Mask | An array of 0/1 values showing which voxels belong to a region. |
| Hash / SHA-256 | A fingerprint of file contents. It helps detect changes; it does not prove clinical correctness. |
| OOD | Out of distribution: an input unlike the model’s qualified training/validation setting. This evaluator consumes externally supplied OOD information. |
| Artifact | A generated report, plot, parameter file or other saved output. |

## 3. Files you can use immediately

Paths below are relative to the **repository root**, the folder containing `README.md`, `agent_main.py` and `frontend/`.

| Path | Purpose | Expected result |
|---|---|---|
| `data/demo/01_clean_case` | Five matching CT slices plus one plan, structure and dose object | Intake: `READY_FOR_RESEARCH_ANALYSIS` |
| `data/demo/02_missing_image` | One referenced CT slice is deliberately absent | Intake: `BLOCKED`, with a missing-reference finding |
| `data/demo/03_frame_mismatch` | Structure/dose coordinate-frame association is deliberately inconsistent | Intake: `BLOCKED` |
| `data/demo/04_invalid_scaling` | Dose scaling is deliberately negative | Intake: `BLOCKED` |
| `data/demo/05_gamma_controls/small_controlled_difference.dcm` | Synthetic dose variant with a small controlled difference | Gamma: 100% at the supplied default 3% / 2 mm / 10% settings |
| `data/demo/05_gamma_controls/large_controlled_difference.dcm` | Synthetic dose variant with a large controlled difference | Gamma: 0% at those same settings |

The gamma reference is `data/demo/01_clean_case/synthetic_dose.dcm`.

**Select one case folder at a time.** Do not verify `data/demo/` as if it were a single patient. The different defect examples deliberately share teaching identities with different content. Combining them creates an ambiguous dataset. The `05_gamma_controls` folder is for dose comparison, not complete-case intake.

For an absolute path, use the `data/demo/01_clean_case` directory inside **your own clone**. Launching from the repository root makes the relative examples below work. Paths are resolved by the computer running the server.

### Path rules that prevent most beginner mistakes

- A **folder** box expects a directory such as `data/demo/01_clean_case`.
- A **file** box expects a full file path such as `data/demo/01_clean_case/synthetic_dose.dcm`.
- A **JSON** box expects JSON, not a pathname to a JSON file, unless the label explicitly says path.
- A **task** box expects a short instruction, not Python or JSON.
- A **Python code** box runs Python and is a separate advanced feature.
- Ordinary path boxes do not need quotation marks around the path. JSON path strings do.
- A GitHub URL is not a local file path. A path refers to the computer running the app, not necessarily the computer displaying the browser.
- Typing a path does not upload a file. The file must already exist on the app server.
- Inputs and runtime outputs must be separate. Never set output/session storage inside a source case or protected raw-data directory.

## 4. Status words: what the app actually means

### Case intake statuses

| Display | Meaning | Judge’s next action |
|---|---|---|
| `READY_FOR_RESEARCH_ANALYSIS` | The implemented intake checks found no blocking or review findings in this selected directory. | Continue to supported calculations. Do not interpret this as treatment or general data-quality certification. |
| `FLAGGED_FOR_REVIEW` | At least one review finding remains, with no blocking finding. | Read the affected scope and follow-up action. Obtain qualified review where appropriate. |
| `BLOCKED` | At least one blocking finding prevents use under this workflow. | Inspect the reason. Correct the export/configuration through an authorized process, or use a supported workflow. Preserve originals. |

A blocked case may contain malformed data, missing objects, unsupported but valid geometry, or a dose grid above the configured resource limit. It is not automatically evidence of an incorrect original clinical treatment.

The GUI’s **Continue to DVH and structure review** button is disabled for BLOCKED cases. In the current implementation it can remain available for FLAGGED_FOR_REVIEW. That availability does not resolve the findings.

### Supplied-model evaluation statuses

| Display | Meaning |
|---|---|
| `APPROVED` | The supplied case satisfies all implemented policy rules and evidence-presence requirements. It is a **research candidate on this case**, not approval of a model across all patients or for clinical use. |
| `FLAGGED_FOR_REVIEW` | There is no rejecting rule, but some metric lies in a review band, evidence is absent, or scope/uncertainty remains unresolved. |
| `REJECTED` | At least one evaluation rule rejects the supplied case. Reasons can include invalid numerical inputs, geometry disagreement, or a comparison metric outside the configured policy. |

One rejecting rule takes precedence over review and pass rules. If none reject but any require review, the overall result requires review. Only all-pass rules yield APPROVED. `hard_checks_passed=true` alone does not mean APPROVED; another dosimetric or evidence rule can still prevent it.

### Copilot statuses are different

In **this exact revision**, the Dynamic Copilot’s overall disposition is `REJECTED` for certain explicit failures and `FLAGGED_FOR_REVIEW` otherwise. It **does not assign overall APPROVED**, even after successful tools. The GUI has a branch for displaying APPROVED, but the current runner does not produce that overall disposition.

Read individual tool observations too. `COMPLETED` means a calculation ran; `GENERATED` means a template was produced. `PASS_CANDIDATE`, `REVIEW` and `REJECT` can describe an individual gamma comparison. These are not treatment approvals. Provider/argument errors can produce a stopped run with review disposition and no numerical evidence.

### Error versus decision

A red message such as `Evaluation rejected: ...` can be a JSON/schema error **before model evaluation starts**. It is not necessarily a completed, audited REJECTED model decision. `Execution successful` in the REPL only means that code execution and its implemented checks completed. It is not a medical conclusion.

## 5. Shared sidebar and controls

| Control | What to enter / do | What it actually does |
|---|---|---|
| **Select Workflow** | Choose one of the nine workflows below. | Changes the visible tool. It does not itself calculate or authorize anything. |
| **Local data folders (one per line)** | For the first test, enter `data/demo/01_clean_case`. To scan several separate folders, put one directory on each line, not a JSON list. | Supplies directories to the scanner. It does not change a patient’s data. |
| **Scan folders** | Click after changing the folder list. | Reads DICOM metadata, counts object types and finds linked dose/plan/structure combinations. This is discovery, not the full pixel-enabled case verifier. |
| **Linked RTDOSE / RTPLAN / RTSTRUCT** | Appears after scanning finds doses. Choose the intended combination. | Sets the selected source combination used by DVH and some default inputs. If several look similar, inspect **Source files and provenance**. The visible label is not independent proof of course identity. |
| Sidebar error messages | Read, do not dismiss as cosmetic. | Indicate unreadable/duplicate files or unsupported associations from discovery. |
| Collapsible instruction/provenance panels | Open to read. | Reveal explanations, file selections or structured results. Expanding a panel does not run a calculation. |
| Number-input plus/minus controls | Type or adjust a number with the stated unit. | Change a parameter. A new calculation still requires its action button. |
| Streamlit Deploy / main menu | Not needed for judging. | Framework controls, not medical-physics workflows. Do not deploy the app as part of a local functional test. |

Many workflows hide an old result after you change the associated inputs. Press the calculation button again. A page with no current result is not always a crash.

## 6. Menu 1: Patient-file Verification

**Question answered:** “Can the implemented intake checks associate and read this selected case, and what needs review?”

### Every input and action

| Control | Beginner entry | Meaning |
|---|---|---|
| **Create an explicitly synthetic demo case** | Optional button. No text required. | Creates new teaching input files in a fresh runtime session and fills in their directory and pseudonym. It writes new synthetic files; it does not fetch or repair a patient. You do not need this if using `data/demo/01_clean_case`. |
| **Case directory** | `data/demo/01_clean_case` | Folder to inspect recursively. This is independent of simply typing a folder in the sidebar. |
| **Case pseudonym (no patient names or original identifiers)** | `judge-demo-001` | A report label. Use 1–64 letters, digits, underscores or hyphens. It must not be the source PatientID. It neither anonymizes the original files nor selects a treatment course. |
| **Decode image and dose pixels** | Leave checked for the complete demonstration. | Actually checks image/dose pixel payloads as well as metadata. Unchecking skips that evidence and requires review. It does not make a bad case pass. |
| **Verify patient files** | Click. | Reads source objects, hashes files, checks identity/references, supported geometry, contours and pixels, checks that inputs did not change during verification, then writes a report/audit to separate runtime storage. |
| **Continue to DVH and structure review** | Click after the clean case is ready. | Discovers that case’s linked objects and opens the DVH menu. It does not calculate a DVH until you select ROIs and press Compute DVH. Disabled for BLOCKED. |
| **Technical findings, content hashes and scope** | Expand if you want details. | Shows structured JSON: file labels/hashes, series, dose-course associations, findings and limits. This is not a hidden clinical approval panel. |

### First positive test

1. Select Patient-file Verification.
2. Enter `data/demo/01_clean_case` and pseudonym `judge-demo-001`.
3. Keep pixel decoding checked and click Verify patient files.
4. Expect READY_FOR_RESEARCH_ANALYSIS and explicit synthetic/research disclosure.
5. The case has eight DICOM files: five CTs, one dose, one plan and one structure set. Six image/dose objects can be decoded. An INFO completeness finding is expected and does not itself trigger review.
6. Read the human report and follow-up actions before continuing.

### Deliberately failing tests

Change the Case directory to each separate example and rerun:

- `data/demo/02_missing_image`: expect BLOCKED. One explicitly referenced image is absent. Review findings about irregular/declared spacing can accompany it. The correct action is to obtain the intended complete export, not invent an image.
- `data/demo/03_frame_mismatch`: expect BLOCKED for frame association.
- `data/demo/04_invalid_scaling`: expect BLOCKED for invalid physical dose/scaling.
- Clean case with **Decode image and dose pixels** unchecked: expect review because pixel integrity is not established.

The judge should count these expected refusals as intended error handling, not as failed demonstrations of a valid case.

## 7. Menu 2: Dynamic Agent Copilot

**Question answered:** “Can the optional Gemini route request the allowed local tools and report their actual outcomes?”

It is separate from the deterministic Interactive Agent Query menu. This menu can contact Google when a usable key is present. Local case paths belong in the dedicated context fields, not in the hosted task text.

### Every input and output control

| Control | Beginner entry / purpose |
|---|---|
| **Copilot Operational Scope & Physics Guardrails** | Read the explanation of tools and bounds. The panel itself performs no check. |
| **Local case directory (stays local)** | `data/demo/01_clean_case`. This supplies the locally selected folder behind the opaque handle `selected_case`. |
| **De-identified research task** | Offline starter: `Verify intake for selected_case. Stop if blocked or requiring review.` Use no names, personal identifiers, secret keys or file paths. |
| **Independent Gamma inputs (local only)** | Expand only when requesting gamma. Otherwise leave its two paths empty. |
| **Reference dose file** | `data/demo/01_clean_case/synthetic_dose.dcm` for the synthetic gamma demonstration. |
| **Evaluated dose file** | `data/demo/05_gamma_controls/small_controlled_difference.dcm` or the large-difference file. |
| **Array spacing in mm, in array-axis order (both arrays)** | For 3D non-DICOM arrays use comma-separated numbers such as `2,2,2`. **Do not type `[2,2,2]` in this Copilot box.** DICOM uses its own geometry, but the GUI still parses this box, so leave a valid numerical string such as the default `1,1,1`. |
| **Gemini API key (memory only; empty runs local intake)** | Leave absent for a local demonstration without provider calls. If a key already exists in process environment `GEMINI_API_KEY`, clearing the visible box does not necessarily force offline mode: the runner can use that environment value. Confirm the displayed execution mode. Do not put a key in the task text, a report or Git. |
| **Model** | Code-listed choices are `gemini-3.8-flash`, `gemini-3.1-pro-preview`, `gemini-2.5-flash`. These are literal configured provider identifiers, not proof they are all available to the user’s account. An organizer should supply a verified model/key configuration for live judging. Model choice does not change the mathematical tool definitions. |
| **Run Copilot** | Starts the controlled route. Requires nonempty task text. Live execution is bounded to six rounds and twelve calls, with explicit provider failures. |
| **Research Triage** | Read the overall conservative disposition as explained in Section 4. |
| **Executed Tool Calls** | Number of actual recorded local tool calls, not hidden reasoning steps. |
| **Execution mode** | LIVE or OFFLINE. This is essential when deciding whether you tested a hosted agent. |
| **View Agent Tool-Calling Trajectory & Safety Interceptions** | Shows each allowlisted tool name, recorded action, validated arguments and observation. It does not export private chain-of-thought. |
| **Deterministic Research Assessment** | Application-composed report from tool observations. Do not infer numerical success from conversational prose alone. |
| **Generated Session Artifacts / View File** | Actual local output plots/reports/templates where available. Missing artifacts are reported; rerun with the correct configuration. |
| **Download Research Assessment (Markdown)** | Downloads the displayed report. |
| **Download Tool Actions (JSON)** | Downloads the recorded structured tool actions/observations. |

### Tasks you can type

**Without a key and without an environment key:**

```text
Verify intake for selected_case. Stop if blocked or requiring review.
```

The expected activity is **local intake only**, with OFFLINE mode. A clean intake can succeed while overall Research Triage remains FLAGGED_FOR_REVIEW. This is not a failed DVH calculation because no DVH was requested/performed.

**With an independently configured live provider:**

```text
Verify intake for selected_case, then calculate DVH metrics for Brainstem and PTV if intake is ready.
```

Both ROI names must be explicitly in the request and exist in the case. Expect an intake observation before a DVH observation. Unknown names or ambiguous courses must not be silently substituted. Without a key, a DVH request is not fulfilled by the intake-only route and can stop with `REQUESTED_ANALYSIS_NOT_PERFORMED`.

For gamma, fill both dedicated paths and type:

```text
Perform gamma comparison using 3pct_2mm on the locally supplied independent dose pair.
```

For a simulation template, with a live provider configured:

```text
Generate a 150 MeV proton TOPAS deck with 100000 histories.
```

Do not confuse `GENERATED` with an executed transport simulation. Generic greetings or broad medical questions may produce no tool evidence. `API_KEY_OR_LOCAL_CASE_REQUIRED`, provider errors or invalid-model errors are configuration failures, not measurements proving a case is safe or unsafe.

## 8. Menu 3: DICOM-RT & DVH Analyzer

**Question answered:** “What dose statistics does each selected outlined region receive in this supplied dose grid?”

### Inputs, options and Calculate button

| Control | What to do |
|---|---|
| **Workflow Instructions & Dosimetric Standards** | Read the workflow explanation. |
| **Source files and provenance** | Inspect the selected dose, plan and structure paths. These come from sidebar discovery or the intake handoff, not from guessing filenames. |
| **Structure naming review (AAPM TG-263 Standards)** | Shows source names, standardized names and naming status. It checks nomenclature, not anatomy. |
| **Official Primary** | Count of names matching the pinned official primary vocabulary. |
| **Pattern Checked** | Count matching a supported target/derived naming pattern. This is a more limited naming check than official-primary membership. |
| **Review Required** | Names without the supported automatic identification needed for this scope. A judge with no anatomy knowledge should not certify a mapping. |
| **Exact source ROI names** | Choose **Brainstem** and **PTV** in the clean teaching case. Brainstem is normally the default if present. Select both to show two curves. Do not type SpinalCord if it is not one of the actual demo options. |
| **Human-reviewed legacy ROI mapping (JSON)** | For this clean demo use `{}`. That means “no additional mapping.” |
| **Suggested aliases for anatomical review** | Appears for certain legacy names. A suggestion is not proof of anatomical equivalence. |
| **I confirmed the suggested aliases against the anatomy** | Appears only when suggestions exist. Leave unchecked unless a qualified reviewer actually confirmed them. |
| **Compute DVH** | Reads the selected objects, validates supported identity/geometry/dose, samples supported contour volumes, computes metrics and generates a plot and readable report. It does not optimize a treatment, run a beam model or generate a new patient dose. |
| **TG-263 naming details** | Post-calculation naming information for inspection. |

If no dataset is selected, scan `data/demo/01_clean_case` in the sidebar first, or use the intake handoff. An empty ROI selection disables Compute DVH.

### Mapping syntax, only after anatomical review

```json
{"Cord":"SpinalCord"}
```

This maps an exact source label to a standardized label. Both keys and values are quoted strings. This example is not needed for the clean teaching dataset. `{Cord:SpinalCord}` and Python dictionaries with single quotes are not valid JSON. Renaming a label does not correct its contour geometry.

### Reading the curve and numbers

| Output | Plain-language interpretation |
|---|---|
| Volume (cc) | Sampled region volume in cubic centimetres. |
| Mean dose (Gy) | Average sampled dose in that region. |
| Voxel Dmax (Gy) | Highest sampled voxel dose. It is not automatically an anatomical maximum or a small-volume endpoint such as D0.03cc. |
| D95% (Gy) | Dose covering at least approximately 95% of the sampled region, implemented as a fifth percentile. It is a dose, not 95% of prescription. |
| D50% (Gy) | Median sampled dose. |
| D2% (Gy) | Near-high-dose statistic: approximately the dose received by the hottest 2% of the sampled region. |
| V50Gy (%) | Percentage of sampled region receiving at least **50 Gy**. It is not the percentage receiving 50% of an inferred prescription. |
| V50Gy (cc) | The same threshold volume in cubic centimetres. |
| Curve x-axis | Dose in Gy. |
| Curve y-axis | Percentage of region receiving at least that dose. A cumulative curve should not increase as dose increases. |
| DVH curve step | Exported dose-threshold spacing, normally starting at 0.01 Gy and enlarged to respect a bin budget. It is not a clinical uncertainty margin. |
| Found / Not evaluated | Whether that ROI had a supported calculation. A missing or unsupported ROI must not be interpreted as zero dose. |

The teaching Brainstem curve is below the PTV curve in dose because the supplied artificial regions occupy different parts of a manufactured dose gradient. This is an illustration, not a demonstrated correct treatment. The DVH alone cannot tell you whether a dose is appropriate without prescription, fractionation and reviewed organ/target constraints. It also cannot locate a hot or cold spot in 3D.

The sampler supports a restricted axial geometry. Unsupported orientations, explicit source-plane/slab/offset encodings, irregular contour planes, invalid topology and partial dose coverage can be refused rather than guessed. A successful selected ROI does not clear whole-case review findings.

## 9. Menu 4: Gamma Index QA (AAPM TG-218)

**Question answered:** “How closely do two supplied dose distributions agree under chosen dose-and-distance criteria?”

### Every field

| Control | Clean synthetic test | Meaning |
|---|---|---|
| **AAPM TG-218 Criteria & User Guide** | Expand to see the stated research bands. | Explains supported policies; it is not a commissioning certificate. |
| **Reference RTDOSE/NPY path** | `data/demo/01_clean_case/synthetic_dose.dcm` | Comparison baseline. It must have independently justified provenance for actual QA. |
| **Independent evaluated dose path** | `data/demo/05_gamma_controls/small_controlled_difference.dcm` | Distribution being compared with the reference. |
| **Dose Tolerance (%)** | `3` | Permitted dose difference scale, relative to the reference maximum in this global implementation. It does **not** mean a 3% acceptable error in every clinical setting. |
| **Distance Tolerance (mm)** | `2` | Spatial distance scale in the comparison. Smaller is stricter. |
| **Low-dose Cutoff (%)** | `10` | Only reference voxels at/above 10% of the reference maximum enter this comparison. It is a cutoff, not a prescription or uncertainty. |
| **Non-DICOM spacing in mm, per array axis (JSON; dose must be Gy)** | `[]` for these DICOM files. | DICOM supplies its geometry. For 3D NPY files use `[dz,dy,dx]`, for example `[2,2,2]`. For 2D arrays use two values. This box uses JSON, unlike the Copilot’s comma-only box. Both arrays receive this same UI spacing setting. |
| **Evaluate Gamma Index** | Click. | Loads the two arrays/objects, validates applicable inputs and computes discrete global gamma, without running model inference or transport. |

### Expected test sequence

1. Use the small controlled difference and defaults **3, 2, 10, []**. Expect **100% passing** and “Candidate threshold met.”
2. Change only the evaluated path to `data/demo/05_gamma_controls/large_controlled_difference.dcm`. Click again. Expect **0% passing** and “Below action threshold.”
3. Put the exact same file into both path boxes and click. Expect refusal for self-comparison. Separate filenames alone would still not prove scientific independence.

The 100% and 0% values are specific constructed controls. They are not evidence of an independently validated predictive model.

### Reading the result

- **Passing rate:** eligible reference voxels whose gamma is at most 1, divided by eligible reference voxels. 100% means agreement under the selected numerical settings, not universal dose correctness.
- **Eligible / total reference voxels:** shows what the low-dose cutoff excluded.
- **Mean / maximum gamma:** dimensionless comparison values; lower generally indicates better numerical agreement under the same settings. Different criteria are not directly interchangeable.
- For exactly **3%/2 mm/10%**, the human report uses candidate ≥95%, review ≥90% and <95%, below 90% fails.
- Exactly **3%/3 mm/10%** uses the same bands as a custom policy.
- Exactly **2%/2 mm/10%** uses candidate ≥90%, review ≥85% and <90%.
- Other combinations can calculate, but the report says no acceptance policy is assigned to that combination. Changing cutoff away from 10% also leaves the predefined policy combinations.

This standalone menu returns a gamma report, not a full-model APPROVED/REJECTED decision. The method is discrete global comparison without interpolation or a measurement-uncertainty model. NPY/array inputs assume Gy and zero origin with supplied spacing; do not use them for arbitrary unregistered patient arrays. DICOM input checks include supported geometry and matching patient/issuer/frame and summation labels. No implicit rescaling between fraction and course dose is performed.

## 10. Menu 5: TOPAS Monte Carlo Deck Generator

**Question answered:** “Can the software prepare a parameter template for an external particle simulation?”

| Control | Starter selection | Meaning |
|---|---|---|
| **TOPAS Deck Instructions & Physical Bounds** | Read if needed. | Describes template scope. |
| **Particle Type** | `proton` | Simulated particle species. Other choices: `e-` = electron, `gamma` = photon, `neutron` = neutron. Choosing a particle does not select or validate a clinical beam model. |
| **Beam Energy (MeV)** | `150` | Per-primary kinetic energy for the template. Supported application range is 0.01–250 MeV, inclusive. |
| **Geometry** | `water_phantom` | Artificial 30×30×30 cm water box. `slab_heterogeneity` adds layers of water, cortical-bone material, lung material and water. This is not a patient CT simulation. |
| **Number of Histories** | `100000` | Number of primary particle histories the external simulator would run. Must be a positive integer. It is not the number of patients or fractions. |
| **Generate TOPAS Deck** | Click. | Builds a validated-parameter text template and displays a handoff report. It does not run TOPAS or produce a simulated dose distribution. |
| **Download TOPAS parameter file** | Click if you want the actual text. | Downloads `topas_research.txt`. This differs from downloading the explanatory report. |
| **Inspect parameter file** | Expand. | Shows the actual generated parameters, including geometry, beam, physics modules and scorer configuration. |

The template uses random seed 42, one thread and DoseToMedium scoring. These defaults do not establish reproducibility of every external runtime or equivalence to another dosimetry quantity.

**Positive test:** proton, 150 MeV, water phantom, 100000 histories should generate a file.

**Negative test:** change energy to `350` and generate again. Expect an explicit energy-range error. Do not count the refusal as a software defect. This does not mean 350 MeV is universally impossible physics; it is outside this application’s supported range.

Larger histories can affect statistical precision and runtime **when TOPAS actually runs later**. Increasing the number in this generator does not perform that computation. A TOPAS installation, physics data and independent beam/transport validation are separate requirements.

## 11. Menu 6: Radiobiology (TCP / NTCP)

**Question answered:** “What probability does this mathematical model estimate for the supplied dose-volume description and parameters?”

This is the easiest advanced mathematical menu to test without any patient data. Do not invent patient-specific biological constants or interpret a demonstration estimate as a person’s outcome.

| Control | Meaning and entry |
|---|---|
| **Radiobiology Modeling Guidelines & Parameters** | Describes the two implemented research models. |
| **Model Type** | `LKB` estimates NTCP. `Poisson_LQ` estimates TCP using the implemented EUD form. Despite the label, this implementation applies no explicit fractionation/LQ survival correction. |
| **Analyzed ROI DVH** | Appears if the session already has a computed DVH. Select a region’s curve. It is a convenience source, not an approved biological model for that region. |
| **DVH JSON** | The numerical histogram, with keys `dose_bins_Gy` and `volume_percent`. You can paste the artificial example below. |
| **DVH type** | `cumulative` means remaining volume at/above successive dose thresholds; `differential` means volume assigned to each dose bin. Choose the representation that actually matches the numbers. |
| **Model parameters JSON (endpoint-specific, with literature review required)** | Enter model constants. `{}` is not sufficient for a successful calculation. |
| **Calculate TCP / NTCP** | Validates the supplied histogram/parameters, computes EUD and the requested probability, and displays an explanatory report. It does not derive model parameters, prescribe treatment or validate a clinical endpoint. |

### Copy-and-paste nonclinical arithmetic test

Select **LKB**. Paste this in **DVH JSON**:

```json
{"dose_bins_Gy":[20,40],"volume_percent":[100,0]}
```

Select **differential**. This artificial distribution assigns all volume to the 20 Gy bin and zero to the 40 Gy bin.

Paste this in **Model parameters JSON**:

```json
{"TD50":20,"m":0.2,"n":1}
```

Click Calculate TCP / NTCP. The implemented formula should give EUD 20 Gy and NTCP 0.5, displayed as approximately **50%**. These numbers are deliberately chosen to test the formula’s midpoint. They are not recommended organ parameters.

For the TCP counterpart, keep the same artificial differential histogram, select **Poisson_LQ**, and use:

```json
{"TCD50":20,"gamma50":2,"a":-10}
```

Expect EUD 20 Gy and TCP approximately **50%** under this model. `a` must be negative. The formula accepts `gamma_50` as an alternative spelling through normalization, but `gamma50` is the clearest copyable key.

### Parameters and representation rules

- LKB `TD50`: positive dose parameter, in Gy, for the modeled 50% endpoint. `m`: positive slope parameter. `n`: positive volume-effect parameter.
- TCP `TCD50`: positive dose parameter in Gy. `gamma50`: positive slope parameter. Optional `a`: negative EUD exponent, default −10.
- Differential percentages must sum to 100. Cumulative volumes must start at 100% at 0 Gy, be non-increasing, and end at zero volume. Dose bins must be increasing and nonnegative.
- Cumulative input uses bin midpoints during conversion to differential weights. Do not expect different histogram discretizations to give identical results.
- The DVH Type control does not automatically rewrite the numbers when you switch it. A curve loaded from the DVH Analyzer is cumulative; leave it cumulative unless you explicitly replace its data with a differential histogram.
- Leave `alpha_beta` out of this demonstration. The current code does not apply a fractionation correction, even if such a parameter appears in a generic description.
- Negative or nonfinite parameters and malformed histograms should trigger errors. A result bounded to 0–100% does not establish clinical calibration or a confidence interval.

## 12. Menu 7: Model Evaluation & Triage

**Question answered:** “Does a supplied model prediction, on a declared common grid, satisfy this research policy relative to a supplied reference?”

### What this menu does not do

It does not train an AI, execute weights, generate a missing prediction, register two image sets, create masks automatically or convert the DICOM teaching case into a complete model-evaluation package. The weights file is read for hashing only. The reference, prediction, masks and optional uncertainty must already exist as numerical `.npy` files.

**The bundled demonstration DICOM files alone cannot fill this menu.** A team member must separately prepare and validate an array-based engineering package. No ready-to-run model-inference package is implied by this guide. Do not rename a `.dcm` file to `.npy` or manufacture “qualification” files just to obtain APPROVED.

### Every visible control

| Control | Meaning |
|---|---|
| **Evaluation Manifest JSON Guide: Required Fields & Schema** | A summary of inputs. Use the actual schema described below where abbreviated UI text is ambiguous. |
| **Clinical QA Decision Policy & Tolerance Matrix** | Shows the implemented research thresholds. The label does not establish clinical commissioning. |
| **Evaluation manifest JSON** | Paste the full JSON **contents**, not the path to a JSON file. Default `{}` intentionally does not contain enough information. |
| **Evaluate supplied model output** | Parses the strict request, reads/hashes supplied files, checks arrays and declared registration, computes eligible metrics and rules, then writes a decision/report/audit if successful. |
| **Research triage** | The overall APPROVED / FLAGGED_FOR_REVIEW / REJECTED result for the supplied case. |
| **Evaluation Provenance & Audit Payload** | Shows observed metrics, hashes, policy and decision information. It is not independent certification of the evidence files. |
| Result plots | Can include model-minus-reference dose difference, uncertainty SD heatmap and overlaid DVHs. Hard invalidity can prevent these outputs. No plot must be interpreted as zero error if calculation was skipped. |
| Signed-review caption | There is no signed-review form in this menu. Signing is an advanced REST workflow with operator-registered keys. |

**Beginner negative test:** leave `{}` in the manifest box and click Evaluate supplied model output. Expect a missing-field/schema error and no successful model assessment. This tests input-contract validation, not whether a model failed physics.

### Required manifest fields

| Field | Type / what a prepared package must supply |
|---|---|
| `model_name` | A nonidentifying name using 1–64 letters/digits/underscore/hyphen, e.g. `demo-dose-model`. |
| `dataset_id` | A similarly restricted case label, e.g. `synthetic-case-001`. |
| `model_weights_path` | Existing weights/provenance file to hash. The evaluator does not load its ML architecture or run inference. |
| `input_paths` | Nonempty list of actual input **file paths**, not a directory path. Supply every intended source file; the operator is responsible for inventory completeness. |
| `reference_path` | Existing numerical 3D NPY reference dose in Gy. |
| `prediction_path` | Existing numerical 3D NPY predicted dose in Gy. |
| `image_grid` | Declared grid for the common image/mask space. |
| `reference_grid` | Declared grid for the reference dose. |
| `prediction_grid` | Declared grid for the predicted dose. |
| `prescription_gy` | Positive reviewed prescription value used for normalization. A real case requires its actual protocol, not a guessed demonstration value. |
| `target_mask_path` | Nonempty binary target NPY mask with exactly matching shape. |
| `oar_mask_paths` | Nonempty map from canonical TG-263 OAR name to a nonempty binary NPY mask. |
| `oar_limits_gy` | A positive finite dose limit for every named OAR, with exactly the same keys as the masks. Limits require a reviewed clinical context for meaningful interpretation. |

Each grid object contains:

| Grid field | Meaning |
|---|---|
| `shape` | Three dimensions in array order `[Z,Y,X]`, e.g. `[3,3,3]` for an engineering fixture. |
| `spacing_mm` | Positive voxel spacings in corresponding array order `[dz,dy,dx]`. |
| `origin_mm` | The common declared origin in the contract’s coordinate convention. It must match the prepared arrays; do not blindly paste DICOM x/y/z metadata into another convention. |
| `frame_id` | Nonempty identifier for the shared declared frame. Matching strings alone do not establish anatomical registration. |
| `direction` | Optional nine-number row-major orthonormal direction matrix; defaults to the identity matrix. Use the verified prepared geometry. |
| `dose_units` | Optional literal `Gy`, the only supported unit here. |

All three complete grid declarations must agree under this policy. No implicit registration/resampling is performed. Binary masks contain only 0 or 1, have matching shape and at least one selected voxel.

### Optional request fields

| Field | Meaning / effect |
|---|---|
| `model_kind` | `dose_predictor` by default. `monte_carlo` requires appropriate energy/density evidence. `auto_segmentation` cannot receive approval from this dose-only policy. |
| `uncertainty_std_path` | Existing nonnegative standard-deviation map **in Gy**, not variance in Gy². Missing map requires review. |
| `confidence` | Externally calibrated confidence between 0 and 1. Missing requires review; below configured minimum rejects. It is not produced by the evaluator. |
| `ood_score` | Externally derived score from 0 to 1. Missing/excess score requires review. |
| `ood_flags` | List drawn from `metal_artifact`, `post_surgical`, `pediatric`, `unseen_geometry`. Flags require review. The app does not automatically detect these anatomies from CT. |
| `qualification_evidence_path` | Existing qualification record to hash. Presence and a hash do not establish scientific validity. |
| `uncertainty_calibration_path` | Existing uncertainty-calibration record to hash. |
| `ood_calibration_path` | Existing OOD-calibration record to hash. |
| `inference_seed` | Declared external inference seed. Default policy expects 42. This does not run inference or guarantee deterministic GPU behavior. |
| `mass_density_path` | Existing positive density NPY array in g/cm³. This is mass density, not electron density. Required evidence for the Monte Carlo route. |
| `energy_mev` | Optional finite numeric energy, excluding booleans, checked against the supported 0.01–250 MeV range. |
| `fluence_per_mm2` | Optional particle fluence. Negative values reject. A meaningful upper-limit check needs a configured limit. |
| `probabilities` | Dictionary of externally supplied TCP/NTCP-like values checked against [0,1]. These are not automatically computed by this menu. |
| `depth_dose_path` | Optional NPY with two columns `[depth_mm,dose_Gy]`. |
| `homogeneous_photon_depth_dose` | Whether the specific post-build-up monotonicity check is applicable. Do not set this for arbitrary dose profiles or proton Bragg peaks. |
| `buildup_end_mm` | Explicit boundary for that depth-dose check. |
| `depth_dose_tolerance_gy` | Explicit nonnegative permitted increase for that check, default 0. Never enlarge it merely to pass. |
| `policy` | Optional object overriding the configurable policy fields below. It does not expose arbitrary gamma/DVH/OAR acceptance rules. |

Unknown JSON fields are refused. JSON keys are case-sensitive. Enter each key once in an actual JSON object. Use the strict `EvaluationRequest` schema rather than inferring a contract from an abbreviated UI example.

### Exact configurable policy defaults

| Policy field | Default | Meaning |
|---|---:|---|
| `version` | `osi-research-1` | Supported policy identifier. |
| `seed` | 42 | Expected declared inference seed. |
| `max_uncertainty_gy` | 2 | Maximum SD must be below this value to pass. |
| `gradient_gy_per_mm` | 1 | Steep-gradient threshold for the uncertainty/OAR overlap check. |
| `critical_margin_mm` | 3 | Distance around OARs considered in that overlap check. |
| `min_confidence` | 0.95 | Minimum supplied calibrated confidence. |
| `max_ood_score` | 0.1 | Maximum supplied OOD score. |
| `mass_density_limit_g_cm3` | 3 | Application density limit. It may exclude valid metals; it is not a universal physical limit. |
| `max_fluence_per_mm2` | null | No upper fluence limit is configured by default. If fluence is supplied without an applicable limit, review remains. |
| `max_voxels` | 1,000,000 | Per-request upper bound for this evaluator; schema permits a lower value, not a larger value. |

Thresholds must be established independently for intended scientific use. A novice judge should keep defaults and inspect outcomes instead of tuning them to obtain a pass.

### Model-triage numerical bands

| Metric | Candidate/pass | Review | Reject |
|---|---|---|---|
| Global 3% / 3 mm gamma | ≥95% | ≥90%, <95% | <90% |
| Global 2% / 2 mm gamma | ≥90% | ≥85%, <90% | <85% |
| Global 3% / 2 mm gamma | ≥95% | ≥90%, <95% | <90% |
| Target D95 / prescription | ≥95% | ≥93%, <95% | <93% |
| MAE / prescription | <1.5% | 1.5–3%, inclusive | >3% |
| OAR voxel Dmax / supplied limit | <98% | 98–100%, inclusive | >100% |

MAE is the mean absolute difference over the complete common dose grid. The OAR limit is supplied by the operator, not inferred. Physical integrity, confidence, uncertainty, OOD and evidence rules are additional requirements beyond these rows.

### Template for understanding the contract, not a ready-to-run fixture

The following paths are **placeholders**. Do not paste this and expect a successful run until a qualified operator supplies every actual referenced file and verifies its geometry. The 40/50 Gy values here are artificial schema examples, not patient recommendations.

```json
{
  "model_name":"demo-dose-model",
  "dataset_id":"synthetic-case-001",
  "model_kind":"dose_predictor",
  "model_weights_path":"/judge-prepared/weights.bin",
  "input_paths":["/judge-prepared/source.dcm"],
  "reference_path":"/judge-prepared/reference.npy",
  "prediction_path":"/judge-prepared/prediction.npy",
  "image_grid":{"shape":[3,3,3],"spacing_mm":[2,2,2],"origin_mm":[0,0,0],"frame_id":"synthetic-frame"},
  "reference_grid":{"shape":[3,3,3],"spacing_mm":[2,2,2],"origin_mm":[0,0,0],"frame_id":"synthetic-frame"},
  "prediction_grid":{"shape":[3,3,3],"spacing_mm":[2,2,2],"origin_mm":[0,0,0],"frame_id":"synthetic-frame"},
  "prescription_gy":40,
  "target_mask_path":"/judge-prepared/target.npy",
  "oar_mask_paths":{"Brainstem":"/judge-prepared/brainstem.npy"},
  "oar_limits_gy":{"Brainstem":50}
}
```

Even after replacing paths, this minimal manifest lacks uncertainty, OOD, calibration and inference-seed evidence, so physically valid calculations would still require review. Do not add fake evidence simply to eliminate that status.

## 13. Menu 8: Interactive Agent Query

**Question answered:** “Can a deterministic natural-language router dispatch a supported explicit request?”

This is **not the Gemini Copilot** and needs no Gemini key. It is a limited intent router, not a general-purpose medical chatbot. It does not execute Python pasted into the Task box.

| Control | Meaning / example |
|---|---|
| **User Guide & Agent Instructions** | Read the supported task scope. |
| **Task** | For a selected clean dataset: `Calculate DVH metrics for Brainstem and PTV`. |
| Shared DVH controls | When the task contains DVH/dose-volume/RTSTRUCT/RTDOSE terms, it displays the same dataset, ROI-selection and mapping controls described in Section 8. The **selected ROI control actually supplies the ROI list**; naming a region in prose does not by itself change that selection. |
| **Execute Task** | Routes the recognized intent to the supported tool or returns an explanation of missing context. |
| **TG-263 Structure Mapping Details** | Naming information on a returned DVH result. |
| **Technical Tool Record** | Underlying result data. It is not a clinician’s signed decision. |

### Reliable examples

For DVH, scan/select the clean case, select Brainstem and PTV in its ROI control, leave mapping `{}`, type:

```text
Calculate DVH metrics for Brainstem and PTV
```

For a TOPAS template:

```text
Generate 150 MeV proton TOPAS deck in water phantom
```

This router uses a 30 cm water phantom and 100000 histories for this route. It does not offer all dedicated-generator controls, and it does not honor every parameter expressed in prose. Use the TOPAS menu when testing geometry/history options. Explicit particle/energy input is preferable to relying on router defaults.

A request such as `Calculate gamma QA` returns instructions to use the dedicated gamma tool because this text route has no independent dose pair supplied. Radiobiology and model-assessment requests likewise need context not provided by this GUI’s basic Task box; use their dedicated menus. A generic greeting or unsupported instruction can return failure/explanation rather than a fabricated result.

The internal class has an external-client stub, but that is not a functional general hosted-agent mode in this menu. The implemented hosted prototype is the separate Dynamic Agent Copilot.

## 14. Menu 9: Stateful Python REPL Sandbox

**Question answered:** “Can a trusted operator run small Python calculations and capture plots in a persistent session?”

Despite the menu name, the interface explicitly warns that this is **unrestricted local Python, not a security sandbox**. It is optional for a novice judge. Do not paste code from documents, patient metadata, websites or untrusted instructions. Post-execution dose checks cannot undo arbitrary filesystem or network actions.

| Control | Meaning |
|---|---|
| **REPL Sandbox Instructions & Visualization Artifacts** | Explains persistent variables and captured figures. |
| **Python code** | Actual executable Python. It is not a natural-language prompt. |
| **I reviewed and trust this code** | User acknowledgment enabling execution, not an automatic security review. |
| **Run Code** | Executes in the persistent namespace, captures output/figures and checks certain dose arrays afterward. |
| Execution successful / error text | Execution/check outcome. This is not research-model approval or a treatment result. |

A benign teaching example to paste after personally reviewing it:

```python
import numpy as np
import matplotlib.pyplot as plt

demo_dose = np.array([[1.0, 2.0], [3.0, 4.0]])
print('Synthetic mean dose:', float(demo_dose.mean()), 'Gy')
plt.figure()
plt.plot([0, 1, 2, 3], [1, 2, 3, 4])
plt.xlabel('Artificial sample number')
plt.ylabel('Artificial dose (Gy)')
plt.title('Synthetic teaching calculation')
plt.show()
```

Expected output includes mean 2.5 Gy and a captured plot. These are artificial numbers.

State persists: a later execution can use earlier variables. There is no reset button in this workflow. The backend checks NumPy arrays whose names contain `dose`, and returned NumPy arrays; it does not validate every variable or every side effect. The GUI mainly displays success/error, stdout and images, so use `print(...)` to make a numerical result visible.

An optional negative-dose control can set `demo_dose` to an array containing −1. It should fail the relevant post-execution guard. That invalid variable remains in the persistent namespace; replace it with a valid array or remove that synthetic variable before later tests. Do not infer that an error rolled back earlier code actions.

## 15. Downloads and common result panels

These controls recur in intake, DVH, gamma, TOPAS, radiobiology and model evaluation when a result exists:

| Control / panel | Meaning |
|---|---|
| Human-readable summary | A brief description of what ran and what the result supports. |
| Measure / Result / Interpretation table | Measurements and their units, plus qualifications. `Not evaluated` is not zero. |
| Follow-up actions | What an operator/reviewer should resolve next. A novice should read these before assigning a verdict to the demonstration. |
| Scope and limitations text | Unsupported assumptions and remaining scientific/deployment work. |
| **Download assessment report (Markdown)** | A readable text report, useful for documenting the judge’s test. |
| **Download metrics (CSV)** | A table for a spreadsheet. It is not raw image data. |
| **Download technical results (JSON)** | Structured output for audit/integration. It is a result object, not automatically a reusable evaluation input manifest. |
| Session ID / artifact name | Identifies stored outputs. Different sessions can have different IDs, timestamps and file names even for identical numerical inputs. |

Downloads and generated calculations create derived files when a user runs them. Input originals are meant to remain unchanged. Changing fields can invalidate the displayed cached result. No universal Calculate button runs all workflows together.

## 16. A 15–20 minute beginner’s judging route

| Order | Activity | What a successful product demonstration means |
|---|---|---|
| 1 | Verify clean teaching case with pixels | Ready state, synthetic label and readable report, no invented patient treatment approval. |
| 2 | Verify missing-image case | Blocked state, specific missing-reference finding, meaningful required export action. |
| 3 | Restore clean case and calculate Brainstem/PTV DVHs | Two curves, explicit Gy/percent/cc metrics, readable limitations. |
| 4 | Run small and large synthetic gamma controls | 100% and 0% at 3%/2 mm/10%, with correct interpretation. |
| 5 | Generate 150 MeV proton water-phantom TOPAS file | Actual parameter text and explicit “simulation not run” scope. |
| 6 | Try 350 MeV in the generator | Supported-range error, with no silently changed energy. |
| 7 | Run the artificial 20 Gy differential LKB example | Model midpoint approximately 50%, clearly conditional/artificial. |
| 8 | Inspect Copilot in OFFLINE mode, if no environment credential exists | Real local intake evidence, explicit mode and conservative review disposition. Do not label it live Gemini. |
| 9 | Submit `{}` to Model Evaluation | Schema refusal rather than a fabricated result. Full successful assessment requires a separately prepared array/evidence package. |
| 10 | Optional deterministic query or reviewed REPL example | Correct supported routing or simple arithmetic/plot, not a general clinical AI claim. |

Record expected refusals separately from unexpected execution errors. Do not give a successful error-detection feature a failure score merely because the word BLOCKED is red. Conversely, a successful calculation should not be awarded clinical accuracy it has not established.

## 17. Troubleshooting without modifying code

| Symptom | Check / interpretation |
|---|---|
| “Scan and select a dataset” | Enter the clean-case folder in the sidebar and click Scan folders, or use the intake-to-DVH handoff. |
| No linked course appears | The path may be wrong, the folder may contain no supported RTDOSE/plan/structure chain, or objects may be missing. This scanner searches lowercase `.dcm` files. Intake has broader candidate recognition. |
| Cannot find a file | Use the app server’s filesystem path, not a GitHub URL or a path from another computer. |
| Many duplicate/conflicting objects | Check that you did not select `data/demo/` or mix separate patients/courses. Do not delete originals during judging. |
| Ready case becomes review when pixels are disabled | Expected: metadata alone does not establish pixel integrity. |
| ROI absent / Not evaluated | Select the exact available source name. Unsupported topology, mapping or geometry can also prevent the ROI calculation. |
| Invalid JSON | Use double quotes, exact keys and commas, no comments or trailing commas. `{}` is valid JSON but often lacks required information. |
| Copilot spacing error | Use `2,2,2`, not `[2,2,2]`, in the Copilot spacing field. |
| Gamma spacing error | Use a JSON list such as `[2,2,2]` for 3D NPY. Use `[]` for the supplied DICOM controls. |
| No acceptance policy for gamma | The selected dose/distance/cutoff combination is outside the three predefined report-policy combinations. |
| Copilot flags review despite clean intake | Current runner intentionally never assigns overall APPROVED. Read the successful intake observation and execution mode. |
| Copilot does not calculate requested DVH in OFFLINE mode | Expected: offline execution performs intake only. Use the deterministic DVH menu, or an operator-configured live provider. |
| Provider invalid-model/authentication/quota/network error | A hosted-service configuration/availability issue. It provides no patient/model QA evidence. Do not edit dose data to fix it. |
| Model evaluator requests many paths | It needs a precomputed, registered array package. The clean DICOM example is not that complete package. |
| A valid large dose is blocked | Default direct-dose voxel budget is 2,000,000; model-evaluation default/cap is 1,000,000. A resource refusal is not proof of malformed physical data. Ask the team to explain qualification rather than increasing it during judging. |
| TOPAS file exists but no simulated plot appears | Expected. This generator does not run transport. |
| Radiobiology says parameters missing | Supply the appropriate artificial test constants, or actual reviewed endpoint-specific parameters. Do not infer defaults from a structure’s name. |
| REPL keeps reporting an old negative-dose array | State persists. An earlier invalid `dose` variable can still be inspected on subsequent runs. Replace/remove that artificial variable or start a new session. |
| Port 8501 does not respond on another computer | It refers to that computer’s localhost. Start the app there; the existing local URL is not a public deployment. |

## 18. For a judge starting on a fresh computer

These are **instructions only**, not commands executed while producing this guide. Installation creates a separate checkout/environment. Use the existing app if it is already provided.

```bash
git clone https://github.com/MYT2004/OpenRad-Agent.git
cd OpenRad-Agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[app,api,test]'
OPENRAD_DATA_ROOTS='["data/demo/01_clean_case"]' \
STORAGE_DIR='./storage/sessions' \
python -m streamlit run frontend/app.py \
  --server.address 127.0.0.1 --server.port 8501
```

The shell activation example is for macOS/Linux. Use Python 3.11 or 3.13 to match the configured CI matrix; `pyproject.toml` requires at least 3.11. Install from the repository root so the local package is available. `app.py` is also a launcher forwarding to `frontend/app.py`.

On Windows PowerShell, after cloning and entering the repository, the equivalent setup avoids needing shell activation:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install '.[app,api,test]'
$env:OPENRAD_DATA_ROOTS = '["data/demo/01_clean_case"]'
$env:STORAGE_DIR = './storage/sessions'
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Open the URL shown by Streamlit. Keep the server terminal running. A cloud/container copy does not automatically have this machine’s patient folders. Mount/provide authorized inputs separately before using real data.

## 19. How the code maps to the interface

| File | Role |
|---|---|
| `app.py` | Convenience Streamlit launcher. |
| `frontend/app.py` | All nine visible workflows, input fields, result displays and handoffs. |
| `agent_main.py` | Command-line entry point for verification, DVH, evaluation, TOPAS and synthetic case generation. |
| `server.py` | FastAPI endpoints for programmatic access and container deployment. Separate from the Streamlit web page. |
| `src/case_verification.py` | Read-only case intake checks, findings and reports. |
| `src/tools.py` | Canonical DVH/TOPAS-file tool boundaries, analysis projection and output/report hooks. |
| `src/agent_dynamic.py` | Optional Gemini function calling, allowlisted tools, mode/trajectory and conservative disposition. |
| `src/decision.py` | Exact model request schema, configurable policy and status reduction. |
| `src/evaluation.py` | Reads supplied arrays/evidence, computes metrics, applies rules and records decisions. |
| `src/reports.py` | Human-readable summaries, interpretations and downloads. |
| `src/storage.py` | Session/artifact directories and local persistence. |
| `src/governance.py` | Hash-chain and signed-review machinery. |
| `src/privacy.py` | Minimal in-memory analysis copies; not a general DICOM de-identification exporter. |
| `src/readonly.py`, `src/resources.py`, `src/hooks.py` | Output-path protection, resource budgets and numerical boundary checks. |
| `openrad/tools/` | Dose sampling, gamma, biological formulas, dataset discovery and TOPAS template generation. |
| `openrad/validation/` | Physics checks and TG-263 naming. |
| `openrad/core/agent.py` | Deterministic Interactive Agent Query router. |
| `openrad/sandbox/repl.py` | Persistent trusted Python execution. |
| `data/demo/` | Packaged artificial positive/negative examples. |
| `validation/tests/`, `validation/evidence/` | Regression checks and reviewed recorded evidence. |
| `storage/` | Runtime outputs, not source code or a raw input archive. |

### Optional command-line tests

Run only if you intend to create runtime outputs later. The commands are not executed in this guide.

```bash
python agent_main.py verify-case \
  --root data/demo/01_clean_case --case-id judge-demo-001

python agent_main.py dvh \
  --rtdose data/demo/01_clean_case/synthetic_dose.dcm \
  --rtstruct data/demo/01_clean_case/synthetic_struct.dcm \
  --rtplan data/demo/01_clean_case/synthetic_plan.dcm \
  --roi Brainstem --roi PTV

python agent_main.py topas \
  --particle proton --energy-mev 150 --histories 100000
```

CLI return values: intake uses 0 ready, 3 review, 2 blocked/error. Supplied-model evaluation uses 0 candidate, 3 review, 2 rejected/error. A shell exit of 2 must be interpreted with the error/result, not treated as a single universal clinical category.

For programmatic access, `python server.py` starts the API, default port 8080 or `PORT`. `/health` reports service/readiness, not a patient verdict. `/docs` is FastAPI’s generated API explorer. Relevant endpoints include `/api/v1/cases/verify`, `/api/v1/dvh/analyze`, `/api/v1/gamma/evaluate`, `/api/v1/topas/generate`, `/api/v1/radiobio/calculate`, `/api/v1/evaluations` and `/api/v1/agent/run`. The REST agent route is deterministic, not the Dynamic Gemini UI. Signed review uses a separate review endpoint with operator-registered Ed25519 keys. Do not expose this trusted single-operator prototype remotely merely to make a judge’s localhost link accessible.

## 20. What an invigilator should conclude

You can assess whether the interface produces reproducible supported calculations, distinguishes absent/invalid inputs from successful output, supplies useful review actions, retains explicit research limitations, and demonstrates real tool calls rather than fabricated measurements.

You cannot infer from this demonstration that every possible patient export is supported, every AI model is accurate, all medical-physics standards are fully satisfied, all provider models work, the REPL is isolated, or the service is ready for shared clinical use. This is a working research POC with explicit remaining qualification and deployment requirements.

The latest local audit records **377 passing regressions, 28 complete workflow scenarios with no skips, and 1,450 numerical checks**. Its seeded gamma probe used **26.2% less peak traced allocation**, with identical result dictionaries; this is reduced temporary memory, not improved accuracy or a general speedup. Demo DVH outputs and recorded controls across all nine menus also matched the baseline. Agent/REPL creation is now deferred until its workflows need it, without a menu or input-contract change. No extra pip packages were required. See the [efficiency audit](../../validation/evidence/efficiency/2026-10-23/README.md).

Earlier evidence includes 63 executed export-fault controls behaving as expected; one requested local baseline remained unsupported. These are recorded engineering results with revision-specific coverage, not tests rerun while writing this manual or a certification of an error-free system.

To check your installed revision:

```bash
python -m pytest validation/tests -q
python -m validation.benchmarks.efficiency
python -m validation.benchmarks.stress.numerical
python -m pip check
```

A fresh installation without external caches cannot reproduce every external-dataset scenario. The following command deliberately fails its completeness gate if required scenarios are skipped; configure authorized `OPENRAD_DATA_ROOTS` first:

```bash
python -m validation.benchmarks.stress.stress_all_menus --require-complete
```

External data is optional for the bundled synthetic tour. See the [external benchmark instructions](../../validation/benchmarks/slicerrt/README.md) and [dataset attribution and access notes](../DATA_SOURCES.md) before fetching it. Do not expect every valid external DICOM geometry to fit the current supported sampler.

## 21. Corrections to the supplied Antigravity draft

| Draft statement | Correct interpretation in this guide |
|---|---|
| READY and APPROVED both mean all clinical safety tests pass | Intake and model-triage statuses have different scopes; neither authorizes treatment. |
| Review is merely non-critical and not dangerous | Review means unresolved evidence or policy conditions; safety is not established. |
| The system runs Monte Carlo simulations | It generates TOPAS templates; an external runtime and commissioned beam validation are separate. |
| Synthetic case is created in memory | The button writes new artificial DICOM files into fresh runtime storage, without changing originals. |
| DVH uses exact voxel intersections | The implemented sampler uses axial voxel centers, inferred contour slabs and z interpolation. |
| A healthy-organ curve should always fall quickly | Interpretation depends on anatomy, prescription, fractionation and endpoints; the artificial curve is descriptive. |
| Standalone gamma returns an immediate model rejection | It returns comparison metrics and research bands; full-model triage is a separate workflow. |
| 0.01–250 MeV is a universal clinical beam bound | It is this application's supported input range. |
| NTCP below 1% means biologically safe | An unqualified model estimate cannot establish patient safety. |
| A universal spinal-cord cap can be assumed | OAR limits must be externally reviewed and supplied for the intended protocol. |
| No key means the entire agent runs offline | Offline Copilot performs intake only; environment credentials can still enable live mode. |
| 370 is the current total test count | The latest recorded suite passed 377 tests; counts are revision-specific. |
| The system prevents every error or hallucination | Only defined boundaries and executed checks are established; unsupported inputs and deployment limits remain explicit. |

## 22. Data credits

Use [DATA_SOURCES.md](../DATA_SOURCES.md) for the Zenodo distribution, original TCIA HNSCC dataset/publications, pinned SlicerRtData revision and terms caveats. The public `data/demo/` files are created by OpenRad's synthetic generator and should be credited as artificial OpenRad examples, not as HNSCC patients or SlicerRT phantom data. Credit does not imply endorsement or independent clinical validation.

## 23. Fixed-revision source references

All of these links point to the inspected revision, rather than whichever version main may contain in the future.

- Interface and exact controls: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/frontend/app.py
- Dynamic Copilot behavior: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/src/agent_dynamic.py
- Model schema and defaults: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/src/decision.py
- Model evaluation rules: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/src/evaluation.py
- Report interpretation: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/src/reports.py
- Radiobiology implementation: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/openrad/tools/radiobio_tool.py
- Deterministic query router: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/openrad/core/agent.py
- REPL behavior: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/openrad/sandbox/repl.py
- Demo instructions: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/data/demo/README.md
- Decision-policy documentation: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/docs/DECISION_ENGINE.md
- Operating limits: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/docs/HARDENING.md
- Recorded audit: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/validation/evidence/post-merge/2026-10-22/assessment.json

- Latest efficiency audit: https://github.com/MYT2004/OpenRad-Agent/blob/7f09598ecbfd66a53dd74ca8f949eb2dfe046ddb/validation/evidence/efficiency/2026-10-23/README.md
