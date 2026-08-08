from __future__ import annotations


def normalize_workspace_folder(folder: str) -> str:
    return folder.replace("\\", "/").strip().strip("/")


def resolve_workspace_folder_id(
    folders: list[dict],
    configured_folder: str,
) -> str:
    normalized_folder = normalize_workspace_folder(configured_folder)
    if not normalized_folder:
        raise ValueError("Workspace folder name cannot be empty.")
    if "/" in normalized_folder:
        raise ValueError(
            f"Workspace folder '{configured_folder}' must be a root folder name, not a path."
        )

    root_matches: list[str] = []
    for folder in folders:
        folder_id = str(folder.get("id") or "").strip()
        if not folder_id:
            continue
        display_name = str(folder.get("displayName") or "").strip()
        if display_name.lower() != normalized_folder.lower():
            continue
        if str(folder.get("parentFolderId") or "").strip():
            continue
        root_matches.append(folder_id)

    if len(root_matches) == 1:
        return root_matches[0]
    if len(root_matches) > 1:
        raise ValueError(
            f"Multiple root workspace folders named '{configured_folder}' were found."
        )

    raise ValueError(
        f"Workspace folder '{configured_folder}' was not found as a root folder."
    )
