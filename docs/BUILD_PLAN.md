# Kế hoạch xây dựng — Auto_ROK

Ngày: 2026-09-19 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)
· Thiết kế: [`docs/DESIGN_BRIEF.md`](DESIGN_BRIEF.md) · Gameplay: [`docs/LLM_GAMEPLAY_SPEC.md`](LLM_GAMEPLAY_SPEC.md)

Kế hoạch được sắp theo **thứ tự phụ thuộc thật**, không theo mức độ hào hứng. Mỗi giai đoạn
ghi rõ: làm gì, chặn bởi cái gì, xong khi nào.

Nguyên tắc sắp xếp: **làm hết phần không cần game trước.** Giai đoạn cần mở client là tài
nguyên khan hiếm nhất (cần người vận hành có mặt), nên phải dồn lại và làm một lượt.

---

## Bảng điểm — bốn con số treo trên tường

Người vận hành muốn giữ cả bốn. Chúng được **xếp tầng**: một cái phân xử khi mâu thuẫn, ba
cái giải thích vì sao nó nhúc nhích.

| | Chỉ số | Hôm nay | Đo cái gì |
|---|---|---|---|
| **★** | **Giờ chạy tự chủ liên tục không cần người chạm** | ~0 | **North star.** Nuốt cả ba cái dưới |
| | Số lần LLM vào cuộc / 100 tick | chưa đo | độ sâu harness — chính là tỉ lệ 80/20 |
| | Số lần tự phát hiện game đổi | 0 | khả năng sống qua thay đổi |
| | % thời gian hàng đợi đầy **và** buff ≠ 0 | chưa đo | sức khoẻ bãi thử |

Thêm một chỉ số cho luận đề *micro AGI tự nuôi*:

| Chỉ số | Hôm nay | Đo cái gì |
|---|---|---|
| % tri thức miền mới do hệ thống tự đề xuất | 0% | bộ não thứ hai có tự viết được không |

---

## P0 — Nền móng · không cần game

**Vì sao trước tiên:** mọi giai đoạn sau đều import code mới. Hiện `pytest tests/` gõ trực
tiếp là gãy, import chạy nhờ `sys.path.insert` lặp trong 32/42 script, một script hardcode
đường dẫn tuyệt đối của đúng máy này.

1. `pyproject.toml` + `conftest.py` → bỏ toàn bộ `sys.path` hack
2. `autorok/llm/boundary.py` — gộp hai danh sách lọc trùng (Design Brief R2), cả hai tầng
   cùng dùng. Giữ nguyên tắc danh sách cho phép
3. Đưa `autorok.mission` vào `config/engineering_graph.yaml`
4. CI chuyển sang `windows-latest`, chạy `pytest tests/` đầy đủ thay vì danh sách 22 file cứng

**Xong khi:** `pytest` chạy từ thư mục bất kỳ · một danh sách lọc duy nhất · CI xanh trên
Windows với toàn bộ 56+ file test.

---

## P1 — Thang suy giảm và tầng chiến lược · không cần game

**Vì sao ở đây:** đây là luận đề sản phẩm. Tầng chiến lược hiện có nhà sản xuất gói
(`MissionScheduler.decision_packets()`) mà **không có người nhận** — nó dựng gói rồi vứt đi.

1. `autorok/mission/ladder.py` — 5 bậc `ORDER_WORK → OBSERVE_ONLY`, mỗi lần tụt ghi lý do
2. `autorok/llm/strategic.py` — người nhận cho gói chiến lược, trả `MissionIntent`
3. Nối `MissionScheduler` → `strategic` → thang suy giảm
4. Ghi nhịp đo vào `mission_knowledge` SQLite (bảng đã có sẵn)
5. Viết lại holdout LLM để đo **tầng chiến lược**, không phải lựa chọn 4 nhánh

**Xong khi:** một chu kỳ lập kế hoạch chạy offline từ trạng thái đội hình giả lập, tụt đủ 5
bậc khi bị chặn, không bao giờ trả về "không có việc".

**Đây là lúc 20,6 giây chuyển từ lỗi chặn thành không quan trọng** — ở tầng này harness đang
chờ quân về hàng giờ.

---

## P2 — Đường OCR · không cần game

**Số đo:** 4.525 ms/khung so với ngưỡng 400 ms. Nguyên nhân: script 711 dòng gọi 11 lần
`RecognizeAsync`, mỗi crop **ghi PNG ra đĩa rồi decode lại**, cộng 185 ms spawn process và
90 ms nạp WinRT mỗi lần gọi. OCR lõi ấm chỉ 170 ms.

