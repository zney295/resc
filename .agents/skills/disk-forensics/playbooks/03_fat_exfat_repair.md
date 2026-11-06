# FAT32 và exFAT: tách capability

## FAT32 native

- Xác minh capacity/sector size trước. Lấy partition start/end và gọi
  `analyze_partition_recovery`; dùng BPB backup pointer/reserved-region checks,
  không mặc định backup luôn ở +6.
- Chỉ áp proposal phù hợp vào overlay với `partition_start_lba`. Cả 512 và 4096
  có thể hợp lệ; bytes-per-sector khác 512 không tự là corruption.
- FAT mirror có thể disabled và chọn active FAT. Không tự copy FAT2 lên FAT1
  chỉ vì một bản có vẻ chứa nhiều entry hơn.
- Dùng native allocated-file extraction khi root đọc được. Deleted case dùng
  `FAT32_DELETED_SCAN`: root SFN có budget, không LFN/subdirectories/chain inference.
  Single-cluster candidate còn cần content validation, không được gọi đã recovered.
- FSInfo free count 0xFFFFFFFF có thể là unknown hợp lệ. FSInfo là hint, không
  phải bản sao payload hay bằng chứng nguyên nhân Windows yêu cầu format.

## exFAT external handoff

Marker exFAT có thể được triage nhận ra nhưng native recovery/mount/checksum/
allocation bitmap traversal chưa có. Không copy 12 boot sectors bằng
`inspect_sector_structure(count=12)`: tool chỉ cho 1..8 và không verify exFAT.
Không coi main/backup phải giống byte tuyệt đối; boot checksum có các trường bị
loại trừ theo specification. Không đưa thuật toán checksum không triển khai thành
kết quả xác minh của resc.

Giữ ảnh/map và dùng engine hiểu exFAT trên bản sao theo
[format routes](../../recovery-triage/references/acquisition-and-formats.md).
