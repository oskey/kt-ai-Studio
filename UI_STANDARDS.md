# KT AI Studio - UI Design Standards

This document defines the unified UI/UX standards for the KT AI Studio project. All future development must strictly adhere to these guidelines to ensure consistency and a modern user experience.

## 1. Interaction & Feedback (Notifications)

**RULE: NEVER use native browser `alert()`, `confirm()`, or `prompt()`.**

### 1.1 Toast Notifications (Transient Feedback)
Use for non-blocking success, info, or error messages that disappear automatically.

- **Component**: Bootstrap 5 Toasts
- **Helper Function**: `showToast(message, type='info', duration=3000)`
- **Types**:
  - `success` (Green): Operation completed successfully.
  - `error` (Red): Operation failed.
  - `warning` (Yellow): Warning or caution.
  - `info` (Blue): General information.

**Usage Example:**
```javascript
// Good
showToast("保存成功", "success");
showToast("网络连接失败", "error");

// Bad
alert("保存成功");
```

### 1.2 Modal Dialogs (Confirmation & Forms)
Use for blocking actions requiring user decision or input.

- **Component**: Bootstrap 5 Modals
- **Styling**:
  - Rounded corners (`rounded-4`)
  - No border (`border-0`)
  - Soft shadows (`shadow-lg`)
  - Centered (`modal-dialog-centered`)
- **Action Buttons**:
  - Primary Action: `btn-primary` or `btn-danger` (for destructive)
  - Cancel Action: `btn-light`

## 2. Visual Style

### 2.1 Color Palette
- **Primary**: Bootstrap Primary Blue (`#0d6efd`) or Indigo (`#6610f2`)
- **Success**: Green (`#198754`)
- **Danger**: Red (`#dc3545`)
- **Warning**: Yellow/Orange (`#ffc107`)
- **Backgrounds**:
  - Main BG: Light Gray (`#f8f9fa`)
  - Card BG: White (`#ffffff`)
  - Sidebar/Panel BG: Light (`#f8f9fa` or `#ffffff`)

### 2.2 Typography
- **Font Family**: System UI (San Francisco, Segoe UI, Roboto, etc.)
- **Headings**: Bold (`fw-bold`), Dark (`text-dark`)
- **Body Text**: Standard weight, Gray-700 (`text-secondary` for muted)
- **Labels**: Small, Uppercase or Muted (`text-label` custom class)

### 2.3 Components

#### Buttons
- **Shape**: Fully Rounded Pills (`rounded-pill`)
- **Size**: Standard (`btn-sm` for compact actions)
- **Icons**: Bootstrap Icons (`bi-`)
- **Shadow**: Subtle shadow on hover (`shadow-sm`, `hover-shadow`)

#### Cards
- **Border**: None or Subtle (`border-0` or `border-light`)
- **Shadow**: None or Small (`shadow-sm`)
- **Radius**: `rounded-3` or `rounded-4`

#### Inputs
- **Style**: `bg-light`, `border-0` (Modern look)
- **Focus**: Standard Bootstrap ring

## 3. Layout Structure
- **Navigation**: Top breadcrumb or Sidebar
- **Content Area**: Container Fluid (`container-fluid px-4`)
- **Grid**: 
  - Left Column (3/12 or 4/12): Settings, Controls, Info
  - Right Column (9/12 or 8/12): Preview, Results, Lists

## 4. Implementation Checklist
Before submitting code, verify:
1. [ ] No `alert()` calls exist.
2. [ ] All buttons use `rounded-pill`.
3. [ ] Cards use `border-0` or minimal borders.
4. [ ] Feedback uses `showToast()`.
5. [ ] Confirmations use Modals.
