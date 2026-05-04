# Copyright 2020 DB Engineering

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#    http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from abel_converter import abel
import os
import representations.representations
from ml_normalize.ml_handler import MLHandler
import ontology.ontology
import loadsheet.loadsheet as load
from loadsheet_validation_checks.loadsheet_validation_checks import LoadsheetValidationChecks
from pretty import PrettyPrint
import base64
from typing import Optional
import pandas as pd
import re
import yaml
import re
import os
import pandas as pd
import yaml
from sentence_transformers import SentenceTransformer, util
from post_processing.abbreviations import ABBREVIATIONS
from post_processing.allowed_tokens import ALLOWED_TOKENS
from post_processing.get_SFN_options import get_SFN_options


def _convert_to_base64(data):
    """
    Convert a data object into a base64 message.
    Used as a codeword to uniquely identify each asset type
    """

    if isinstance(data, set):
        data = list(data)
        data.sort()
        data = tuple(data)
        data = str(data)

    if isinstance(data, list):
        data.sort()
        data = tuple(data)
        data = str(data)

    if isinstance(data, tuple):
        data = str(data)

    encoded_bytes = base64.b64encode(data.encode("utf-8"))
    encoded_str = str(encoded_bytes, "utf-8")

    return encoded_str


def _print_type(type, type_dict):
    """
    prints out a type's assets and fields
    """
    print(f"ASSET GENERAL TYPE: {type}")
    print("--------------------------------------------------------------------------------")
    for field_hash in type_dict.keys():
        assets = type_dict[field_hash][0]
        fields = type_dict[field_hash][1]
        col_width = max(len(field) for field in fields) + 3

        print(f"ASSETS: {assets}\n")
        print("FIELDS")
        print("="*col_width)
        print("\n".join(fields))
        print("\n\n")


