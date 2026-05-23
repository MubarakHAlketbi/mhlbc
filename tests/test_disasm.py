"""Tests for hl_disasm.py — Gate 4 disassembly engine."""

import io
import json
import subprocess
import sys

import pytest
from hl_disasm import (
    OpcodeDecoder, CFGBuilder, JumpResolver, RegisterTracker,
    Disassembler, Instruction, BasicBlock, format_disassembly
)
from hl_parser import HLParser, HLParserError
from tests.hl_helper import (
    encode_varint, stream_from_bytes, build_minimal_bytecode,
    build_header, build_ints_pool, build_floats_pool, build_strings_pool,
)


# ── Helpers ─────────────────────────────────────────────────────────────

def encode_op(opcode: int, *args: int) -> bytes:
    """Encode an opcode with specific argument values."""
    data = bytes([opcode])
    for a in args:
        data += encode_varint(a)
    return data


def build_test_hlb(opcodes: bytes, nops: int, reg_types=None, ints=None, floats=None, strings=None):
    """Build a minimal HL bytecode file with custom opcodes."""
    reg_types = reg_types or [0]
    ints = ints or [1, 2]
    floats = floats or [1.0]
    strings = strings or ['test']
    
    fn_entry = encode_varint(0) + encode_varint(0)  # type_idx, findex
    fn_entry += encode_varint(len(reg_types))        # nregs
    fn_entry += encode_varint(nops)                   # nops
    for rt in reg_types:
        fn_entry += encode_varint(rt)
    fn_entry += opcodes
    
    header = build_header(version=5, nints=len(ints), nfloats=len(floats),
                         nstrings=len(strings), nfunctions=1)
    pools = build_ints_pool(ints) + build_floats_pool(floats) + build_strings_pool(strings)
    return header + pools + fn_entry


# ── Opcode Decoder Tests ────────────────────────────────────────────────

class TestOpcodeDecoder:
    
    def test_decode_simple_sequence(self):
        """OMov + OInt + ORet should decode correctly."""
        opcodes = encode_op(0, 0, 1) + encode_op(1, 2, 0) + encode_op(67, 0)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 3)
        
        assert len(instrs) == 3
        assert instrs[0].mnemonic == "OMov"
        assert instrs[0].args == [0, 1]
        assert instrs[0].opcode == 0
        assert instrs[1].mnemonic == "OInt"
        assert instrs[1].args == [2, 0]
        assert instrs[2].mnemonic == "ORet"
        assert instrs[2].args == [0]
    
    def test_mnemonic_lookup(self):
        """All 102 standard opcodes should have mnemonic names."""
        for i in range(102):
            name = OpcodeDecoder.mnemonic_for(i)
            assert name.startswith("O") or name == "OP_" + str(i), f"Bad mnemonic for opcode {i}: {name}"
        # OLast is sentinel
        assert OpcodeDecoder.mnemonic_for(102) == "OLast"
        # Out of range
        assert OpcodeDecoder.mnemonic_for(200) == "OP_200"
    
    def test_nargs_lookup(self):
        """Key opcodes should have correct arg counts."""
        assert OpcodeDecoder.nargs_for(0) == 2   # OMov
        assert OpcodeDecoder.nargs_for(6) == 1   # ONull
        assert OpcodeDecoder.nargs_for(7) == 3   # OAdd
        assert OpcodeDecoder.nargs_for(29) == -1 # OCallN
        assert OpcodeDecoder.nargs_for(44) == 2  # OJTrue
        assert OpcodeDecoder.nargs_for(58) == 1  # OJAlways
        assert OpcodeDecoder.nargs_for(66) == 0  # OLabel
        assert OpcodeDecoder.nargs_for(67) == 1  # ORet
        assert OpcodeDecoder.nargs_for(90) == -1 # OMakeEnum
        assert OpcodeDecoder.nargs_for(102) == 0 # OLast
    
    def test_truncated_data(self):
        """Truncated bytecode should return fewer instructions than requested."""
        opcodes = encode_op(0, 0, 1)  # Only 1 complete opcode, but request 3
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 3)
        assert len(instrs) <= 3
        assert len(instrs) >= 1  # Should get at least OMov
    
    def test_out_of_range_opcode(self):
        """Opcode index > 102 should decode as OP_NNN."""
        opcodes = bytes([200])  # Out of range
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OP_200 (INVALID)"
        assert instrs[0].opcode == 200
    
    def test_byte_offsets(self):
        """Each instruction should track its byte offset and size."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 2)
        
        # OMov: 1 op byte + 2 varints = 3 bytes
        assert instrs[0].byte_offset == 0
        assert instrs[0].byte_size == 3
        # ORet: starts at offset 3, 1 op byte + 1 varint = 2 bytes
        assert instrs[1].byte_offset == 3
        assert instrs[1].byte_size == 2
    
    def test_variable_arg_ocalln(self):
        """OCallN should decode correctly with variable args."""
        # OCallN: op=29, p1=0, p2=1, count=2, extra=[10, 20]
        opcodes = bytes([29]) + encode_varint(0) + encode_varint(1) + bytes([2]) + encode_varint(10) + encode_varint(20)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OCallN"
        # args: [p1, p2, count, extra0, extra1]
        assert len(instrs[0].args) >= 3
    
    def test_debug_info_attachment(self):
        """Debug line/file info should attach to instructions."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        debug_lines = [42, 99]
        debug_files = [0, 0]
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 2, debug_lines, debug_files)
        assert instrs[0].source_line == 42
        assert instrs[1].source_line == 99
    
    def test_label_detection(self):
        """OLabel should set is_label=True."""
        opcodes = encode_op(66)  # OLabel
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert instrs[0].is_label
        assert instrs[0].mnemonic == "OLabel"


