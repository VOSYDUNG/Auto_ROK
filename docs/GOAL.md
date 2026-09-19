# Mục tiêu Auto_ROK

Ngày: 2026-09-19 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)

---

## 1. Mục tiêu sản phẩm

Đưa một mô hình ngôn ngữ chạy cục bộ vào vị trí biên quyết định của một vòng lặp vận hành
Rise of Kingdoms, trên đúng một máy Windows thật, một tài khoản đã đăng nhập, một client
đang hiển thị, chỉ dùng CPU và RAM.

Chủ ngữ là **LLM local**. Harness tồn tại để biến một tình huống game thành một bài toán
quyết định nhỏ, đáng tin, có bằng chứng — rồi thi hành đúng một hành động đã được chốt
chặn và chứng minh kết quả nhìn thấy được.

Hệ thống chỉ được coi là thành công khi vòng lặp đó **xác định, đo được, và fail-closed**.

> Lưu ý sửa sai: bản GOAL trước ngày 2026-09-19 viết *"harness là sản phẩm mà LLM local
> được huấn luyện và kiểm thử xoay quanh nó"*. Đó là đảo ngược. Dự án xoay quanh LLM
> local; harness là nền 80%.

---

## 2. User story của LLM local

Đây là tài liệu trung tâm của dự án, không phải phụ lục.

**Khi** harness có một quan sát tươi, gắn nguồn gốc, và có nhiều hơn một bước đi hợp lệ,
**thì** LLM local nhận đúng một gói ngữ cảnh có cấu trúc tối thiểu cùng danh sách ứng
viên đã được lọc sẵn.

Nó trả về đúng một trong ba thứ:

1. **một `ActionChoice` có sẵn trong danh sách** — không được bịa ra lựa chọn mới;
2. **`NEEDS_DECISION`** — khi bằng chứng không đủ để chọn;
3. **`retraining_required`** — khi nhận ra bề mặt game đã thay đổi so với kiến thức đã
   huấn luyện.

Nó **không bao giờ** nhìn thấy toạ độ màn hình thô, trạng thái game ẩn, bộ nhớ tiến trình,
hay một bề mặt điều khiển desktop tự do. Nó **không bao giờ** phát chuột hay phím.

Model mục tiêu thuộc lớp Qwen hoặc GPT-OSS chạy cục bộ. Phần suy luận của nó là một biên
quyết định nhỏ, khoảng 20% vòng lặp; 80% còn lại và **toàn bộ** quyết định an toàn thuộc
về logic xác định của harness.

### Luôn bật, không luôn có việc

Dịch vụ model chạy thường trực như người quan sát rảnh. "Luôn bật" không có nghĩa "luôn
được giao nhiệm vụ". Harness chỉ gửi gói khi có tín hiệu `NEEDS_DECISION` hoặc
`UNKNOWN_STATE` thật. Model không sở hữu đồng hồ, lịch, cờ hoàn thành, quyền tiêu tài
nguyên, hay kênh phát input.

---

## 3. Hợp đồng harness

Harness sở hữu:

- ROI client cố định đã huấn luyện, thu hình và tri giác chỉ bằng CPU;
- OCR/CV, chiếu trạng thái, nguồn gốc khung hình;
- đồ thị mission, chính sách, lọc ứng viên;
- nối đất mục tiêu, cô lập input, actuation có chốt chặn;
- phê duyệt gắn occurrence, checkpoint, retry/recovery, huỷ lệnh;
- xác minh hậu điều kiện trên khung hình tươi, và bằng chứng bất biến;
- dòng thời gian mission dựa trên dữ liệu, và kho kiến thức cục bộ cho các dữ kiện về
  reset, cooldown, cửa sổ sự kiện và hàng đợi.

**Toạ độ là ràng buộc quan sát/hiệu năng, không phải giấy phép để bấm.** Mọi hành động
vẫn phải được nối đất vào khung hình hiện tại, occurrence hiện tại và trạng thái phê
duyệt hiện tại.

---

## 4. Lát cắt đang nhận

