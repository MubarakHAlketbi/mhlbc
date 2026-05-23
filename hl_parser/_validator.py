class ParseValidator:
    """Post-parse validation pass checking consistency after HLParser.execute().

    Runs sanity checks on parsed data and produces structured diagnostics
    to catch stream alignment errors and format mismatches early.
    """

    def __init__(self, parser: 'HLParser'):
        self.parser = parser
        self.warnings: list[dict] = []

    def _warn(self, msg: str) -> None:
        self.warnings.append({"tag": "VALIDATE", "message": msg})

    def validate(self) -> list[dict]:
        """Run all checks and return list of warning dicts."""
        self._check_native_findex_bounds()
        self._check_function_findex_bounds()
        self._check_globals_bounds()
        return self.warnings

    def _check_native_findex_bounds(self) -> None:
        """Native findex must be non-negative."""
        for i, n in enumerate(self.parser.natives or []):
            fi = n.get("findex")
            if fi is not None and fi < 0:
                self._warn(f"native[{i}].findex={fi} is negative")

    def _check_function_findex_bounds(self) -> None:
        """Functions have combined namespace: natives[0..nnatives) + functions[nnatives..)."""
        total = self.parser.nnatives + self.parser.nfunctions
        for i, f in enumerate(self.parser.functions or []):
            fi = f.get("findex")
            if fi is not None and (fi < 0 or fi >= total):
                self._warn(f"function[{i}].findex={fi} out of range [0, {total})")

    def _check_globals_bounds(self) -> None:
        """Global type indices must be in [0, ntypes)."""
        for i, g in enumerate(self.parser.globals or []):
            if g is not None and (g < 0 or g >= self.parser.ntypes):
                self._warn(f"global[{i}].type={g} out of range [0, {self.parser.ntypes})")