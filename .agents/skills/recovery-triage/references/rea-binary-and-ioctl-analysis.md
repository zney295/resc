# Phân tích nhị phân và IOCTL với REA

Áp dụng khi cần xác minh hành vi từ một PE, DLL, driver hoặc bộ cấu hình có sẵn. Giữ định danh file, phiên bản, SHA-256 và xuất xứ của từng mục tiêu. Đọc tĩnh các tệp `.ini` để tìm bảng tương thích, mã nhận diện thiết bị và tùy chọn. Một mục trong bảng cấu hình chỉ mô tả cấu hình của công cụ đó.

1. Dùng catalog REA hiện tại để chọn tool. `inspect_pe_resources` kiểm tra tài nguyên PE. Với bảng import/export, dùng tool tương ứng nếu có hoặc `llvm-readobj --coff-imports --coff-exports <file>`.
2. Khi có provider native, mở binary tĩnh và truy xref tới `DeviceIoControl` hoặc `NtDeviceIoControlFile`. Kiểm tra calling convention và lần ngược giá trị IOCTL cùng cấu trúc input tại từng call site. Trên Windows x64, `DeviceIoControl` nhận IOCTL ở `EDX`. Giữ địa chỉ, bytes, đường dữ liệu và nhánh gọi. Import chỉ chứng minh liên kết với API.
3. Với `SCSI_PASS_THROUGH_DIRECT`, kiểm tra access bits của IOCTL, độ dài CDB, chiều truyền, offset sense buffer và ABI. Các IOCTL pass-through của Windows yêu cầu handle có quyền đọc/ghi. Resc dùng handle `GENERIC_READ` với các truy vấn storage descriptor, dung lượng và trạng thái chống ghi của Windows.
4. Lưu bằng chứng dạng tóm tắt với ID, SHA-256, phạm vi, mức quan sát hay suy luận và các câu hỏi còn mở. Đóng phiên phân tích native khi xong. Kiểm chứng cấu trúc trước khi tích hợp bằng ảnh tổng hợp. Lệnh vendor, thay layout vật lý và firmware nằm ngoài luồng resc.

## Quan sát trên bản Windows của phiên nâng cấp

- `diskpart.exe` SHA-256 `a9882c2c19922af201780dbce7b2f8d41b0d4341784e63bf40baf3a986ca0c7b`. Tài nguyên PE trong REA `ev_944551d9aa71f9ded3de5d5f9984c418b6905148102241d8689137541b74aa2f`. `llvm-readobj` thấy import `DeviceIoControl` và `CreateFileW`.
- `fmifs.dll` SHA-256 `be3b68c20faf690d10654fae158c5f5b5b56def904a3138dc06fe951e5d0e416`. Tài nguyên PE trong REA `ev_ed24e87ff492a3c6aa07ce85bdd75b86fb07277b0781417c066d3725238ae4bc`. `llvm-readobj` thấy cùng hai import và export `FormatEx`, `FormatEx2`.

`llvm-objdump` xác nhận các lệnh nạp trực tiếp vào `EDX` trước lời gọi qua IAT.
Địa chỉ dưới đây là RVA tính từ image base của đúng binary đã băm.

| Mục tiêu | RVA của lời gọi | IOCTL quan sát |
| --- | --- | --- |
| `diskpart.exe` | `0x6B4E`, `0x9497`, `0x94DE` | Tương ứng `0x70050`, `0x7C054`, `0x70140` |
| `fmifs.dll` | `0x3A75`, `0x92AD`, `0x932F`, `0x9C10` | `0x90260` |
| `fmifs.dll` | `0x3ACA`, `0x5224`, `0x52F9` | Tương ứng `0x90078`, `0x9C040`, `0x9C280` |

Các call site trên xác nhận đối số cục bộ. Đường gọi hoàn chỉnh của từng thao tác và hành vi của phần mềm hãng còn cần binary và provider phù hợp. Khi dữ liệu đọc về lặp `00`/`FF`, ghi lại phạm vi, trạng thái I/O, lần đọc lặp và điều kiện thu nhận. Chẩn đoán FTL hoặc NAND cần bằng chứng riêng từ phần cứng hoặc firmware.

[REA](https://github.com/morluto/rea) · [Windows SDK ntddscsi.h](https://raw.githubusercontent.com/tpn/winsdk-10/master/Include/10.0.16299.0/shared/ntddscsi.h) · [Storage property query](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddstor/ni-ntddstor-ioctl_storage_query_property)
