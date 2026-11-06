# Async job, terminal state và cursor thật

Gọi tools/list; dùng job_id từ start_async_disk_job hoặc extract_recovered_data.
Không bịa schedule tool hay kết quả results[] chưa trả về.

Ví dụ đối tượng tools/call:

```json
{"name":"poll_async_job","arguments":{"job_id":"ID_FROM_START"}}
{"name":"read_scan_hits","arguments":{"session_id":"ID_FROM_OPEN","job_id":"ID_FROM_START","cursor":0,"limit":20}}
```

Các hình dạng status JSON (nằm trong report của tool):

```json
{"Running":{"progress_percent":25.0,"message":"...","sectors_processed":100,"items_found":2,"bytes_written":0}}
{"Completed":{"result":{}}}
{"Failed":{"error":"..."}}
"Cancelled"
```

- Poll có khoảng nghỉ phù hợp thời gian job và tiếp tục công việc độc lập.
  Không busy-wait, cũng không rời task với lời hứa job đã xong.
- Hit cursor là byte offset next_cursor trả về, không row index/limit cộng dồn.
  Trang bị giới hạn bởi JSON budget có thể ngắn hơn requested limit.
- Cancel bằng poll_async_job(job_id,cancel=true), chờ terminal acknowledgement.
  Một job commit xong trước cancel vẫn Completed; kiểm output thực tế.
- Completed phải đọc result/status clone/map; partial acquisition có thể zero-fill.
- Giữ WAL/hit files/source binding và staged commit recovery paths. Session reopen
  không tự resume job. Quota/no-space không được xử lý bằng xóa chứng cứ.
- Không có overlay_memory_used_kb hoặc auto flush 512 MB như tài liệu lịch sử.
  Xem capabilities cho patch-history/WAL bounds, không clear/reopen để mất state.

Zero-hit chuyển [coverage/reader/format](../../recovery-triage/references/acquisition-and-formats.md#zero-hit);
báo kết quả theo [template](../../recovery-triage/references/report-and-handoff.md).
