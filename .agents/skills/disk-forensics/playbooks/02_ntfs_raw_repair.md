# NTFS RAW: xác minh boot trước, không hứa MFT undelete

RAW có thể do metadata, sai offset, encryption hoặc nguồn đọc sai. Hoàn tất
[reader/triage](../../recovery-triage/SKILL.md) trước khi vá.

1. Lấy partition boundary từ topology hoặc bằng chứng độc lập. Không mặc định
   mọi volume bắt đầu LBA 2048; ảnh partition có thể bắt đầu 0.
2. Gọi `analyze_partition_recovery` với `partition_start_lba`; đối chiếu NTFS
   primary/backup, bytes per sector 512/4096, cluster/record geometry, MFT locations
   và identity. Header signature hợp lệ không chứng minh toàn volume tốt.
3. Backup ở partition end được xác minh; trường BPB total-sectors có thể không
   gồm backup. Không thử cả hai công thức tùy tiện khi chưa biết boundary.
4. Nếu proposal phù hợp, dùng `virtual_patch_and_verify` với
   `copy_from_lba`, `to_lba`, `partition_start_lba` và session ID.
5. SUCCESS chỉ root traversal + file entry; xuất allocated files bằng native
   `TSK_TREE_EXTRACT`, kiểm hash/manifest/format. Quotas và unsupported attributes
   vẫn có thể khiến extraction partial/fail.
6. MFT damage nặng/deleted/attribute lists cần engine chuyên biệt. Không tự sao
   chép "đúng bốn records 1024 byte" từ MFTMirr: số lượng/record size và fixups
   phải theo geometry. Chưa có automatic MFTMirr reconstruction trong resc.
7. `scan_filesystem_journals` là NotImplemented; không dùng để verify một patch
   hoặc kết luận deleted MFT/USN đã phục hồi.

Nếu payload không tồn tại trong view hoặc sau reconnect mất, boot repair không
tạo lại dữ liệu; đi [reader controls](../../recovery-triage/references/reader-controls.md).
