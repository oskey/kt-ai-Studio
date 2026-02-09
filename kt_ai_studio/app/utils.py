from app.config import config

def to_web_path(path: str):
    if not path:
        return ""
    # Normalize slashes for comparison
    path = path.replace("\\", "/")
    output_dir = config.OUTPUT_DIR.replace("\\", "/")
    
    # 1. Absolute Path
    if path.startswith(output_dir):
        rel_path = path[len(output_dir):]
        if rel_path.startswith("/"):
            rel_path = rel_path[1:]
        return f"/output/{rel_path}"

    # 2. Relative Path starting with "output/" (stored in DB)
    # We want to map this to the /output mount point.
    if path.startswith("output/"):
        return f"/{path}"

    # 3. Relative Path without "output/" (legacy or inside output)
    if not path.startswith("/") and not path.startswith("http"):
        return f"/output/{path}"

    return path
