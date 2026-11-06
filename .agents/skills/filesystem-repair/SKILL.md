---
name: filesystem-repair
description: Kiểm chứng metadata NTFS/FAT32 và sửa thử bằng overlay; định tuyến RAW, mất phân vùng, deleted/format, exFAT/Ext4/mã hóa mà không ghi lên nguồn.
metadata:
  version: "3.0"
---

# Sửa thử filesystem theo bằng chứng

Đọc [triage](../recovery-triage/SKILL.md) trước. Chỉ phân tích logic sau khi nguồn
có capacity/geometry đáng tin và đã bảo toàn acquisition. `No Media` không phải
lỗi filesystem. RAW cũng có thể là encryption, sai offset hoặc format chưa hỗ trợ.

1. Mở **ảnh** với sector size đúng; `scan_disk_topology` và
   `analyze_partition_recovery` so primary/backup/bounds/CRC.
2. Xác minh partition start/end, volume identity và proposal; không mặc định start
   2048, backup GPT array 32 sectors, FAT32 backup +6 hay NTFS BPB count luôn gồm
   sector backup. Không chọn tùy tiện giữa hai bản hợp lệ nhưng mâu thuẫn.
3. Áp dụng proposal được kiểm tra bằng `virtual_patch_and_verify` trong overlay,
   kèm `partition_start_lba`. GPT header phải được tái tạo location/CRC; không
   copy nguyên backup header về primary.
4. `UNVERIFIED` vẫn để patch trong overlay. Ghi patch/revision và lỗi; không
   chồng thêm patch vô căn cứ để ép SUCCESS. Session mới/resume có thể replay WAL.
5. `SUCCESS` chỉ là root traversal + một file entry. Xuất allocated NTFS/FAT qua
   `TSK_TREE_EXTRACT`, kiểm file và manifest, không công bố toàn volume đã lành.
6. Deleted FAT32: `FAT32_DELETED_SCAN`, root SFN có giới hạn; free single-cluster
   plan chưa xác minh payload. Không dùng allocated tree extraction làm undelete.
7. NTFS deleted MFT/journals, ADS/compressed/encrypted/sparse extraction,
   exFAT/Ext4/RAID reconstruction chưa native. Dùng nhánh
   [formats/handoff](../recovery-triage/references/acquisition-and-formats.md),
   ghi external/not-run. Không gọi journal NotImplemented để kiểm chứng.
8. Chỉ metadata còn nguyên trong khi payload mất sau reconnect: chuyển
   [reader/persistence](../recovery-triage/references/persistence-lab.md);
   sửa filesystem không làm bytes không còn xuất hiện trở lại.

## Tài liệu

- [NTFS/VBR và giới hạn MFT](playbooks/01_ntfs_mft_recovery.md)
- [FAT32 FSInfo/exFAT](playbooks/02_fat32_exfat_fsinfo.md)
- [Ext4 và external handoff](playbooks/03_ext4_superblock_recovery.md)
