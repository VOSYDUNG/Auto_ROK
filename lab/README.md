# Lab — phần cứng và tăng tốc

Thành lập: 2026-09-20 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](../docs/PROJECT_DECLARATION.md)

## Lab này để làm gì

Trả lời một câu duy nhất, bằng số đo chứ không bằng cảm giác:

> **Muốn nhanh hơn thì thêm linh kiện nào, và thêm vào có đáng không?**

Nó sinh ra từ phép loại suy nhúng của người vận hành: một con ESP32 điều khiển được cánh
tay robot vì nó có **tín hiệu sạch** và **tri thức nạp sẵn**, không phải vì nó mạnh. Khi
cần thêm năng lực, hệ nhúng **gắn thêm một con chip cho một việc cụ thể** — không phải
nâng cấp toàn bộ.

Lab áp dụng đúng kỷ luật đó: **đo trước, xác định việc cụ thể, rồi mới nói tới linh kiện.**

## Kỷ luật của lab

1. **Đo trước khi mua.** Không đề xuất phần cứng nào trước khi có số đo chứng minh phần
   mềm hiện tại đã hết cách.
2. **Một linh kiện, một việc.** "Gắn GPU cho nhanh" không phải mục tiêu. "Gắn X để chạy Y
   nhanh hơn N lần" mới là.
3. **Ghi cả kết quả âm.** Thứ gì không đáng làm cũng phải ghi lại kèm lý do, nếu không sáu
   tháng sau sẽ có người đề xuất lại.
4. **Lab không được đổi ranh giới sản phẩm.** `PROJECT_DECLARATION` §5 hiện **cấm mọi đường
   chạy phụ thuộc GPU**. Lab được phép nghiên cứu và **đề xuất sửa tuyên bố**, nhưng không
   được lặng lẽ thêm GPU vào runtime.

## Tài liệu

| Tài liệu | Nội dung |
|---|---|
| [`HARDWARE_INVENTORY.md`](HARDWARE_INVENTORY.md) | Phần cứng thật, đo ngày 2026-09-20 |
| [`GPU_ACCELERATION_STUDY.md`](GPU_ACCELERATION_STUDY.md) | Quadro M1200 có dùng được không, và câu trả lời bất ngờ |

## Phát hiện đầu tiên, và nó quan trọng

Máy đang chạy dự án **không phải** Dell Precision 7520. Nó là một workstation X99:

```
Intel Xeon E5-2686 v4 · 18 nhân / 36 luồng · 45 MB L3
64 GB RAM
AMD Radeon R5 430 2GB  (chỉ xuất hình, không có CUDA)
```

Và con số quyết định:

```
gpt-oss-20b MXFP4      = 11,3 GB
Quadro M1200 VRAM      =  4,0 GB
```

**Model lớn gấp 2,8 lần toàn bộ bộ nhớ của GPU đó.** Chi tiết ở
[`GPU_ACCELERATION_STUDY.md`](GPU_ACCELERATION_STUDY.md).

## Câu hỏi đang mở

Xếp theo thứ tự nên nghiên cứu — câu rẻ nhất trước.

| # | Câu hỏi | Vì sao trước |
|---|---|---|
| 1 | `llama-server` có đang dùng đủ 36 luồng không? | miễn phí, có thể là toàn bộ vấn đề |
| 2 | Bản llama.cpp từ WinGet có biên dịch cho AVX2 không? | Broadwell có AVX2, không có AVX-512 |
| 3 | Model 3B–7B có đủ cho vai trò biên quyết định không? | nhỏ hơn thì nhanh hơn **và** vừa GPU 4GB |
| 4 | Quadro M1200 lắp được vào máy X99 không? | MXM là chuẩn laptop, không cắm thẳng vào desktop |
| 5 | Offload một phần lên 4GB có nhanh hơn CPU thuần không? | với Maxwell qua PCIe, thường là **chậm hơn** |
| 6 | Việc gì trong dự án đáng gắn coprocessor riêng? | đúng tinh thần nhúng, khác hẳn "thêm GPU" |
