# Boundary prefilter: heuristic, không phải xác nhận mảnh

FRAGMENT_PREFILTER đánh giá thống kê các block được chỉ định. Nó không lọc theo
FAT/NTFS free allocation và không kiểm codec semantics hoặc đúng nội dung.

Ví dụ đối tượng tools/call; các LBA chỉ để minh họa, phải thay từ bằng chứng
nguồn và kiểm capacity/geometry trước:

```json
{"name":"start_async_disk_job","arguments":{"session_id":"ID_FROM_OPEN","job_type":"FRAGMENT_PREFILTER","params":{"first_fragment_end_lba":100,"candidate_start_lba":200,"candidate_end_lba":300,"cluster_sectors":8}}}
```

Không truyền head_last_lba/search_window_clusters/file_type/top_candidates.
Cluster sectors phải power of two trong phạm vi capability. Điểm cao hoặc
entropy gần nhau chưa chứng minh liên tục, cùng file hoặc đúng thứ tự.

Giữ nhiều hypothesis, bao gồm mảnh nằm trước offset hiện tại. Validate bằng format/
filesystem evidence rồi export byte plan; không quy confidence thành xác suất.
JPEG/PNG/MP4 structure consistent vẫn có thể chứa nhầm payload; kiểm decoder và
nội dung độc lập theo [report](../../recovery-triage/references/report-and-handoff.md).

Nếu nguồn fill thống trị hay reader không đồng ý, quay về
[controls](../../recovery-triage/references/reader-controls.md), không tăng search
window vô hạn.