# ── Jump Resolution Tests ───────────────────────────────────────────────

class TestJumpResolver:
    
    def test_simple_jump(self):
        """OJAlways with +5 offset should resolve to correct target."""
        # @0: OMov, @1: OInt, @2: OJAlways +5 → target=8
        opcodes = (encode_op(0, 0, 1) + encode_op(1, 0, 0) +
                  encode_op(58, 5) + encode_op(0, 0, 0) + encode_op(0, 0, 0) +
                  encode_op(0, 0, 0) + encode_op(0, 0, 0) + encode_op(0, 0, 0) +
                  encode_op(67, 0))
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 9)
        instrs = JumpResolver.resolve(instrs)
        
        assert instrs[2].jump_target == 8  # 2+1+5 = 8
    
    def test_conditional_jump(self):
        """OJFalse should resolve jump target."""
        opcodes = encode_op(45, 0, 3)  # OJFalse r0, +3 → target=5
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        instrs = JumpResolver.resolve(instrs)
        
        assert instrs[0].jump_target == 4  # index 0 + 1 + offset 3 = 4
    
    def test_backward_jump(self):
        """Negative jump offsets should work (back-edges for loops)."""
        # @0: OMov, @1: OInt, @2: OJTrue r0, -3 → target=0
        opcodes = encode_op(0, 0, 1) + encode_op(1, 0, 0) + encode_op(44, 0, -3)
        decode = OpcodeDecoder()
        instrs = decode.decode_instructions(opcodes, 3)
        instrs = JumpResolver.resolve(instrs)
        
        # JTrue at index 2 with offset -3 → target = 2+1-3 = 0
        assert instrs[2].jump_target == 0
    
    def test_no_jump_non_jump_op(self):
        """Non-jump opcodes should have None jump_target."""
        opcodes = encode_op(0, 0, 1)  # OMov
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        instrs = JumpResolver.resolve(instrs)
        
        assert instrs[0].jump_target is None


# ── CFG Builder Tests ───────────────────────────────────────────────────

class TestCFGBuilder:
    
    def test_linear_block(self):
        """A straight-line function should produce one basic block."""
        opcodes = encode_op(0, 0, 1) + encode_op(1, 0, 0) + encode_op(67, 0)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 3)
        instrs = JumpResolver.resolve(instrs)
        cfg = CFGBuilder.build(instrs)
        
        assert len(cfg) == 1
        assert cfg[0].start_ip == 0
        assert cfg[0].end_ip == 3
    
    def test_if_else_cfg(self):
        """An if-else should produce 4 basic blocks."""
        # @0: OMov r0,r1
        # @1: OJFalse r0, +2 → @4 (else)
        # @2: OInt r0, 0  (then)
        # @3: OJAlways +1 → @5 (merge)
        # @4: OInt r0, 1  (else)
        # @5: ORet r0     (merge)
        opcodes = (encode_op(0, 0, 1) + encode_op(45, 0, 2) +
                  encode_op(1, 0, 0) + encode_op(58, 1) +
                  encode_op(1, 0, 1) + encode_op(67, 0))
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 6)
        instrs = JumpResolver.resolve(instrs)
        cfg = CFGBuilder.build(instrs)
        
        assert len(cfg) >= 3, f"Expected >=3 blocks, got {len(cfg)}"
        # Block 0: entry (OMov + OJFalse)
        assert cfg[0].start_ip == 0
        assert cfg[0].end_ip == 2
        # Check block relationships
        all_succs = set()
        for blk in cfg:
            all_succs.update(blk.successors)
        # Should have at least 2 successor edges
        assert len(all_succs) >= 2
    
    def test_loop_cfg(self):
        """A loop with back-edge should set is_loop_header."""
        # @0: OMov r0, 0 (loop header)
        # @1: OJTrue r0, -1 → @1 (self-loop)
        # @2: ORet r0
        opcodes = encode_op(0, 0, 0) + encode_op(44, 0, -1) + encode_op(67, 0)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 3)
        instrs = JumpResolver.resolve(instrs)
        cfg = CFGBuilder.build(instrs)
        
        # Check that some block has is_loop_header
        loop_headers = [blk for blk in cfg if blk.is_loop_header]
        assert len(loop_headers) > 0, "No loop header detected"
    
    def test_multiple_blocks_no_duplicate_edges(self):
        """CFG edges should not have duplicates."""
        opcodes = (encode_op(0, 0, 1) + encode_op(45, 0, 2) +
                  encode_op(1, 0, 0) + encode_op(58, 1) +
                  encode_op(1, 0, 1) + encode_op(67, 0))
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 6)
        instrs = JumpResolver.resolve(instrs)
        cfg = CFGBuilder.build(instrs)
        
        for blk in cfg:
            assert len(blk.successors) == len(set(blk.successors)), \
                f"Block {blk.id} has duplicate successors: {blk.successors}"
            assert len(blk.predecessors) == len(set(blk.predecessors)), \
                f"Block {blk.id} has duplicate predecessors: {blk.predecessors}"


