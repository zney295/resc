# Reader controls: phân biệt lỗi input, phần mềm và media

Mục tiêu: kiểm tra giả thuyết về đường đọc, không chọn trước lỗi phần cứng hay resc.
Lưu ảnh hiện có trước; thử trên ảnh chuẩn và media đối chứng ổn định. Không cần
đọc lại toàn USB đang lỗi nhiều lần để làm thí nghiệm.

## Chuẩn hóa phép so

Mỗi capture ghi: source model/serial/identity, OS/driver/tool version, file/device
path, capacity, logical sector size, input là disk hay volume, start byte, length,
buffer/chunk size, buffered/direct flags, thời gian, overlay/WAL revision, read
errors/short reads/cancellation và acquisition map. Tính byte_offset = LBA ×
sector_size; volume-relative offset phải cộng partition start khi so whole disk.

So cùng phạm vi trong ảnh nguồn gốc, không so overlay đã vá với nguồn chưa vá.
Giữ cùng chunk size trong phép so đầu; sau đó chỉ đổi một biến (chunk/flags/reader).
Không gọi hai reader "độc lập" nếu thực chất cùng một backend/library/handle.

| Phép đối chứng | Câu hỏi | Giới hạn |
| --- | --- | --- |
| Ảnh chuẩn có hash biết trước, qua reader A/B | Backend có trả đúng offset, tail, geometry, bytes trên 2 GiB không? | File backend pass chưa kiểm raw-device backend |
| USB khỏe có payload/hash biết trước, cùng OS/reader | Raw-device path có khác file path? | USB khỏe pass không loại lỗi tương thích theo thiết bị |
| Cùng reader, cùng cửa sổ, đọc lặp có giới hạn | Dữ liệu/đường đọc có thay đổi? | Khác nhau chưa phân biệt cache, concurrent writes, power hoặc hardware |
| A và B cùng offset/length, mỗi reader tự ổn định | Backend/flags/offset/chunk nào khác? | Hai luồng khác nhau chưa biết bên nào đúng |
| Lặp tại cửa sổ sau reconnect khi được phép | Dữ liệu quan sát có phụ thuộc phiên/caching? | Không phải persistent write test nếu không có payload gốc |

Ưu tiên cửa sổ đã biết có dữ liệu khác 00/FF, kèm đầu/giữa/cuối nếu cần và trong
capacity. Ghi tổng bytes đã đọc và điều kiện dừng; ví dụ một số cửa sổ 4 KiB đến
1 MiB với budget nhỏ. Thiết bị lỗi/đọc suy giảm thì dừng sớm, không ép đủ mẫu.
Không đề xuất thử ghi lên USB thật trong bước kiểm chứng reader chỉ đọc.

## Diễn giải

- Cùng reader đổi bytes: chuyển UNSTABLE_IO/READER_DISAGREEMENT; giữ snapshots và
  lỗi, kiểm concurrent writes/identity/map trước kết luận component.
- A/B ổn định nhưng khác: tái hiện trên ảnh chuẩn và USB đối chứng; điều tra offset,
  direct/buffered I/O, alignment, cache và short-read handling; chưa tự chọn A/B.
- Mọi reader cùng 00/FF: chỉ xác nhận các view quan sát cùng dạng; không chứng
  minh dữ liệu gốc bị xóa, TRIM hoặc NAND đã chết. Hash nguồn gốc/map còn thiếu?
- Hash ảnh khớp luồng sao lưu: xác nhận sao chép luồng đó, không chứng minh USB
  trả bytes người dùng từng lưu. Native extraction test pass cũng không chứng
  nhận backend USB vật lý.
- Ví dụ 6/16 mẫu khác chỉ là 6 cửa sổ dưới điều kiện đã ghi, không phải error rate
  37.5% của USB/reader hay tỷ lệ byte mất; không trộn khác reader/I/O/time làm một.

So ảnh đã lưu bằng [evidence_audit.py compare](audit-helper.md); helper không mở
raw devices, bypass cache hay tạo thêm capture. Báo first differing ranges và
coverage, giữ full JSON để xem phần bị cắt trong interactive report.
