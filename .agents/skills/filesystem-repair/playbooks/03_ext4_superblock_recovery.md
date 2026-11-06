# Ext4: nhận diện và chuyển engine phù hợp

Native resc chưa có Ext4 superblock recovery, journal/extent-tree reconstruction
hoặc root inode extraction. Không dùng virtual_patch_and_verify NTFS/FAT SUCCESS
để tuyên bố Ext4 mount được.

Primary superblock thường ở byte offset 1024 từ đầu filesystem; signature là
bằng chứng nhận dạng, không đủ xác định healthy volume. Backup placement phụ thuộc
block/group geometry và feature flags như sparse_super/sparse_super2; không dùng
một danh sách block/LBA cố định cho mọi nguồn, đặc biệt với 4Kn.

Bảo toàn acquisition, xác minh filesystem start/block size/features và dùng
engine Ext4 trên **bản sao**. Không chạy fsck sửa nguồn hay copy backup superblock
mù vào overlay rồi báo recovered. Giữ journal/extent provenance và phân biệt
deleted extents với blocks đã tái cấp phát.

Đọc [format/encryption/RAID routes](../../recovery-triage/references/acquisition-and-formats.md)
và [báo cáo giới hạn](../../recovery-triage/references/report-and-handoff.md).
