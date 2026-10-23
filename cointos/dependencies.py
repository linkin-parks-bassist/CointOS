"""Pure queue dependency spelling and brief metadata; no runtime state imports."""
import re

def line(text: str, label: str) -> str | None:
    """The value of a brief's `Label:` line, if it has one."""
    for row in text.splitlines():
        found = re.match(rf"\**{label}:\**\s*(.+)", row.strip(), re.IGNORECASE)
        if found:
            return found[1].strip()
    return None


NO_DEPENDENCY = {"none", "nothing", "n/a", "-"}


def depends(text: str) -> list[str]:
    """The items named on a brief's `Depends on:` line, comma-separated; `none` names nothing."""
    names = []
    for name in (line(text, "Depends on") or "").split(","):
        name = name.strip().strip("`*()[]").strip().rstrip(".;").strip("`*()[]").strip()
        if name and name.lower() not in NO_DEPENDENCY and name not in names:
            names.append(name)
    return names


def dependency_brief(brief: str, dependencies: list[str]) -> str:
    """Replace dependency metadata without changing the assignment's other text."""
    return metadata_brief(brief, "Depends on", ", ".join(dependencies) or "none")


def metadata_brief(brief: str, label: str, value: str) -> str:
    """Render structured metadata into the human-readable assignment projection."""
    metadata = label + ": " + value
    rows = brief.splitlines()
    found = False
    result = []
    for row in rows:
        if re.match(rf"\**{re.escape(label)}:\**", row.strip(), re.IGNORECASE):
            if not found:
                result.append(metadata)
                found = True
        else:
            result.append(row)
    if not found:
        result.insert(0, metadata)
    return "\n".join(result)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def canonical(project: str, names: list[str]) -> list[str]:
    result = []
    for name in names:
        if ':' in name:
            owner, _, item = name.partition(':')
            if owner != project or item != slug(item) or item.lower() in NO_DEPENDENCY:
                raise ValueError(f"dependency {name!r} must name an item in project {project!r}; "
                                 "use ITEM or PROJECT:ITEM for this project")
            name = item
        if name not in result:
            result.append(name)
    return result
