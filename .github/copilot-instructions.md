# GitHub Copilot System Instructions: ComfyUI Development

## 🛠️ Environment & Architecture
- **Environment:** ComfyUI running inside the Unraid community Docker container `ComfyUI-Nvidia-Docker`.
- **Python Virtual Environment:** Located inside the container at `./mnt/venv`. Always use this path for package discovery or interpreter context.
- **Languages:** Strictly **Python** for node logic and backend architecture; **JSON** for ComfyUI workflow structures.

---

## 📂 Strict Directory & File Routing
You must enforce strict boundaries when creating or modifying files:
- 🗺️ **Workflows:** All workflow creations, edits, or exports must be restricted to:
  `user/default/workflows/`
- 🧩 **Custom Nodes:** All Python backend logic, custom node creations, or edits must be restricted to:
  `custom_nodes/_personal-custom-nodes/`
- 📑 **Agent Output:** Write all planning and tracking documentation (`plan_*.md` and `memory_*.md`) exclusively to:
  `.copilot/`

---

## 🛠️ Development & Quality Standards
- **Code Formatting:** Never ignore **Ruff** formatting or linting errors. All generated Python code must strictly adhere to Ruff's lint rules and formatting standards.
- **Code Integrity:** Never ignore pre-existing bugs, type mismatches, or structural issues. Fix or account for them during edits.
- **Design Principles:** Strictly apply software engineering principles:
  - **DRY** (Don't Repeat Yourself)
  - **SRP** (Single Responsibility Principle)
  - **YAGNI** (You Aren't Gonna Need It)
  - **KISS** (Keep It Simple, Stupid)

---

## 📝 Required Documentation Maintenance
You are responsible for keeping project metadata continuously synchronized. Update the following files seamlessly as changes occur:

1. **Global Scope:** Keep `README.md` (root directory) updated with overall project descriptions, high-level features, and Unraid-specific infrastructure notes.
2. **Custom Nodes Scope:** Keep `custom_nodes/_personal-custom-nodes/README.md` and `custom_nodes/_personal-custom-nodes/pyproject.toml` updated with exact dependencies, node descriptions, and module details.
3. **Execution Tracking:** Continuously update any `plan_*.md` and `memory_*.md` files in `.copilot/` as granular sub-tasks are completed or when project memory shifts.
