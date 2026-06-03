# Performance and Scalability

Large bytecode files can contain tens of thousands of strings, types, functions, and opcodes.

## Required Behavior

- Avoid O(N) UI widgets for large lists.
- Avoid unnecessary full-copy transformations of large byte arrays.
- Preserve compatibility with bytes, bytearray, and mmap where existing code supports them.
- Keep parser structures plain and serializable where practical.
- Prefer streaming or indexed access over eager expansion when possible.

## GUI-Facing Guardrails

- Long-running parse, disassembly, decompile, report, or analysis work must not block the UI thread.
- Large lists should use model/view virtualization rather than eagerly materialized widgets.