`GATHER_RESOURCE` một nhân vật là lát cắt dọc tham chiếu. Các mission khác chưa được đưa
vào nghiệm thu cho tới khi có hợp đồng quan sát, chính sách, hành động và xác minh của
riêng chúng.

Nhánh mission thứ hai `CLAIM_ALLIANCE_TERRITORY_RSS` đã có mặt ở mức **partial** và đang
bị chặn bởi blocker `A001` — chữ ký hoàn thành sau nút Claim chưa được huấn luyện.

Bản đồ trạng thái/mission có ràng buộc bằng chứng nằm ở
[`docs/GAME_STATE_MISSION_MATRIX.md`](GAME_STATE_MISSION_MATRIX.md); nó là hàng rào phạm
vi, ngăn việc nâng cấp các nhánh chưa được xác minh.

Entrypoint duy nhất: `scripts/run_gather_tick.py`.

---

## 5. Định nghĩa hoàn thành — G1 đến G6

Đây là **hệ đánh số duy nhất** của dự án. Nó được thi hành bằng máy, không bằng lời:
`scripts/audit_goal_readiness.py` đọc bằng chứng thật trong `workspace/evidence/` và trả
về pass/blocked cho từng cổng.

| Cổng | Nội dung |
|---|---|
| **G1** | Cô lập input trên host Windows thật: ràng buộc đúng cửa sổ đích, foreground ổn định, từ chối khung hình cũ, huỷ lệnh/khôi phục được, và không có input ngoài ý muốn |
| **G2** | Ngưỡng CPU và OCR/trạng thái đạt trên tập holdout, mà không hạ đường nối đất runtime xuống mức mờ hoặc phụ thuộc GPU |
| **G3** | Hợp đồng `NEEDS_DECISION` của LLM local được đo trên các ca holdout rời khung hình. Chỉ gọi được model thì không phải nghiệm thu |
| **G4** | Phê duyệt B003 gắn tường minh vào occurrence, nhân vật, và lựa chọn quân/tướng đang nhìn thấy |
| **G5** | Một tick GATHER có giới hạn chứng minh được hậu điều kiện nhìn thấy `Queue used +1`, kèm bằng chứng huỷ/tiếp tục/khôi phục, không replay ngoài phạm vi |
| **G6** | Chỉ sau khi G1–G5 đạt mới được chạy endurance, và chỉ khi có uỷ quyền tường minh của người vận hành |

Bằng chứng cũ, thiếu, mơ hồ, lệch nhau hay không kiểm chứng được đều **dừng vòng lặp**.
Không phát input trước khi cổng liên quan và phê duyệt tương ứng có mặt.

### Điều kiện của G6

Lặp R3 phải được người vận hành uỷ quyền riêng. Bản audit chỉ chấp nhận file
`workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` gắn đúng hợp đồng occurrence
GATHER đang hoạt động và có `max_additional_runs` tường minh. Bằng chứng runtime mỗi tick
là append-only; đường dẫn trùng thì fail-closed chứ không ghi đè bản ghi cũ.

---

## 6. Mục tiêu năng suất của lát cắt GATHER

Ngoài việc đạt G1–G6, lát cắt GATHER có một mục tiêu vận hành đo được:

- **lấp đầy hàng đợi hành quân** — đưa chỉ số `n/5` lên `5/5`;
- **giữ buff tăng tốc thu thập không về 0** trong suốt chu kỳ 24h.

Hai đòn bẩy này độc lập và đều có thể gãy nhịp độc lập. Cách tính và cách đo nằm ở
[`knowledge/gathering_continuity_2026-09-19.yaml`](../knowledge/gathering_continuity_2026-09-19.yaml).

---

## 7. Không thuộc phạm vi

- không Docker, máy ảo, Hyper-V, không đường chạy GPU;
- không tác tử desktop tự do không giới hạn;
- không đọc bộ nhớ tiến trình, không chèn code vào game;
- không nghiệm thu chỉ dựa trên việc gọi được model qua HTTP, một biên nhận gửi lệnh, hay
  một tỉ lệ OCR chung chung;
- không tái dùng phê duyệt cũ hay replay cũ ngoài occurrence hiện tại.