1. Crop trong bộ nhớ, bỏ 11 lần ghi/đọc đĩa
2. Tiến trình OCR thường trú — trả spawn và nạp WinRT về một lần
3. Đo lại. Chỉ khi vẫn chưa đạt mới tính tới binary native (C++ / C# NativeAOT)

**Xong khi:** < 400 ms/khung, kết quả OCR **giống hệt** bản cũ trên tập corpus đã có.

**Ghi chú về C/C++:** phát input đang dưới 1 ms, tức dưới 0,003% một vòng quan sát. Chỗ đáng
dùng ngôn ngữ native là OCR, không phải di chuyển chuột.

---

## P3 — Khảo sát nhân vật · **cần game, chỉ quan sát**

**Đây là pass quan sát đầu tiên.** Không phát input ngoài điều hướng an toàn. Dồn mọi câu
hỏi còn mở vào đúng lượt này.

1. Grounding ba bề mặt: Tướng · City Hall · Chợ
2. `autorok/mission/survey.py` → ghi `OperatorSnapshot` vào `operator_layer` (R5 — schema đã
   có, chưa ai dùng)
3. Tính `tốc độ farm = nền + skill tướng`, thay mốc `OPERATOR_BASELINE` cho từng nhân vật
4. **Trả lời 4 câu còn mở cùng lượt:**
   - bảng *cấp Chợ → hàng mỗi lượt* và số xe
   - màn chi tiết tài nguyên **loại trừ item** nằm ở đâu
   - đường giao: kéo bản đồ hay Chợ → Support, cái nào nối đất chắc hơn
   - chu kỳ xoay hàng Courier Station (cần thấy **2 vòng**)

**Xong khi:** 8 nhân vật có profile gắn bằng chứng · 4 câu trên có đáp án · không phát input
ngoài điều hướng an toàn.

---

## P4 — Giao hàng · **khoá cho tới khi P3 xong**

Không xây nửa vời. Giao hàng là logistics: hàng đợi thứ hai (số xe, do cấp Chợ quyết định),
cộng chi phí tele lại gần phải trả trước.

1. `autorok/mission/delivery.py` — lập kế hoạch nhiều lượt theo sức chứa
2. Nối sổ cái `DeliveryLedger` (đã xong) vào đường thi hành
3. Cổng nghiệm thu riêng cho hành động chuyển tài sản

**Chặn bởi:** bảng cấp Chợ (P3) · đường giao (P3) · **thuế bao nhiêu phần trăm** — người vận
hành cho số.

**An toàn:** game cho giao hết, nên không có trần hành động nào để dựa vào. **Sổ cái đúng
chính là cơ chế an toàn duy nhất.** Vì vậy mọi bút toán bắt buộc có `evidence_ref` — đã
cưỡng chế trong `autorok/mission/order.py`.

---

## P5 — Chạy thật · cần game, có phát input

1. Nối `autorok.mission` vào `scripts/run_gather_tick.py`
2. Lấp hàng đợi một nhân vật tới **5/5**
3. Xoay vòng hai cấp qua 8 nhân vật
4. Đo north star: giờ chạy tự chủ liên tục

**Chặn bởi:** P0–P3. Và G6 chặn bởi **chữ ký của người vận hành**, không phải bởi code —
bản audit chỉ chấp nhận `workspace/evidence/gather/R3_ENDURANCE_AUTHORIZATION.json` có
`max_additional_runs` tường minh.

---

## Phụ thuộc

```
P0 nền móng ──┬── P1 thang + chiến lược ──┐
              └── P2 OCR ─────────────────┼── P5 chạy thật
                       P3 khảo sát ───────┤
                       P4 giao hàng ──────┘
                        ↑ chặn bởi P3 + số thuế
```

**Làm song song được:** P1 và P2 độc lập nhau sau khi P0 xong.
**Không làm song song được:** P4 phải chờ P3; P5 phải chờ tất cả.

---

## Cái gì KHÔNG làm trong vòng này

| Việc | Vì sao hoãn |
|---|---|
| Chuyển `harness/` vào `autorok/` | 44 module + 56 file test; làm sau khi CI Windows đã bảo vệ |
| Đăng nhập đổi tài khoản (cấp 2) | đổi nhân vật trong game đủ cho 2×4; thông tin đăng nhập là việc riêng |
| Xoá đường guest/VM | nợ đã đặt tên, không chặn gì |
| Nhánh alliance (A001) | GATHER chưa đóng thì chưa mở nhánh hai |
| Port sang ứng dụng khác | đã trả lời được câu hỏi khuôn mẫu; biến thành test sau, khi CI Windows chạy |
| Giao diện vận hành | người vận hành đã nói bản HUD cũ không dùng được; thiết kế lại sau P1 |
