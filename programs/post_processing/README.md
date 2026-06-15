# Loadsheet Post-Processor
This repository/document outlines the Loadsheet Post-Processor module (`LoadsheetPostProcessor`) within the Onboarding Automation Tools. It acts as an automated data-sanitization pipeline, programmatically cleaning a loaded spreadsheet DataFrame to preemptively resolve common errors that cause the validation sequence to fail.

## Table of Contents
- [Overview](#overview)
  - [Core Features](#core-features)
- [Workflow](#workflow)
  - [Detailed Workflow](#detailed-workflow)

## Overview
The post-processing module is designed to sanitize and harmonize loadsheets before final validation against the predefined ontology. 

### Core Features
* **Invalid SFN Removal**: Automatically checks every `standardFieldName` against the permitted fields for its assigned `typeName` (sourced dynamically from the ontology YAML configurations). Invalid or misspelled field names are safely cleared out.
* **Smart Duplicate Resolution**: If multiple fields within the same asset share an identical `standardFieldName`, the processor uses a hybrid evaluation algorithm to select the best record to keep:
  * **80% Literal Similarity**: A Jaccard token similarity score comparing split components of the text string.
  * **20% Semantic Similarity**: Uses a lightweight NLP transformer model (all-MiniLM-L6-v2) to cross-evaluate the true contextual meaning of metadata fields (name, type, objectName) against the standard field name.
  * *Result*: The row yielding the highest combined score is kept, while the sub-optimal duplicates have their field names cleared.
* **Majority Vote Harmonization**: Specifically targets standardizing fields on high-volume equipment like VAVs, Fans, and FCUs. It clusters data by `generalType` and `objectName`, finds the statistical majority mapping winner, and automatically forces conflicting entries into compliance.
* **Change Audit Log**: Every deletion, substitution, and correction is tracked inside an explicit internal `event_log`.

## Workflow
**General Post-Processing Process**
1. Import the referenced ontology.
2. Load the target loadsheet.
3. Fill out generalTypes, assetNames, and typeNames for equipment in loadsheet. The post_processing function uses this information as inputs. Without it, the post_processing function will be very limited in what it can accomplish. 
4. Run the post-processor to execute data-sanitization (SFN removal, duplicate resolution, harmonization).

### Detailed Workflow

#### Step 1 - Import the ontology
Load the ontology configurations so the processor can source the permitted fields for `typeName` validation.
```
import ontology "...\digitalbuildings\ontology\yaml\resources"
```

#### Step 2 - Import the loadsheet
Import the normalized loadsheet that you want to preemptively clean before validation.
```
import loadsheet '../loadsheet/Loadsheet_ALC_Final.xlsx'
```

#### Step 3 - Execute Post-Processing
Run the post-processing module to execute the automated data-sanitization pipeline. *(Note: Typo from original source corrected to proper command spelling if applicable).*
```
post_processing
```

#### Step 4 - Event Log
The changes made to the loadsheet by the post_processing algorithm are printed out to terminal. Review these changes and make sure no unexpected/erroneous updates have been made. 