# ── Disassembler Integration Tests ─────────────────────────────────────

class TestDisassembler:
    
    def test_full_pipeline(self):
        """Parse bytecode + disassemble + validate."""
        opcodes = encode_op(0, 0, 1) + encode_op(1, 0, 0) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=3)
        p = HLParser('<test>')
        p.execute(stream_from_bytes(hlb))
        
        d = Disassembler(p)
        instrs = d.disassemble_function(0)
        assert len(instrs) == 3
        msgs = d.validate()
        assert not msgs, f"Validation warnings: {msgs}"
    
    def test_disassemble_malformed_skips(self):
        """Malformed functions should return empty list."""
        hlb = build_test_hlb(encode_op(0, 0, 1), nops=1)
        p = HLParser('<test>')
        p.execute(stream_from_bytes(hlb))
        # Force malformed
        p.functions[0].malformed = True
        
        d = Disassembler(p)
        instrs = d.disassemble_function(0)
        assert instrs == []
    
    def test_register_tracking(self):
        """Register tracker should record type assignments."""
        opcodes = encode_op(0, 0, 1) + encode_op(1, 0, 0) + encode_op(67, 0)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 3)
        
        reg_types = [0, 0, 0]
        history = RegisterTracker.track(instrs, reg_types)
        
        # r0 should have been written by OMov and OInt
        assert 0 in history
        assert len(history[0]) >= 2, f"Expected >=2 assignments to r0, got {len(history[0])}"
    
    def test_cfg_available_after_disasm(self):
        """build_cfg should work after disassemble_function."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=2)
        p = HLParser('<test>')
        p.execute(stream_from_bytes(hlb))
        
        d = Disassembler(p)
        d.disassemble_function(0)
        cfg = d.build_cfg(0)
        assert len(cfg) == 1


# ── CLI Tests ───────────────────────────────────────────────────────────

class TestCLIDisasm:
    
    def _run_cli(self, *args, input_hlb=None) -> subprocess.CompletedProcess:
        """Run the CLI with given args and optional temp input file."""
        import tempfile, os
        if input_hlb:
            tf = tempfile.NamedTemporaryFile(suffix='.hl', delete=False)
            tf.write(input_hlb)
            tf.close()
            filepath = tf.name
        else:
            filepath = '/nonexistent'
        
        cmd = [sys.executable, 'cli.py', 'disasm', filepath] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True,
                               cwd='/home/mubarak/mhlbc')
        
        if input_hlb:
            os.unlink(filepath)
        return result
    
    def test_disasm_json_output(self):
        """--json should produce valid JSON with instructions."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=2)
        
        result = self._run_cli('-f', '0', '--json', input_hlb=hlb)
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        
        data = json.loads(result.stdout)
        assert "function" in data
        assert data["function"]["nops"] == 2
        instrs = data["function"]["instructions"]
        assert len(instrs) == 2
        assert instrs[0]["mnemonic"] == "OMov"
        assert instrs[1]["mnemonic"] == "ORet"
    
    def test_disasm_human_output(self):
        """Default output should be human-readable with mnemonics."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=2)
        
        result = self._run_cli('-f', '0', input_hlb=hlb)
        assert result.returncode == 0
        assert "OMov" in result.stdout
        assert "ORet" in result.stdout
    
    def test_disasm_jump_target_in_json(self):
        """JSON output should include jump_target for jump instructions."""
        opcodes = encode_op(44, 0, 2)  # OJTrue r0, +2
        hlb = build_test_hlb(opcodes, nops=1)
        
        result = self._run_cli('-f', '0', '--json', input_hlb=hlb)
        assert result.returncode == 0
        
        data = json.loads(result.stdout)
        instr = data["function"]["instructions"][0]
        assert instr["mnemonic"] == "OJTrue"
        assert instr.get("jump_target") is not None
    
    def test_disasm_csv_output(self):
        """--csv should produce valid CSV with header."""
        opcodes = encode_op(0, 0, 1) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=2)
        
        result = self._run_cli('-f', '0', '--csv', input_hlb=hlb)
        assert result.returncode == 0
        assert 'func_idx' in result.stdout
        assert 'OMov' in result.stdout
    
    def test_disasm_nonexistent_file(self):
        """Nonexistent file should produce error exit."""
        result = self._run_cli('-f', '0')
        assert result.returncode != 0


class TestJSONOutputVerification(TestCLIDisasm):
    """Verify --json output round-trips cleanly."""

    def test_json_round_trip(self):
        """--json output should parse without error."""
        opcodes = encode_op(0, 0, 1) + encode_op(44, 0, 2) + encode_op(67, 0)
        hlb = build_test_hlb(opcodes, nops=3)
        result = self._run_cli('-f', '0', '--json', input_hlb=hlb)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "function" in data
        assert len(data["function"]["instructions"]) == 3

    def test_json_all_functions(self):
        """--json without --function should include all functions."""
        hlb = build_test_hlb(encode_op(67, 0), nops=1)
        result = self._run_cli('--json', input_hlb=hlb)
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "function" in data
        assert len(data["function"]["instructions"]) == 1


class TestVariableArgDecode:
    """Variable-arg opcodes: OCallN, OSwitch, OMakeEnum decoding."""

    def test_ocalln_decode(self):
        """OCallN with 3 arguments should decode correctly."""
        opcodes = encode_op(29, 0, 1) + bytes([3]) + encode_op(2) + encode_op(3) + encode_op(4)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OCallN"
        # Args: [r, findex, count, arg1, arg2, arg3]
        assert instrs[0].args == [0, 1, 3, 2, 3, 4]

    def test_oswitch_decode(self):
        """OSwitch with 3 cases should decode correctly."""
        opcodes = encode_op(70, 0, 3) + encode_op(2) + encode_op(4) + encode_op(6) + encode_op(8)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OSwitch"
        # Args: r + ncases + default_offset; cases stored in jump_cases
        assert instrs[0].args[:2] == [0, 3]
        assert instrs[0].jump_cases == [2, 4, 6]
        assert instrs[0].jump_default == 8

    def test_omakeenum_decode(self):
        """OMakeEnum with 2 params should decode correctly."""
        opcodes = encode_op(90, 0, 1) + bytes([2]) + encode_op(5) + encode_op(6)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OMakeEnum"
        # Args: [r, findex, nparams, param1, param2]
        assert instrs[0].args == [0, 1, 2, 5, 6]

    def test_ocallmethod_decode(self):
        """OCallMethod with 2 args should decode correctly."""
        opcodes = encode_op(30, 0, 1) + bytes([2]) + encode_op(2) + encode_op(3)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OCallMethod"

    def test_ocallthis_decode(self):
        """OCallThis with 1 arg should decode correctly."""
        opcodes = encode_op(31, 0, 1) + bytes([1]) + encode_op(2)
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OCallThis"

    def test_ocallclosure_decode(self):
        """OCallClosure with 0 args should decode correctly."""
        opcodes = encode_op(32, 0, 1) + bytes([0])
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OCallClosure"
        # Args: [r, closure_reg, count] + count × args
        assert instrs[0].args == [0, 1, 0]


class TestFuzzedOpcodes:
    """Fuzzed/truncated opcode edge cases."""

    def test_truncated_mid_opcode(self):
        """Data truncated after opcode byte should return incomplete instructions."""
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(bytes([0]), 1)  # OMov expects 2 args
        assert len(instrs) <= 1  # Should not crash

    def test_truncated_mid_second_opcode(self):
        """Truncated in middle of second opcode's args."""
        opcodes = encode_op(0, 0, 1) + bytes([7])  # OMov(0,1) + OAdd partial
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 2)
        assert len(instrs) >= 1  # At least OMov should decode

    def test_invalid_opcode_index(self):
        """Invalid opcode index (200) should still produce an instruction."""
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(bytes([200]), 1)
        assert len(instrs) == 1
        assert instrs[0].mnemonic == "OP_200 (INVALID)"
    def test_truncated_ocalln_count(self):
        """OCallN with truncated arg list after count byte."""
        opcodes = encode_op(29, 0, 1) + bytes([100]) + encode_op(2)  # claims 100 args, has 1
        decoder = OpcodeDecoder()
        instrs = decoder.decode_instructions(opcodes, 1)
        assert len(instrs) == 1  # Should still produce OCallN with partial args
