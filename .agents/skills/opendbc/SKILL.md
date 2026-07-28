```markdown
# opendbc Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `opendbc` repository, which is primarily a Python codebase without a detected framework. You'll learn about file organization, import/export styles, commit message patterns, and how to work with the repository's testing approach.

## Coding Conventions

### File Naming
- Use **snake_case** for all Python files and modules.
  - Example: `signal_parser.py`, `dbc_loader.py`

### Import Style
- Prefer **relative imports** within the package.
  - Example:
    ```python
    from .signal_parser import parse_signals
    from . import dbc_loader
    ```

### Export Style
- Use **named exports** by explicitly listing public objects in `__all__` or through direct function/class definitions.
  - Example:
    ```python
    __all__ = ['parse_signals', 'DBCFile']
    ```

### Commit Message Patterns
- Commit messages are freeform, sometimes prefixed (e.g., `tests`), with an average length of 68 characters.
  - Example:  
    ```
    tests: add additional edge case for dbc_loader
    ```

## Workflows

### Adding a New Feature
**Trigger:** When you need to implement new functionality.
**Command:** `/add-feature`

1. Create a new Python file using snake_case if needed.
2. Implement the feature using relative imports for internal modules.
3. Export new functions/classes via named exports.
4. Write or update tests as appropriate.
5. Commit changes with a descriptive message.

### Fixing a Bug
**Trigger:** When a bug is reported or discovered.
**Command:** `/fix-bug`

1. Locate the relevant module using snake_case conventions.
2. Apply the fix, using relative imports if importing from other modules.
3. Update or add test cases to cover the bug.
4. Commit with a clear message describing the fix.

### Writing or Updating Tests
**Trigger:** When adding features or fixing bugs.
**Command:** `/write-test`

1. Locate or create a test file matching the pattern `*.test.ts`.
2. Add or update test cases relevant to your changes.
3. Run tests to ensure correctness.
4. Commit with a message prefixed by `tests:` if desired.

## Testing Patterns

- Test files follow the pattern `*.test.ts`.
- The specific testing framework is **unknown**; inspect existing test files for conventions.
- Place test files alongside or in a dedicated test directory as per repository structure.
- Example test file name: `signal_parser.test.ts`

## Commands

| Command        | Purpose                                    |
|----------------|--------------------------------------------|
| /add-feature   | Guide for adding a new feature             |
| /fix-bug       | Steps to fix a bug                         |
| /write-test    | Instructions for writing or updating tests |

```