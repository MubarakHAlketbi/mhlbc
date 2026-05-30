"""B6: Field resolution diagnostic collection and classification tests."""

import pytest
from hl_decompile import (
    FieldResolveRecord,
    FN_CAT_RECEIVER_TYPE_MISSING,
    FN_CAT_RECEIVER_DECLARED_DYNAMIC,
    FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED,
    FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB,
    FN_CAT_THIS_FIELD_INDEX_OOB,
    FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE,
    FN_CAT_DYNAMIC_STRING_MISSING,
    FN_CAT_ENUM_FIELD_UNRESOLVED,
    FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE,
    FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD,
    FN_CAT_RECEIVER_TYPE_INVALID,
    FN_CAT_UNKNOWN_FIELD_PATTERN,
    K_OBJ, K_DYN,
)


class TestFieldResolveRecord:
    """FieldResolveRecord dataclass instantiation and defaults."""

    def test_instantiation(self):
        rec = FieldResolveRecord(
            func_idx=0, instr_idx=0, opcode=38, op_name="OField",
            receiver_reg=1, field_idx=2,
            receiver_type_idx=10, receiver_type_kind=K_OBJ,
            receiver_type_name="MyClass",
            resolution_strategy="parent_type",
            parent_type_idx=10,
            resolved_name="radius", is_fallback=False,
        )
        assert rec.is_fallback is False
        assert rec.resolved_name == "radius"
        assert rec.receiver_type_kind == K_OBJ
        assert rec.subcategory == ""  # default

    def test_fallback_detection(self):
        rec = FieldResolveRecord(
            func_idx=0, instr_idx=0, opcode=39, op_name="OSetField",
            receiver_reg=2, field_idx=5,
            receiver_type_idx=-1, receiver_type_kind=-1,
            receiver_type_name="unknown",
            resolution_strategy="none",
            parent_type_idx=-1,
            resolved_name="f5", is_fallback=True,
        )
        assert rec.is_fallback is True
        assert rec.resolved_name == "f5"
        assert rec.receiver_type_idx == -1


class TestFieldSubcategoryConstants:
    """All B6 subcategory constants must be distinct strings."""

    def test_distinct(self):
        cats = [
            FN_CAT_RECEIVER_TYPE_MISSING,
            FN_CAT_RECEIVER_DECLARED_DYNAMIC,
            FN_CAT_RECEIVER_VIRTUAL_UNSUPPORTED,
            FN_CAT_RECEIVER_OBJECT_FIELD_INDEX_OOB,
            FN_CAT_THIS_FIELD_INDEX_OOB,
            FN_CAT_DYNAMIC_STRING_FIELD_AVAILABLE,
            FN_CAT_DYNAMIC_STRING_MISSING,
            FN_CAT_ENUM_FIELD_UNRESOLVED,
            FN_CAT_ENUM_RECEIVER_NOT_ENUM_OPCODE,
            FN_CAT_FUN_OR_METHOD_RECEIVER_FIELD,
            FN_CAT_RECEIVER_TYPE_INVALID,
            FN_CAT_UNKNOWN_FIELD_PATTERN,
        ]
        assert len(set(cats)) == len(cats), "All subcategory constants must be distinct"

    def test_known_values(self):
        assert FN_CAT_RECEIVER_TYPE_MISSING == "receiver_type_missing"
        assert FN_CAT_RECEIVER_DECLARED_DYNAMIC == "receiver_declared_dynamic"
        assert FN_CAT_ENUM_FIELD_UNRESOLVED == "enum_field_unresolved"


class TestFieldDiagCollection:
    """Field diagnostics are collected during decompilation."""

    def test_diags_populated_on_fixture(self):
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        parser = HLParser("tests/fixtures/hl/Enums.hl")
        parser.execute()
        disasm = Disassembler(parser)
        dec = Decompiler(parser, disasm)
        result = dec.decompile_all()

        total_diags = sum(
            len(ir_fn.field_resolve_diags)
            for ir_fn in result.functions.values()
        )
        assert total_diags > 0, "Should collect field resolve diagnostics"

    def test_enum_fields_resolved_on_enums_fixture(self):
        """Enum field name recovery resolves some OEnumField accesses."""
        from hl_parser import HLParser
        from hl_disasm import Disassembler
        from hl_decompile import Decompiler

        parser = HLParser("tests/fixtures/hl/Enums.hl")
        parser.execute()
        disasm = Disassembler(parser)
        dec = Decompiler(parser, disasm)
        result = dec.decompile_all()

        total_enum = 0
        resolved_enum = 0
        for ir_fn in result.functions.values():
            for d in ir_fn.field_resolve_diags:
                if d.opcode in (93, 94):
                    total_enum += 1
                    if not d.is_fallback:
                        resolved_enum += 1

        assert total_enum > 0, "Enums fixture should have OEnumField instructions"
        assert resolved_enum > 0, (
            f"No enum fields resolved; {total_enum} total accesses"
        )
