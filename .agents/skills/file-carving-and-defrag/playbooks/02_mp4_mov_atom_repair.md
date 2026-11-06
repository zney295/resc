# MP4/MOV: box evidence và extents, chưa tái tạo moov

ISO BMFF có size32, extended size64 và size0 theo file/view boundary; QuickTime
cũ có thể không ftyp. moov/mdat có nhiều vị trí hợp lệ, không mặc định header mẫu
00 00 00 18 hay moov luôn ở cuối.

1. Trên ảnh ổn định, ISO_BMFF_BOX_SCAN phát hiện plausible ftyp/moov/mdat/moof
   headers. Không dùng SIMD_MAGIC_CARVE với target_patterns tự chế.
2. Đối chiếu box length, filesystem extents, source identity và logical order;
   gần nhau trên disk không chứng minh cùng video.
3. analyze_video_candidate nhận ordered non-overlapping byte ranges. Nó kiểm
   box bounds và stco/co64 chunk starts, không mọi sample extent/timeline/codec.
4. MISSING_MOOV khác CHUNK_OFFSETS_OUTSIDE_MDAT và budget-exceeded. fMP4 cần
   demuxer; thiếu moov không tự cho phép ghép bất kỳ moov từ video khác.
5. CARVE_BY_BYTE_RANGES xuất đúng plan; tool không rewrite stco/co64, tái tạo moov
   hay suy thứ tự mảnh tự động.
6. recovery.py verify-media --decode trên output dùng FFmpeg độc lập. Decoder
   pass vẫn có thể sai nội dung, như counterexample trong nghiên cứu của repo.
7. Nếu dùng Untrunc/donor/remux ngoài resc thì ghi engine/version, donor
   compatibility, generated header/index và derivative provenance; chưa có native
   integration hoặc success rate do skill này tạo ra.

Xem [nghiên cứu](../../../../docs/research/deep-evidence-study.vi.md) và
[format routes](../../recovery-triage/references/acquisition-and-formats.md).
