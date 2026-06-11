# GINI AI - GLOBAL EXECUTION RULES
# Applies to EVERY task automatically.
# Last updated: Task 5

====================================================
PHASE 0 — PRE-IMPLEMENTATION ANALYSIS (MANDATORY)
====================================================

Before writing any code:

1. Inspect the entire relevant project area.
2. Identify:
   - Existing components
   - Existing files
   - Existing architecture
   - Existing integrations
   - Existing dependencies

3. Classify each item as:
   - WORKING
   - PARTIAL
   - BROKEN
   - MISSING

4. Never assume a component is missing.
5. Never create code before inspection.
6. Never duplicate functionality.
7. Never create alternative versions of existing modules.
8. Reuse existing implementations whenever possible.
9. Preserve existing architecture unless there is a critical reason to change it.
10. Create a short implementation plan before modifying code.

====================================================
IMPLEMENTATION RULES
====================================================

1.  Follow existing project architecture.
2.  Maintain modular design.
3.  Keep code scalable.
4.  Keep code production-ready.
5.  Use clear naming conventions.
6.  Add documentation where appropriate.
7.  Add type hints where appropriate.
8.  Avoid hardcoded values.
9.  Use centralized configuration.
10. Use centralized logging.
11. Preserve backward compatibility whenever possible.
12. Do not remove existing functionality unless it is broken and replacement is implemented.
13. Do not rewrite large systems when a small fix is sufficient.
14. Minimize file creation.
15. Minimize unnecessary refactoring.

====================================================
ERROR PREVENTION RULES
====================================================

Before creating any file:
  → Check whether an equivalent file already exists.

Before creating any module:
  → Check whether similar functionality already exists.

Before adding dependencies:
  → Check whether existing dependencies already solve the problem.

Before refactoring:
  → Verify that refactoring provides measurable value.

Never introduce duplicate:
  - routers
  - services
  - managers
  - handlers
  - utilities
  - configs
  - loggers
  - memory systems

====================================================
TESTING REQUIREMENTS
====================================================

After implementation:

1.  Validate imports.
2.  Validate dependency usage.
3.  Validate integration points.
4.  Validate startup flow.
5.  Validate error handling.
6.  Validate existing functionality still works.
7.  Check for regressions.
8.  Check for broken references.
9.  Check for duplicate logic.
10. Check for runtime issues.

====================================================
REQUIRED TASK REPORT FORMAT
====================================================

START OF EVERY TASK:

### Inspection Report

Existing Components:
- component_name: WORKING | PARTIAL | BROKEN | MISSING

Implementation Plan:
- Step 1...
- Step 2...

----------------------------------------------------

END OF EVERY TASK:

### Completion Report

Files Modified:
- path/to/file.py — reason

Files Created:
- path/to/file.py — reason

Files Removed:
- (none) or path

Components Implemented:
- ...

Components Fixed:
- ...

Validation Performed:
- ...

Risks Remaining:
- ...

Recommended Next Task:
- ...

====================================================
RULE 11 — ZIP RULE
====================================================

After EVERY task:
  Generate a ZIP of the ENTIRE project (all tasks combined).
  Not just the current task's files — the complete codebase.
  Name: GINI-ORACLE-1-Complete.zip

====================================================
CRITICAL RULE
====================================================

DO NOT:
  - Blindly generate code
  - Recreate existing systems
  - Duplicate modules
  - Rewrite working code
  - Change architecture without justification

ALWAYS:
  Inspect → Analyze → Plan → Implement → Validate → Report
