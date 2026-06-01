def get_SFN_options(constructed_type,general_types_data,secondary_general_types_data,abstract_data,secondary_abstract_data):

    type_name = constructed_type.strip()
    parts = type_name.split("_")

    if len(parts) < 2:
        print("❌ Invalid format. Expected at least one abstract after the general prefix.")
        return set()

    general_type = parts[0]
    abstract_types = parts[1:]

    all_required_fields = set()
    all_optional_fields = set()
    required_field_to_abstracts = {}
    missing_abstracts = []
    missing_general_types = []

    # ----------------------------
    # GENERAL TYPES
    # ----------------------------

    try:
        info = general_types_data.get(general_type)
        secondary_info = secondary_general_types_data.get(general_type)

        if not info and not secondary_info:
            missing_general_types.append(general_type)

        if info is not None:
            opt_uses = info.get("opt_uses", []) or []
            for field in opt_uses:
                all_optional_fields.add(str(field).strip().lower())

        if secondary_info is not None:
            secondary_opt_uses = secondary_info.get("opt_uses", []) or []
            for field in secondary_opt_uses:
                all_optional_fields.add(str(field).strip().lower())

    except Exception:
        print(f"⚠️ Error pulling data from: {general_type}")

    # ----------------------------
    # ABSTRACT TYPES
    # ----------------------------

    for abstract_type in abstract_types:

        try:
            info = abstract_data.get(abstract_type)

            if not info:
                missing_abstracts.append(abstract_type)
                continue

            for item in info.get("implements", []) or []:
                if item.startswith("/"):
                    secondary_impl = secondary_abstract_data.get(item.removeprefix("/"))
                    if secondary_impl:
                        for field in secondary_impl.get("uses", []):
                            info.setdefault("uses", []).append(field)

            uses = info.get("uses", []) or []
            opt_uses = info.get("opt_uses", []) or []

            for field in uses:
                norm_field = str(field).strip().lower()
                all_required_fields.add(norm_field)
                required_field_to_abstracts.setdefault(norm_field, set()).add(abstract_type)

            for field in opt_uses:
                all_optional_fields.add(str(field).strip().lower())

        except Exception:
            print(f"⚠️ Abstract not found in ABSTRACT.yaml: {abstract_type}")

    combined_fields = all_required_fields | all_optional_fields

    if missing_abstracts:
        print("⚠️ Missing abstracts (not found in ABSTRACT.yaml):")
        for a in missing_abstracts:
            print(f"  - {a}")

    return combined_fields