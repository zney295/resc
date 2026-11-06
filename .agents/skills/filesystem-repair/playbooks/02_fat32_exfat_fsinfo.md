# FAT32 FSInfo và exFAT: đừng vá hint thành payload

Xem [FAT32/exFAT](../../disk-forensics/playbooks/03_fat_exfat_repair.md).

## FAT32

FSInfo có chữ ký/geometry và free-count/next-free hints; 0xFFFFFFFF có thể là
unknown hợp lệ. Không suy Windows RAW là do free count, không mặc định backup
FSInfo tại +7 trong mọi volume. Nếu root/allocated files đọc được thì ưu tiên
export dữ liệu. Boot/backup proposal do analyze_partition_recovery kiểm tra; chỉ
apply overlay sau identity/boundary evidence.

FAT copies có active/mirroring semantics. Không sao một FAT nguyên vẹn lên bản
khác nếu chưa hiểu allocation/live references. Deleted root scanner tự có các
kiểm tra bảo thủ; không nâng unknown multi-cluster candidate thành file recovered.

## exFAT

Native exFAT recovery/checksum/mount chưa có. Boot checksum không phải XOR đơn
giản; specification loại trừ các byte VolumeFlags/PercentInUse ở offsets 106,
107,112. Không dùng thuật toán thiếu trường loại trừ hoặc copy 12 sectors rồi
công bố Windows nhận được dữ liệu. Main/backup không bắt buộc byte-identical ở
các trường mutable.

Giữ ảnh rồi external handoff bằng engine hiểu boot regions, FAT, allocation bitmap,
upcase/directory entry checks. Không chạy sửa ghi lên nguồn.
