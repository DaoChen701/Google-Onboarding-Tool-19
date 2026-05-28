import pandas as pd
import yaml
import os
import re
from sentence_transformers import SentenceTransformer, util
from .abbreviations import ABBREVIATIONS
from .allowed_tokens import ALLOWED_TOKENS
from .get_SFN_options import get_SFN_options

def load_yaml(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def normalize_text(text):
    if pd.isna(text) or text is None:
        return ""

    text = str(text).lower()
    tokens = text.split()

    prefix_mapping = {
        "sf": "supply_fan", "ef": "exhaust_fan", "rf": "exhaust_fan", 
        "df": "discharge_fan", "sfan": "supply_fan", "efan": "exhaust_fan", 
        "rfan": "exhaust_fan", "dfan": "discharge_fan"
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

            df.at[idx, "standardFieldName"] = replacement
            updated_count += 1

            event_log.append({
                "row": idx + 2,
                "asset": df.at[idx, "assetName"],
                "generalType": general_type,
                "object": object_name,
                "reason": "majority_vote",
                "from": current_str,
                "to": replacement
            })

    return updated_count

class LoadsheetPostProcessor:
    @classmethod
    def run(cls, df: pd.DataFrame, loadsheet_path: str, ontology_root: str):
        """
        Executes the post-processing pipeline on the loadsheet dataframe.
        """
        event_log = []
        
        # ----------------------------
        # LOAD YAML
        # ----------------------------
        general_types_data = load_yaml(os.path.join(ontology_root, "HVAC", "entity_types", "GENERALTYPES.yaml"))
        secondary_general_types_data = load_yaml(os.path.join(ontology_root, "entity_types", "global.yaml"))
        abstract_data = load_yaml(os.path.join(ontology_root, "HVAC", "entity_types", "ABSTRACT.yaml"))
        secondary_abstract_data = load_yaml(os.path.join(ontology_root, "entity_types", "ABSTRACT.yaml"))

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
                        df.at[idx, "standardFieldName"] = ""
                        invalid_removed_count += 1

                        event_log.append({
                            "row": idx + 2,
                            "asset": row["assetName"],
                            "object": "",
                            "reason": "invalid",
                            "from": original,
                            "to": ""
                        })

        # ----------------------------
        # DUPLICATES & MAJORITY VOTE
        # ----------------------------
        duplicate_removed_count = resolve_duplicate_sfns(df, event_log)
        majority_vote_count = apply_majority_vote_by_object_name(df, event_log)

        # ----------------------------
        # EXPORT CLEANED FILE
        # ----------------------------
        df.drop(columns=["originalStandardFieldName"], inplace=True)
        output_path = loadsheet_path.replace(".xlsx", "_cleaned.xlsx")
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