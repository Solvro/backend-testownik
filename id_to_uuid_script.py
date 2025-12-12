import json
import uuid
from pathlib import Path


def migrate_user_ids():
    # Configuration
    input_file = Path("db.json")
    output_file = Path("migrated_db.json")
    user_model = "users.user"

    # Load entire database
    with open(input_file) as f:
        data = json.load(f)

    # Phase 1: Create ID mapping and update users
    id_mapping = {}
    for entry in data:
        if entry["model"] == user_model:
            old_id = entry["pk"]
            new_uuid = str(uuid.uuid4())
            id_mapping[old_id] = new_uuid
            entry["pk"] = new_uuid
            entry["fields"]["usos_id"] = old_id

            # Update ID field if explicitly defined in model
            if "id" in entry["fields"]:
                entry["fields"]["id"] = new_uuid

    # Phase 2: Update all foreign keys
    for entry in data:
        # Update foreign keys
        if entry["model"] == "users.usersettings" and entry["pk"] in id_mapping:
            # Handle OneToOneField as primary key
            entry["pk"] = id_mapping[entry["pk"]]

        # Update regular foreign keys
        for field in ["user", "maintainer"]:
            if field in entry["fields"] and entry["fields"][field] in id_mapping:
                entry["fields"][field] = id_mapping[entry["fields"][field]]

        # Update M2M relationships (StudyGroup members)
        if entry["model"] == "users.studygroup" and "members" in entry["fields"]:
            entry["fields"]["members"] = [
                id_mapping[member_id] for member_id in entry["fields"]["members"] if member_id in id_mapping
            ]

        # Update admin log entries
        if (entry["model"] == "admin.logentry") and ("object_id" in entry["fields"]):
            object_id = entry["fields"]["object_id"]
            try:
                if int(object_id) in id_mapping:
                    entry["fields"]["object_id"] = id_mapping[int(object_id)]
            except ValueError:
                pass

    # Save migrated data
    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    # Save ID mapping for reference
    with open("id_mapping.json", "w") as f:
        json.dump(id_mapping, f, indent=2)


if __name__ == "__main__":
    migrate_user_ids()
