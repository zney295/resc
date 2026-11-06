# NTFS VBR/MFT: quy trình hiện hành

Dùng [NTFS RAW](../../disk-forensics/playbooks/02_ntfs_raw_repair.md) cho boot
proposal. Giữ partition boundary, geometry 512/4096, record size/fixup và identity;
không lấy ví dụ sector/record cố định làm thông số nguồn thật.

- Boot proposal -> overlay -> root traversal -> allocated extraction -> verify.
- Patch API là copy_from_lba/to_lba hoặc patches[{lba,offset,hex_data}], kèm
  session_id và partition_start_lba phù hợp. Không dùng patch_hex.
- MFTMirr không là bản sao mọi file/user record. Không tự áp bốn record 1024 byte
  trong mọi geometry hoặc coi journal NotImplemented là validation.
- Native tree không hỗ trợ deleted/ADS/compressed/encrypted/sparse/attribute-list
  extraction. Giữ ảnh và chuyển engine phù hợp khi cần.
- Mirror repair thủ công, nếu có căn cứ, vẫn chỉ hypothesis trong overlay;
  không claim resc có automatic MFT reconstruction.
- Khi không đủ bytes gốc, sao metadata không tạo lại payload. Thay đổi sau
  reconnect cần [persistence/reader controls](../../recovery-triage/references/persistence-lab.md).