class Handler:
    """
    Handler object for handling onboarding workflow.
    Acts as an interface between the CLI and the following libraries:
     - representations: for converting the loadsheet into ontology-usable objects
     - ontology: for asset validation and tMatching
     - loadsheet: for loadsheet and bms imports and exports
                              as well as interaction with the rules engine
    """

    def __init__(self):
        """ Initialize the handler. """
        # Create some flags to mark the status of the processes
        self.ontology_built = False
        self.representations_built = False
        self.loadsheet_built = False
        self.validated = False
        self.matched = False

        # Save some config info so that it can be reused
        self.last_loadsheet_path = ''
        self.last_rule_path = ''
        self.payload_path = None
        self.bc_path = None

    def validate_path(self, path, valid_file_types: list):
        file_type = os.path.splitext(path)[1]

        if not file_type in valid_file_types:
            raise ValueError(f"Path '{path}' is not a valid file type. Allowed types: {', '.join(valid_file_types)}.")
        if not os.path.exists(path):
            raise ValueError(f"Loadsheet path '{path}' is not valid.")
        return True

    def build_ontology(self, ontology_root):
        """
        Try to build the ontology. If theres an error, print it out but don't blow up.
        args:
                - ontology_root: the root folder of the ontology to be imported

        returns: N/A
        """
        try:
            # Adjust the resource directory in the ontology file to import from the desired location.
            # Build the ontology.
            ont = ontology.ontology.Ontology(ontology_root)
            ont.validate_without_errors()
            self.ontology_built = True
            self.ontology = ont
            self.ontology_root = ontology_root
            print(f"[INFO]\tOntology built from '{ontology_root}'.")

        except Exception as e:
            # Raise the exception to the user
            print(f"[WARNING]\tOntology could not build: {e}")

    def import_loadsheet(self, loadsheet_path, has_normalized_fields):
        """
        Attempts to build loadsheet from given filepath
        If errors occur, prints them but doesn't close program

        args:
                - loadsheet_path: path of loadsheet Excel or BMS file
                - has_normalized_fields: flag if passed path is to BMS type (no normalized fields)
                                         or loadsheet (normalized fields)

        returns: N/A
        """
        # Check that the ontology is built first.
        # if not self.ontology_built:    #Ontology necessary for matching, not loadsheet
        # print('[ERROR]\tOntology not built. Build it first.')
        # return

        try:
            if self.validate_path(loadsheet_path, ['.xlsx', '.csv']):
                try:
                    # Import the data into the loadsheet object.
                    self.ls = load.Loadsheet.from_loadsheet(
                        loadsheet_path, has_normalized_fields)
                    print("[INFO]\tLoadsheet Imported")
                    self.loadsheet_built = True
                    self.last_loadsheet_path = loadsheet_path

                except Exception as e:
                    print("[ERROR]\tLoadsheet raised errors: {}".format(e))

        except Exception as e:
            print("[ERROR]\tCould not load: {}".format(e))

    # 01132021: ad-hoc fix for bms import error; needs to be addressed
    # later. Fix done to address demo issues Trevor had earlier
    # in the day. Currently do not have time to refactor =(.
    # basically took the source code directly above and reused w/
    # minimal modification
    def import_bms(self, bms_path, has_normalized_fields):
        """
        Attempts to build loadsheet from given filepath
        If errors occur, prints them but doesn't close program

        args:
                - loadsheet_path: path of loadsheet Excel or BMS file
                - has_normalized_fields: flag if passed path is to BMS type (no normalized fields)
                                         or loadsheet (normalized fields)

        returns: N/A
        """
        # Check that the ontology is built first.
        # if not self.ontology_built:    #Ontology necessary for matching, not loadsheet
        # print('[ERROR]\tOntology not built. Build it first.')
        # return

        try:
            if self.validate_path(bms_path, ['.xlsx', '.csv']):
                try:
                    # Import the data into the loadsheet object.
                    self.ls = load.Loadsheet.from_bms(bms_path)
                    print("[INFO]\tBMS Imported")
                    self.loadsheet_built = True

                except Exception as e:
                    print("[ERROR]\tLoadsheet raised errors: {}".format(e))

        except Exception as e:
            print("[ERROR]\tCould not load: {}".format(e))

    # end by sypks

    def validate_loadsheet(self):
        """ Try to build the loadsheet. If theres an error, print it out but don't blow up. """

        # Check that the ontology is built first.
        if not self.ontology_built:
            print('[ERROR]\tOntology not built. Build it first.')
            return

        try:

            # Validate the loadsheet
            self.ls.validate()

            try:
                # Convert the loadsheet to validation
                print('\n[INFO]\tConverting loadsheet into asset representations.')
                self.reps = representations.representations.Assets()
                self.reps.load_from_data(self.ls._data)
                print('[INFO]\tAsset representations built.')

                # Validate the representations
                print('[INFO]\tValidating assets.')
                self.reps.validate(self.ontology)
                print('[INFO]\tAsset representations validated!')
                self.representations_built = True

                print('[INFO]\tBuilding type representations...')
                self.general_types = self.reps.get_general_types()
                self.types = self.reps.determine_types()
                print(
                    f'[INFO]\tType representations built: {len(self.general_types)} general types, {len(self.types)} unique types')
                self.validated = True

            except Exception as e:
                print(f"[ERROR]\tAsset represtations failed to build: {e}. ")

        except Exception as e:
            print(f"[ERROR]\tLoadsheet raised errors: {e}")

    def apply_rules(self, rules_path):  # REWRITE ME
        """ Run a given rules file over the loadsheet data. """

        try:
            assert self.loadsheet_built, "Loadsheet is not initialized."
            assert os.path.exists(
                rules_path), f"Rule file path '{rules_path}' is not valid."
            print(f"[INFO]\tApplying rules from '{rules_path}'")
            self.ls.apply_rules(rules_path)
            print("[INFO]\tRules applied.")

        except Exception as e:
            print(f"[ERROR]\tRules could not be applied: {e}.")

    def apply_ml_normalization(self):
        """ Run ML normalization on the loadsheet data. """

        # use rules for asset name normalization
        rules_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "resources",
                "rules",
                "google_rules_asset_name.json"
            )
        assert os.path.exists(rules_path), f"Rule file path '{rules_path}' is not valid."
        assert self.loadsheet_built, "Loadsheet is not built."

        try:
            print("[INFO]\tApplying rules for asset names...")
            self.ls.apply_rules(rules_path)
            print("[INFO]\tRules applied.")
        except Exception as e:
            print(f"[ERROR]\tRules could not be applied: {e}.")

        # use ML models to predict required, generalType, and standardFieldName
        ml_handler = MLHandler()
        assert ml_handler.models_loaded, "Loadsheet is not initialized."
        assert ml_handler.tokenizers_loaded, "Representations are not built."
        try:
            print("[INFO]\tApplying ML normalization...")
            input_cols = ['controlProgram', 'Name', 'objectName', 'type']
            
            self.ls._update_header_map(load._ML_PREDICTION_HEADERS) # update hader mapping in Loadsheet object for correct excel export

            std_input_cols = load.Loadsheet._to_std_headers(input_cols)
            
            df = pd.DataFrame.from_records(self.ls._data)
            df = ml_handler.get_predictions(df, std_input_cols)

            print("[INFO]\tML normalization applied.")
        except Exception as e:
            print(f"[ERROR]\tML normalization failed: {e}.")

        # map units using standardFieldName mapping
        try:
            print("[INFO]\tMapping units...")
            mask = df['required']=='YES'
            df.loc[mask, 'units'] = df.loc[mask, 'standardfieldname'].apply(abel.value_mapping.map_units)
            print("[INFO]\tUnits mapped.")
        except Exception as e:
            print(f"[ERROR]\tUnit mapping failed: {e}.")

        self.ls._update_header_map(df.columns)

        df.columns = self.ls._to_std_headers(df.columns)
        self.ls._update_data_from_dataframe(df)


    def export_loadsheet(self, excel_path):
        """
        exports loadshet data to excel file

        args:
                - excel_path: output filepath

        returns: N/A
        """

        try:
            # Check that the loadsheet object is built.
            assert self.loadsheet_built, "Loadsheet is not initialized."

            excel_path = excel_path.replace('\\', '/')
            folderpath = excel_path.replace(excel_path.split('/')[-1], '')
            assert os.path.exists(
                folderpath[:-1]), "Specified Excel path '{}' is not valid.".format(folderpath[:-1])
            print("[INFO]\tExporting to Excel file '{}'".format(excel_path))
            self.ls.export_to_loadsheet(excel_path)
            print("[INFO]\tData exported to Excel file!")

        except Exception as e:
            print('[ERROR]\tExcel file not exported: {}'.format(e))

    def export_abel_spreadsheet(self, excel_path, payload_path, building_config_path: Optional[str] = None, output_path: Optional[str] = None):
        """converts loadsheet to ABEL spreadsheet.

        args:
                - excel_path: path to normalized loadsheet.
                - payload_path: 
        """
        if not payload_path:
            print("[INFO]\tTo convert loadsheet to ABEL, please import payload.")
            return

        if not building_config_path:
            print("[INFO]\tYou did not import a building config. Without it, ABEL sheet data will be incomplete.")
            while True:
                response = input("[INPUT]\tProceed without building config? (Y/N): ").strip()
                if response in ("", "Y", "y"):
                    break
                elif response in ("N", "n"):
                    return

        new_converter = abel.Abel()
        new_converter.import_loadsheet(excel_path)
        new_converter.import_payload(payload_path)
        if building_config_path:
            new_converter.import_building_config(building_config_path)
        new_converter.build()
        if not output_path:
            output_path = excel_path.replace('.xlsx', '_abel.xlsx')
        print(output_path)
        new_converter.dump(output_path)

    def import_excel(self, excel_path):
        """ Import from an Excel file. """
        try:
            # Check that the loadsheet object is built.
            if not self.loadsheet_built:
                self.ls = load.Loadsheet()
                self.loadsheet_built = True

            if excel_path is None and self.last_loadsheet_path != '':
                excel_path = self.last_loadsheet_path
            assert os.path.exists(
                excel_path), "Specified Excel path '{}' is not valid.".format(excel_path)
            self.last_loadsheet_path = excel_path

            print("[INFO]\tImporting from Excel file '{}'".format(excel_path))
            self.ls.from_loadsheet(excel_path)

        except Exception as e:
            print('[ERROR]\tExcel file not imported: {}'.format(e))

    def review_types(self, general_type=None):
        """
        lets user review assets by generaltype

        args:
                - general_type: User can input type and see all assets of that type
                                            Default None

        returns: N/A, prints review data to cmd
        """
        if not self.validated:
            print("[ERROR]\tLoadsheet isn't validated yet... run 'validate' first.")
            return

        '''
        types is a dictionary of dictionary of list pairs
        each instance is of form
        "general_type":{
            "fields_hash":[[list_of asset paths],[list of type fields]],
            "fields_hash":[[list_of asset paths],[list of type fields]]
        }
        '''

        types = {}

        for asset_path in self.reps.assets:
            asset = self.reps.assets[asset_path]
            field_hash = _convert_to_base64(asset.get_fields())
            gT = asset.general_type.lower()
            if gT not in types.keys():
                types[gT] = {}
            if field_hash not in types[gT].keys():
                types[gT][field_hash] = [[], asset.get_fields()]
            types[gT][field_hash][0].append(asset.full_asset_name)

        # now we print
        if general_type is not None:
            if general_type.lower() not in types.keys():
                print(
                    f"[ERROR]\tGeneral Type {general_type} not present in loadsheet. Valid types are {[type for type in types.keys()]}")
                return
            relevant_assets = types[general_type.lower()]
            _print_type(general_type, relevant_assets)
        else:
            for type in types.keys():
                _print_type(type, types[type])

    def review_matches(self):
        """
        reviews matches made once assets have been matched to the ontology
        match types are in {EXACT, CLOSE, INCOMPLETE, NONE}
        See match_types for more information

        args: N/A

        returns: N/A, but prints review to cmd
        """
        if not self.matched:
            return

        matches = {}
        for asset_path in self.reps.assets:
            asset = self.reps.assets[asset_path]
            match = asset.match
            if match.match_type not in matches.keys():
                matches[match.match_type] = []
            matches[match.match_type].append(asset.full_asset_name)

        for match in matches:
            print(f"[{match}]: {matches[match]}")
            print('---------------------------------------------------------------------------------------------------------------------------------------------------\n\n')

    def match_types(self):
        """
        Matches each asset to nearest asset in ontology

        prereqs:
                - loadsheet validation

        args: N/A

        returns: N/A
        """

        if not self.validated:
            print("[ERROR]\tLoadsheet isn't validated yet... run 'validate' first.")
            return
        # Get matches for all types if the general_type specified is None.
        print("[INFO]\tMatching types to ontology...")

        for asset_path in self.reps.assets:
            asset = self.reps.assets[asset_path]
            match = self.ontology.find_best_fit_type(
                asset.get_fields(), 'HVAC', asset.get_general_type())
            asset.add_match(match)

        self.matched = True

    def apply_matches(self):
        """
        returns each asset, one at a time

        args: N/A
        returns: Asset iterable
        """
        for asset_path in self.reps.assets:
            yield self.reps.assets[asset_path]

    def loadsheet_checks(self):
        # Check that the ontology is built first.
        if not self.ontology_built:
            print('[ERROR]\tOntology not imported. Import it first.')
            return
        
         # Check that the loadsheet is imported first.
        if not self.loadsheet_built:
            print('[ERROR]\tLoadsheet not imported. Import it first.')
            return
        
        try:
            df = pd.read_excel(self.last_loadsheet_path)
        except FileNotFoundError:
            print(f"❌ File not found: {self.last_loadsheet_path}")
            return
        except PermissionError:
            print(f"❌ Permission denied: The file '{self.last_loadsheet_path}' is likely open in another program. Please close it and try again.")
            return
        except Exception as e:
            print(f"❌ Unexpected error while reading the file: {e}")
            return

        if not LoadsheetValidationChecks.validate_required_columns(df):
            print("⛔ Stopping validation due to missing columns.")
            return
        else:
            print("✅ Loadsheet contains the correct columns.")
        if not LoadsheetValidationChecks.validate_no_leading_trailing_spaces(df):
            print("⛔ Stopping validation due to leading/trailing spaces.")
            return
        else:
            print("✅ No leading or trailing spaces found in cells.")
        df_cleaned = LoadsheetValidationChecks.validate_required_column(df)
        if df_cleaned is None:
            print("\n⛔ Stopping validation due to invalid required column entry(s)")
            return
        else:
            print("✅ All rows in 'required' column contain 'YES' or 'NO'.")
        if not LoadsheetValidationChecks.validate_required_fields_populated(df_cleaned):
            print("⛔ Stopping validation due to missing required fields in required & not missing rows.")
            return
        else:
            print("✅ All necessary columns populated where required='YES' and isMissing='NO'.")
        if not LoadsheetValidationChecks.validate_missing_required_rows(df_cleaned):
            print("⛔ Stopping validation due to invalid data on missing required rows.")
            return
        else:
            print("✅ All necessary columns populated where required='YES' and isMissing='YES'.")
        if not LoadsheetValidationChecks.validate_object_type_for_command_status(df_cleaned):
            print("⛔ Stopping validation due to objectType mismatches for control/status points.")
            return
        else:
            print("✅ All binary standardFieldNames have binary objectType values.")
        if not LoadsheetValidationChecks.validate_object_type_for_measurement_points(df_cleaned):
            print("⛔ Stopping validation due to objectType mismatches for measurement points.")
            return
        else:
            print("✅ All analog standardFieldNames have analog objectType values.")
        if not LoadsheetValidationChecks.validate_alarm_types(df_cleaned):
            print("⛔ Stopping validation due to invalid alarm type entries.")
            return
        else:
            print("✅ All alarms have the correct BALM type.")
        if not LoadsheetValidationChecks.validate_unique_standard_fields_per_asset(df_cleaned):
            print("⛔ Stopping validation due to duplicate standardFieldNames within assets.")
            return
        else:
            print("✅ No duplicate standardFieldNames within a single asset.")
        if not LoadsheetValidationChecks.validate_unique_typename_per_asset(df_cleaned):
            print("⛔ Stopping validation due to inconsistent typeName assignments per asset.")
            return
        else:
            print("✅ All assetNames have exactly one typeName.")
        self.validated = True
        print("\n🎉 All validations passed!")

    def post_processing(self):

        def load_yaml(path):
            with open(path, "r") as f:
                return yaml.safe_load(f)

        def normalize_text(text):
            if pd.isna(text) or text is None:
                return ""

            text = str(text).lower()
            tokens = text.split()

            prefix_mapping = {
                "sf": "supply_fan",
                "ef": "exhaust_fan",
                "rf": "exhaust_fan",
                "df": "discharge_fan",
                "sfan": "supply_fan",
                "efan": "exhaust_fan",
                "rfan": "exhaust_fan",
                "dfan": "discharge_fan"
            }

            expanded_tokens = []
            for token in tokens:
                match = re.match(r'^(sf|ef|rf|df|sfan|efan|rfan|dfan)(\d+).*$', token)
                if match:
                    prefix, num = match.groups()
                    token = f"{prefix_mapping[prefix]}_{num}"
                expanded_tokens.append(token)

            final_tokens = []
            for token in expanded_tokens:
                if token in ABBREVIATIONS:
                    final_tokens.extend(ABBREVIATIONS[token].split())
                else:
                    final_tokens.append(token)

            split_tokens = []
            for token in final_tokens:
                if "_" in token:
                    split_tokens.extend(token.split("_"))
                else:
                    split_tokens.append(token)

            seen = set()
            deduped = []

            for token in split_tokens:
                is_enum = re.match(r"^\d+[a-z]*$", token)
                if (token in ALLOWED_TOKENS or is_enum) and token not in seen:
                    deduped.append(token)
                    seen.add(token)

            if len(deduped) <= 1:
                return ""

            return "_".join(sorted(deduped))

        def token_similarity(a, b):
            set_a = set(a.split("_"))
            set_b = set(b.split("_"))
            if not set_a or not set_b:
                return 0
            return len(set_a & set_b) / len(set_a | set_b)

        # ----------------------------
        # DUPLICATES
        # ----------------------------
        def resolve_duplicate_sfns(df, event_log):
            print("\nResolving duplicates...")

            model = SentenceTransformer("all-MiniLM-L6-v2")
            removed_count = 0

            df_valid = df[
                df["standardFieldName"].notna() &
                (df["standardFieldName"].astype(str).str.strip() != "") &
                df["assetName"].notna() &
                (df["assetName"].astype(str).str.strip() != "")
            ].copy()

            for asset_name, asset_group in df_valid.groupby("assetName"):

                duplicated_rows = asset_group[
                    asset_group.duplicated(subset=["standardFieldName"], keep=False)
                ]

                if duplicated_rows.empty:
                    continue

                for sfn, dup_group in duplicated_rows.groupby("standardFieldName"):

                    normalized_sfn = normalize_text(sfn) or str(sfn).lower()
                    sfn_embedding = model.encode(normalized_sfn, convert_to_tensor=True)

                    scores = []

                    for idx, row in dup_group.iterrows():

                        row_text = " ".join([
                            str(row.get("name", "")),
                            str(row.get("type", "")),
                            str(row.get("objectName", ""))
                        ])

                        normalized_row = normalize_text(row_text) or row_text.lower()
                        row_embedding = model.encode(normalized_row, convert_to_tensor=True)

                        semantic = util.cos_sim(sfn_embedding, row_embedding).item()
                        literal = token_similarity(normalized_sfn, normalized_row)
                        total = 0.8 * literal + 0.2 * semantic

                        scores.append((idx, total))

                    best_idx = max(scores, key=lambda x: x[1])[0]

                    for idx, _ in scores:
                        if idx != best_idx:
                            original = df.at[idx, "originalStandardFieldName"]
                            asset = df.at[idx, "assetName"]

                            df.at[idx, "standardFieldName"] = ""
                            removed_count += 1

                            event_log.append({
                                "row": idx + 2,
                                "asset": asset,
                                "object": "",
                                "reason": "duplicate",
                                "from": original,
                                "to": ""
                            })

            return removed_count

        # ----------------------------
        # MAJORITY VOTE
        # ----------------------------
        def apply_majority_vote_by_object_name(df, event_log):
            print("\nMajority vote cleanup...")

            target_types = {"VAV", "FAN", "FCU"}
            updated_count = 0

            filtered_df = df[df["generalType"].isin(target_types)].copy()
            grouped = filtered_df.groupby(["generalType", "objectName"])

            for (general_type, object_name), group in grouped:

                if len(group) <= 1:
                    continue

                votes = group["standardFieldName"].apply(
                    lambda x: str(x).strip() if pd.notna(x) and str(x).strip() != "" else "<BLANK>"
                )

                counts = votes.value_counts()
                max_count = counts.max()

                candidates = counts[counts == max_count].index.tolist()

                non_blank = [c for c in candidates if c != "<BLANK>"]
                if non_blank:
                    candidates = non_blank

                winner = None
                for v in votes:
                    if v in candidates:
                        winner = v
                        break

                replacement = "" if winner == "<BLANK>" else winner

                for idx in group.index:

                    current = df.at[idx, "standardFieldName"]
                    current_str = "" if pd.isna(current) else str(current).strip()

                    if current_str == replacement:
                        continue

                    original = df.at[idx, "originalStandardFieldName"]
                    asset = df.at[idx, "assetName"]

                    df.at[idx, "standardFieldName"] = replacement
                    updated_count += 1

                    event_log.append({
                        "row": idx + 2,
                        "asset": asset,
                        "generalType": general_type,
                        "object": object_name,
                        "reason": "majority_vote",
                        "from": current_str,
                        "to": replacement
                    })

            return updated_count

        # Check that the ontology is built first.
        if not self.ontology_built:
            print('[ERROR]\tOntology not imported. Import it first.')
            return
        
         # Check that the loadsheet is imported first.
        if not self.loadsheet_built:
            print('[ERROR]\tLoadsheet not imported. Import it first.')
            return
        
        # ----------------------------
        # LOAD INPUT
        # ----------------------------
        try:
            df = pd.read_excel(self.last_loadsheet_path)
            df["originalStandardFieldName"] = df["standardFieldName"].copy()
        except FileNotFoundError:
            print(f"❌ File not found: {self.last_loadsheet_path}")
            return
        except PermissionError:
            print(f"❌ Permission denied: The file '{self.last_loadsheet_path}' is likely open in another program. Please close it and try again.")
            return
        except Exception as e:
            print(f"❌ Unexpected error while reading the file: {e}")
            return

        event_log = []

        # ----------------------------
        # LOAD YAML
        # ----------------------------
        base = self.ontology_root
        
        general_types_data = load_yaml(
            os.path.join(base, "HVAC", "entity_types", "GENERALTYPES.yaml")
        )

        secondary_general_types_data = load_yaml(
            os.path.join(base, "entity_types", "global.yaml")
        )

        abstract_data = load_yaml(
            os.path.join(base, "HVAC", "entity_types", "ABSTRACT.yaml")
        )

        secondary_abstract_data = load_yaml(
            os.path.join(base, "entity_types", "ABSTRACT.yaml")
        )

        type_cache = {}
        invalid_removed_count = 0

        # ----------------------------
        # INVALID REMOVAL
        # ----------------------------
        print("\nRemoving invalid standardFieldNames...")

        for idx, row in df.iterrows():

            type_name = row["typeName"]
            sfn = row["standardFieldName"]

            if pd.notna(type_name) and str(type_name).strip():

                type_name = str(type_name).strip()

                if type_name not in type_cache:
                    type_cache[type_name] = get_SFN_options(
                        type_name,
                        general_types_data,
                        secondary_general_types_data,
                        abstract_data,
                        secondary_abstract_data
                    )

                valid_sfns = type_cache[type_name]

                if pd.notna(sfn) and str(sfn).strip():

                    sfn = str(sfn).strip()

                    if sfn not in valid_sfns:
                        original = df.at[idx, "originalStandardFieldName"]
                        asset = row["assetName"]

                        df.at[idx, "standardFieldName"] = ""
                        invalid_removed_count += 1

                        event_log.append({
                            "row": idx + 2,
                            "asset": asset,
                            "object": "",
                            "reason": "invalid",
                            "from": original,
                            "to": ""
                        })

        duplicate_removed_count = resolve_duplicate_sfns(df, event_log)
        majority_vote_count = apply_majority_vote_by_object_name(df, event_log)

        df.drop(columns=["originalStandardFieldName"], inplace=True)

        output_path = (
            self.last_loadsheet_path
            .replace(".xlsx", "_cleaned.xlsx")
        )

        df.to_excel(output_path, index=False)

        print(f"\n💾 Cleaned spreadsheet saved as: {output_path}")

        # ----------------------------
        # FINAL REPORT
        # ----------------------------
        print("\n================ FINAL CHANGE SUMMARY ================")

        current_section = None

        for c in event_log:

            if c["reason"] == "invalid":
                section = "INVALID STANDARD FIELD NAMES"
            elif c["reason"] == "duplicate":
                section = "DUPLICATE STANDARD FIELD NAMES"
            elif c["reason"] == "majority_vote":
                section = "MAJORITY VOTE"
            else:
                section = "OTHER"

            if section != current_section:
                print(f"\n=== {section} ===")
                current_section = section

            parts = [f"Row {c['row']}"]

            if c["reason"] == "majority_vote":
                gt = c.get("generalType")
                if gt and not (pd.isna(gt) or str(gt).strip() == ""):
                    parts.append(gt)
            else:
                asset = c.get("asset")
                if not (pd.isna(asset) or str(asset).strip() == ""):
                    parts.append(asset)

            obj = c.get("object")
            if obj:
                parts.append(obj)

            parts.append(f"'{c['from']}' -> '{c['to']}'")

            print(" | ".join(parts))

        print(f"\n✅ Invalid SFNs removed: {invalid_removed_count}")
        print(f"✅ Duplicate SFNs removed: {duplicate_removed_count}")
        print(f"✅ Majority vote corrections: {majority_vote_count}")