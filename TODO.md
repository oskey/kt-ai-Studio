# TODO List

## Bug Fixes
- [ ] **Scene Merge Cleanup**: Delete temporary images (e.g., `ComfyUI_temp_xxxxx_.png`) after successful scene merge. Only keep the final result.

## Improvements
- [ ] **Scene Status Logic**:
    - [ ] Update Scene List to show "Draft" (草稿) if no generation occurred.
    - [ ] "Completed" (完成) status requires BOTH Base Image (Scene Gen) AND Character Merge to be finished.
    - [ ] Update Scene Detail top-right badge to reflect this logic.
- [ ] **Merge Prerequisites**:
    - [ ] Disable "Merge Character" button if Scene Base Image is missing.
    - [ ] Check if associated Character has 8-mirror images generated ("Completed"). Prompt user to generate character images first if not ready.

## New Features
- [ ] **System Logs (系统日志)**:
    - [ ] Create a dedicated log database table (Time, Module, Count/Progress, Message).
    - [ ] Add "System Logs" page to sidebar.
    - [ ] Implement auto-scrolling, read-only console-like UI.
    - [ ] Log key events (e.g., batch generation progress).
- [ ] **Batch Character Generation**:
    - [ ] Add "One-Click Generate All Base Images" (一键生成所有基图) to Character List:
        - Skips "Completed"/"Ready".
        - Processes "Draft" -> "Ready" (Prompt + Base Image).
        - Runs in background with log updates.
    - [ ] Add "One-Click Generate Character Complete" (一键生成角色完整图) to Character List:
        - Skips "Completed".
        - Processes "Ready" -> "Completed" (8-mirror).
        - Processes "Draft" -> "Completed" (Prompt + Base + 8-mirror).
        - Runs in background with log updates.
