# -*- coding: utf-8 -*-
"""解密 SQLCipher4 的 WAL 文件并重建为可被 sqlite3 回放的明文 WAL。

WAL 结构: 32 字节头部 + N 个帧(24 字节帧头 + 4096 字节页数据)。
页数据加密方式与 db 页相同(尾部 80 字节为 IV16+HMAC64)。
帧校验和是对"帧头前8字节+加密页数据"算的, 解密后必须重算。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wcdb_key_tool_windows import _decrypt_page, PAGE_SZ

WAL_HDR_SZ = 32
FRAME_HDR_SZ = 24


def wal_checksum(data, s0, s1, big_endian):
    fmt = ">I" if big_endian else "<I"
    for i in range(0, len(data), 8):
        x0 = struct.unpack_from(fmt, data, i)[0]
        x1 = struct.unpack_from(fmt, data, i + 4)[0]
        s0 = (s0 + x0 + s1) & 0xFFFFFFFF
        s1 = (s1 + x1 + s0) & 0xFFFFFFFF
    return s0, s1


def decrypt_wal(enc_wal_path: str, out_wal_path: str, enc_key: bytes) -> int:
    with open(enc_wal_path, "rb") as f:
        wal = f.read()
    if len(wal) < WAL_HDR_SZ:
        print("  WAL 太小, 跳过")
        return 0
    hdr = bytearray(wal[:WAL_HDR_SZ])
    magic, version, pagesize, ckpt = struct.unpack(">IIII", hdr[:16])
    if magic not in (0x377F0682, 0x377F0683):
        print(f"  非 WAL 文件 magic={magic:#x}, 跳过")
        return 0
    big_endian = magic == 0x377F0683
    assert pagesize == PAGE_SZ, f"page size {pagesize}"
    salt1, salt2 = struct.unpack(">II", hdr[16:24])

    # 头部校验和(前 24 字节, 明文不变, 只需读出作为帧校验的起点)
    s0, s1 = wal_checksum(bytes(hdr[:24]), 0, 0, big_endian)

    nframes = (len(wal) - WAL_HDR_SZ) // (FRAME_HDR_SZ + PAGE_SZ)
    out = bytearray()
    out += hdr  # 头部原样保留(含原校验和, 明文未变仍有效)

    good_frames = 0
    for i in range(nframes):
        off = WAL_HDR_SZ + i * (FRAME_HDR_SZ + PAGE_SZ)
        fhdr = bytearray(wal[off: off + FRAME_HDR_SZ])
        page = wal[off + FRAME_HDR_SZ: off + FRAME_HDR_SZ + PAGE_SZ]
        if len(page) < PAGE_SZ:
            break
        fsalt1, fsalt2 = struct.unpack(">II", fhdr[8:16])
        if (fsalt1, fsalt2) != (salt1, salt2):
            break  # salt 变了说明之后的帧属于旧 checkpoint, 无效
        pgno = struct.unpack(">I", fhdr[:4])[0]
        dec_page = _decrypt_page(enc_key, page, pgno)
        # 重算校验和: 帧头前 8 字节 + 解密后的页
        s0, s1 = wal_checksum(bytes(fhdr[:8]), s0, s1, big_endian)
        s0, s1 = wal_checksum(dec_page, s0, s1, big_endian)
        fhdr[16:24] = struct.pack(">II", s0, s1)
        out += fhdr
        out += dec_page
        good_frames += 1

    with open(out_wal_path, "wb") as f:
        f.write(out)
    return good_frames


if __name__ == "__main__":
    enc_wal, out_wal, key_hex = sys.argv[1], sys.argv[2], sys.argv[3]
    n = decrypt_wal(enc_wal, out_wal, bytes.fromhex(key_hex))
    print(f"  WAL 解密完成: {n} 帧")
