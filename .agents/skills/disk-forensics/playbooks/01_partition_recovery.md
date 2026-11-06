# MBR/GPT: proposal có kiểm chứng, sửa thử trong overlay

Chỉ dùng sau [triage](../../recovery-triage/SKILL.md) trên nguồn có capacity/
geometry đáng tin. No Media/0 byte không đi nhánh partition repair.

1. Mở ảnh đúng sector size, gọi `scan_disk_topology` và
   `analyze_partition_recovery(session_id)`. Kiểm primary/backup header CRC,
   entry array CRC, capacity, usable ranges và mâu thuẫn giữa các bản hợp lệ.
2. Xác minh volume identity/boundary theo báo cáo. GPT entry array size phụ thuộc
   entry count/size, không mặc định 32 sectors; backup cuối ảnh không đúng nếu
   ảnh bị cắt hoặc chỉ là ảnh partition.
3. Dùng `overlay_proposal` khi đủ điều kiện. Array copy và header patch là bước
   riêng; header cần tái tạo current/alternate LBA, array location và CRC.
   Không copy nguyên backup header về primary.
4. `virtual_patch_and_verify` chỉ vá overlay. Kiểm lại topology và NTFS/FAT root
   traversal. UNVERIFIED không chứng minh volume mount được, patch vẫn còn.
5. Nếu không đủ backup, có thể dùng `SIMD_VBR_HUNT` trên ảnh với range có budget.
   VBR hit là candidate, cần geometry/overlap/identity chứ không chỉ 55AA.
6. Chỉ dựng partition hypothesis khi có bằng chứng độc lập; không tự điền start
   2048/size phỏng đoán hoặc dùng tham số scan_step_sectors không có trong schema.
7. Xuất file, kiểm provenance/content theo [report](../../recovery-triage/references/report-and-handoff.md).
   Partition repair ảo không sửa controller, persistence hay dữ liệu đã không còn.

Nếu scan không ra candidate hoặc ảnh toàn fill, chuyển
[zero-hit/coverage](../../recovery-triage/references/acquisition-and-formats.md#zero-hit).
